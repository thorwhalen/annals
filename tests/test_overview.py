"""Spoken overviews: asking from the page, the worker, and what a reader sees of each state."""

import stat
import sys
import time

import pytest
from fastapi.testclient import TestClient

from annals import overview
from annals.overview import Requests
from annals.store import DocStore


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


@pytest.fixture
def doc(store):
    return store.publish(text="# Hello\n\nThe parser landed.", title="Hello")["id"]


@pytest.fixture
def requests(store):
    return Requests(store.target.root)


@pytest.fixture
def client(store):
    return TestClient(_app(store))


def _app(store, overviews=True):
    from annals.api import mk_api

    return mk_api(store=store, overviews=overviews)


def _maker(tmp_path, body):
    """A stand-in for the overview command: a script taking {source} {minutes} {out}."""
    script = tmp_path / "maker.py"
    script.write_text(f"import sys\nsource, minutes, out = sys.argv[1:4]\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return [sys.executable, str(script), "{source}", "{minutes}", "{out}"]


GOOD = "open(out, 'w').write('<!doctype html><title>P</title>' + minutes + open(source).read())"


def test_off_by_default(store, doc):
    client = TestClient(_app(store, overviews=False))
    assert "listen" not in client.get(f"/docs/{doc}").json()
    assert client.get(f"/docs/{doc}/overview").status_code == 404
    assert client.post(f"/docs/{doc}/overview", json={"minutes": 3}).status_code == 404


def test_a_page_sees_the_choices_and_their_cost(client, doc):
    listen = client.get(f"/docs/{doc}").json()["listen"]
    assert listen["state"] == "none"
    assert {"minutes": 5, "characters": 4500} in listen["choices"]


def test_asking_queues_once(client, doc, requests):
    assert client.post(f"/docs/{doc}/overview", json={"minutes": 3}).json()["state"] == "queued"
    again = client.post(f"/docs/{doc}/overview", json={"minutes": 7}).json()
    assert again["state"] == "queued" and again["minutes"] == 3
    assert requests.get(doc)["minutes"] == 3


@pytest.mark.parametrize("minutes", [4, 0, 1000, "5", None])
def test_only_the_offered_lengths(client, doc, minutes):
    assert client.post(f"/docs/{doc}/overview", json={"minutes": minutes}).status_code == 400


def test_another_site_cannot_spend_the_money(client, doc, requests):
    r = client.post(f"/docs/{doc}/overview", json={"minutes": 3}, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403 and requests.get(doc) is None


def test_unknown_document_is_404(client):
    assert client.post("/docs/20990101-000000-nope-abcd/overview", json={"minutes": 3}).status_code == 404


def test_what_cannot_be_spoken_is_not_offered(store, client):
    picture = store.publish(text="x", filename="a.bin", title="Binary")["id"]
    assert "listen" not in client.get(f"/docs/{picture}").json()
    assert client.post(f"/docs/{picture}/overview", json={"minutes": 3}).status_code == 400


def test_the_worker_publishes_the_page_and_the_button_finds_it(client, store, doc, requests, tmp_path):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    results = overview.work(store, requests, command=_maker(tmp_path, GOOD))
    assert results[0]["state"] == "done"
    listen = client.get(f"/docs/{doc}").json()["listen"]
    assert listen["state"] == "done" and not listen["stale"]
    made = store.meta(listen["overview"])
    assert made["kind"] == "html" and overview.TAG in made["tags"] and "Hello" in made["title"]
    assert "The parser landed." in store.read_text(made["id"])


def test_an_overview_has_no_overview(client, store, doc, requests, tmp_path):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    made = requests.get(doc)["overview"]
    assert "listen" not in client.get(f"/docs/{made}").json()
    assert client.post(f"/docs/{made}/overview", json={"minutes": 3}).status_code == 400


def test_a_failure_says_why_and_the_next_still_runs(client, store, doc, requests, tmp_path):
    other = store.publish(text="# Other\n\nMore.", title="Other")["id"]
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    bad = "import sys as s\nif 'parser' in open(source).read():\n    s.exit('the voice ran out')\n" + GOOD
    client.post(f"/docs/{other}/overview", json={"minutes": 3})
    overview.work(store, requests, command=_maker(tmp_path, bad))
    failed = client.get(f"/docs/{doc}/overview").json()
    assert failed["state"] == "failed" and failed["error"] == "the voice ran out"
    assert client.get(f"/docs/{other}/overview").json()["state"] == "done"
    # and it can be asked for again
    assert client.post(f"/docs/{doc}/overview", json={"minutes": 3}).json()["state"] == "queued"


def test_a_command_that_writes_nothing_is_a_failure(client, store, doc, requests, tmp_path):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    overview.work(store, requests, command=_maker(tmp_path, "pass"))
    assert "no page" in client.get(f"/docs/{doc}/overview").json()["error"]


def test_a_missing_command_is_a_failure_not_a_crash(client, store, doc, requests):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    overview.work(store, requests, command=["/nonexistent/maker", "{source}", "{out}"])
    assert client.get(f"/docs/{doc}/overview").json()["state"] == "failed"


def test_a_command_must_name_its_inputs(store, requests):
    with pytest.raises(ValueError, match="source"):
        overview.work(store, requests, command=["maker"])
    with pytest.raises(ValueError, match="no overview command"):
        overview.work(store, requests, command=None)


def test_the_document_changing_marks_the_overview_stale(client, store, doc, requests, tmp_path):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    assert not client.get(f"/docs/{doc}/overview").json()["stale"]
    store.publish(text="# Hello\n\nChanged.", title="Hello", replace=doc)
    assert client.get(f"/docs/{doc}/overview").json()["stale"]


def test_a_binned_overview_is_gone_from_the_button(client, store, doc, requests, tmp_path):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    store.trash(requests.get(doc)["overview"])
    assert client.get(f"/docs/{doc}/overview").json()["state"] == "none"


def test_a_request_left_running_belonged_to_a_dead_worker(store, doc, requests, tmp_path):
    requests.put(doc, {"state": "running", "minutes": 3, "version": 1, "started": overview._now()})
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    assert requests.get(doc)["state"] == "failed"


def test_a_second_worker_does_nothing(store, doc, requests, tmp_path):
    overview.request(store, requests, doc, minutes=3)
    with overview._only_one_worker(requests.folder) as mine:
        assert mine
        assert overview.work(store, requests, command=_maker(tmp_path, GOOD)) == []
    assert requests.get(doc)["state"] == "queued"


def test_a_page_is_spoken_as_its_text(store, requests, tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<html><head><title>T</title><style>p{}</style></head><body><p>Words here.</p><script>evil()</script></body></html>")
    doc = store.publish(page, title="Page")["id"]
    overview.request(store, requests, doc, minutes=3)
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    text = store.read_text(requests.get(doc)["overview"])
    assert "Words here." in text and "evil" not in text


def test_the_request_files_do_not_show_up_as_documents(client, store, doc):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    assert [d["id"] for d in store.list()] == [doc]


def test_a_remote_store_cannot_offer_it():
    from annals.api import mk_api
    from annals.target import SshTarget

    remote = DocStore(SshTarget("somehost", "/data"), settle=False)
    with pytest.raises(ValueError, match="on this machine"):
        mk_api(store=remote, overviews=True)


def test_float_and_bool_minutes_are_refused(client, doc):
    for minutes in (3.0, 5.0, True):
        assert client.post(f"/docs/{doc}/overview", json={"minutes": minutes}).status_code == 400


def test_a_current_overview_is_not_paid_for_twice(client, store, doc, requests, tmp_path):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    first = requests.get(doc)["overview"]
    again = client.post(f"/docs/{doc}/overview", json={"minutes": 3}).json()
    assert again["state"] == "done" and again["overview"] == first
    assert client.post(f"/docs/{doc}/overview", json={"minutes": 3, "force": True}).json()["state"] == "queued"


def test_a_crash_after_publishing_does_not_pay_again(store, doc, requests, tmp_path):
    overview.request(store, requests, doc, minutes=3)
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    made = requests.get(doc)["overview"]
    # As if the worker had died between publishing and recording it.
    requests.put(doc, {"state": "queued", "minutes": 3, "requested": overview._now()})
    marker = tmp_path / "ran"
    overview.work(store, requests, command=_maker(tmp_path, f"open({str(marker)!r}, 'w')\n" + GOOD))
    assert not marker.exists()
    assert requests.get(doc)["overview"] == made
    assert sum(overview.TAG in m.get("tags", []) for m in store.list()) == 1


def test_the_daily_limit_stops_the_spending(store, requests, tmp_path):
    docs = [store.publish(text=f"# D{i}\n\nText.", title=f"D{i}")["id"] for i in range(3)]
    for d in docs:
        overview.request(store, requests, d, minutes=3)
    results = overview.work(store, requests, command=_maker(tmp_path, GOOD), daily_limit=2)
    assert [r["state"] for r in results] == ["done", "done", "failed"]
    assert "limit" in results[2]["error"]


def test_a_request_made_during_a_run_is_picked_up(store, doc, requests, tmp_path):
    other = store.publish(text="# Other\n\nMore.", title="Other")["id"]
    overview.request(store, requests, doc, minutes=3)
    body = (
        "import json, os\n"
        f"p = {str(requests.folder / other)!r} + '.json'\n"
        "if not os.path.exists(p):\n"
        f"    json.dump({{'state': 'queued', 'minutes': 3, 'requested': {overview._now()!r}}}, open(p, 'w'))\n"
        + GOOD
    )
    results = overview.work(store, requests, command=_maker(tmp_path, body))
    assert {r["doc"] for r in results} == {doc, other}


def test_a_request_nobody_fulfilled_expires_and_can_be_retried(client, store, doc, requests, tmp_path):
    old = "2020-01-01T00:00:00+00:00"
    requests.put(doc, {"state": "queued", "minutes": 3, "requested": old})
    seen = client.get(f"/docs/{doc}/overview").json()
    assert seen["state"] == "failed" and "no worker" in seen["error"]
    marker = tmp_path / "ran"
    overview.work(store, requests, command=_maker(tmp_path, f"open({str(marker)!r}, 'w')\n" + GOOD))
    assert not marker.exists(), "an expired request must not spend money when a worker wakes"
    assert client.post(f"/docs/{doc}/overview", json={"minutes": 3}).json()["state"] == "queued"


def test_a_dead_workers_request_can_be_retried_without_a_worker(client, doc, requests):
    requests.put(doc, {"state": "running", "minutes": 3, "started": "2020-01-01T00:00:00+00:00"})
    assert client.get(f"/docs/{doc}/overview").json()["state"] == "failed"
    assert client.post(f"/docs/{doc}/overview", json={"minutes": 3}).json()["state"] == "queued"


@pytest.mark.parametrize("junk", ["[1]", "7", '"x"', '{"state": "done"}', '{"state": "done", "overview": 3}'])
def test_a_damaged_record_breaks_nothing(client, store, doc, requests, tmp_path, junk):
    other = store.publish(text="# Other\n\nMore.", title="Other")["id"]
    requests.folder.mkdir(parents=True, exist_ok=True)
    (requests.folder / f"{doc}.json").write_text(junk)
    assert client.get(f"/docs/{doc}").status_code == 200
    assert client.get(f"/docs/{doc}/overview").json()["state"] == "none"
    assert client.post(f"/docs/{doc}/overview", json={"minutes": 3}).status_code == 200
    overview.request(store, requests, other, minutes=3)
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    assert requests.get(other)["state"] == "done"


def test_the_version_recorded_is_the_one_spoken(client, store, doc, requests, tmp_path):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    store.publish(text="# Hello\n\nChanged first.", title="Hello", replace=doc)
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    state = client.get(f"/docs/{doc}/overview").json()
    assert state["state"] == "done" and not state["stale"]
    assert "Changed first." in store.read_text(state["overview"])


@pytest.mark.parametrize("bad", [["x", "{{source}}", "{{out}}"], ["x", "{source}", "{out}", "{nope}"], ["x", "{source}", '{"a":1}', "{out}"]])
def test_a_bad_command_fails_before_any_money_is_spent(store, requests, bad):
    with pytest.raises(ValueError):
        overview.work(store, requests, command=bad)


def test_a_timeout_stops_the_children_too(store, doc, requests, tmp_path):
    marker = tmp_path / "grandchild-ran"
    child = tmp_path / "child.py"
    child.write_text(f"import time\ntime.sleep(2)\nopen({str(marker)!r}, 'w')\n")
    body = f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, {str(child)!r}])\ntime.sleep(30)\n"
    overview.request(store, requests, doc, minutes=3)
    overview.work(store, requests, command=_maker(tmp_path, body), timeout=0.5)
    assert "gave up" in requests.get(doc)["error"]
    time.sleep(2.5)
    assert not marker.exists()


def test_a_daemon_holding_the_output_does_not_lose_a_paid_result(store, doc, requests, tmp_path):
    body = "import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n" + GOOD
    overview.request(store, requests, doc, minutes=3)
    began = time.monotonic()
    overview.work(store, requests, command=_maker(tmp_path, body), timeout=15)
    assert requests.get(doc)["state"] == "done" and time.monotonic() - began < 10


def test_a_page_whose_head_never_closes_still_has_text():
    assert overview.html_to_text("<html><head><title>T</title><body><p>Body") == "Body"


def test_the_command_is_told_the_source_documents_page(store, doc, requests, tmp_path):
    overview.request(store, requests, doc, minutes=3)
    script = tmp_path / "maker.py"
    script.write_text(
        "import sys\nopen(sys.argv[1], 'w').write('page')\n"
        f"open({str(tmp_path / 'url')!r}, 'w').write(sys.argv[2])\n"
    )
    overview.work(
        store, requests,
        command=[sys.executable, str(script), "{out}", "{url}", "{source}"],
        doc_url=lambda i: f"https://x.test/d/{i}",
    )  # fmt: skip
    assert (tmp_path / "url").read_text() == f"https://x.test/d/{doc}"
    assert store.meta(requests.get(doc)["overview"])["source"]["of"] == doc
