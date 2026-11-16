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


def test_force_makes_a_new_one_rather_than_reusing_the_last(client, store, doc, requests, tmp_path):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    first = requests.get(doc)["overview"]
    client.post(f"/docs/{doc}/overview", json={"minutes": 3, "force": True})
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    assert requests.get(doc)["overview"] != first


# -- one review of several documents: the page's Listen on a selection -----------------


@pytest.fixture
def trio(store):
    ids = [
        store.publish(text=f"# {t}\n\nAbout {t.lower()}.", title=t)["id"]
        for t in ("Bees", "Tides", "Bridges")
    ]
    return store.make_group("Nature", ids), ids


def test_a_group_tells_the_page_each_review_and_the_cost(client, trio):
    group, ids = trio
    g = client.get(f"/groups/{group['id']}").json()
    assert {"minutes": 5, "characters": 4500} in g["listen"]["choices"]
    assert all(m["listen"]["state"] == "none" for m in g["items"])
    assert all(m["has_markdown"] for m in g["items"])


def test_a_group_says_nothing_of_reviews_when_they_are_off(store, trio):
    group, _ = trio
    off = TestClient(_app(store, overviews=False))
    g = off.get(f"/groups/{group['id']}").json()
    assert "listen" not in g and all("listen" not in m for m in g["items"])
    assert off.post("/overviews", json={"docs": ["x"]}).status_code == 404


def test_one_review_of_several_combines_them_into_one_document(client, store, trio, requests, tmp_path):
    group, ids = trio
    r = client.post("/overviews", json={"docs": ids[:2], "group": group["id"], "minutes": 3})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["listen"]["state"] == "queued" and out["listen"]["minutes"] == 3
    # asking publishes nothing: the worker makes the combined document when it starts
    assert out["doc"] is None and not _combined(store)
    assert store.group(group["id"])["docs"] == ids
    _work(store, requests, tmp_path)
    (combined,) = _combined(store)
    out = {"doc": combined["id"]}
    assert overview.COMBINED_TAG in combined["tags"]
    assert combined["source"]["combines"] == ids[:2]
    text = store.read_text(out["doc"])
    assert "About bees." in text and "About tides." in text and "bridges" not in text
    # it joins the group, so it is found where it was asked for
    assert out["doc"] in store.group(group["id"])["docs"]
    # asking again for the same documents reuses it: one document, one request
    again = client.post("/overviews", json={"docs": ids[1::-1], "group": group["id"], "minutes": 3}).json()
    assert again["doc"] == out["doc"] and again["listen"]["state"] == "done"
    assert len(_combined(store)) == 1


def _combined(store):
    return [m for m in store.list() if overview.COMBINED_TAG in (m.get("tags") or [])]


def _work(store, requests, tmp_path):
    return overview.work(store, requests, command=_maker(tmp_path, GOOD))


def test_no_worker_means_no_combined_document(client, store, trio, requests):
    group, ids = trio
    out = client.post("/overviews", json={"docs": ids, "group": group["id"]}).json()
    assert out["doc"] is None and out["listen"]["state"] == "queued"
    assert not _combined(store) and store.group(group["id"])["docs"] == ids
    # the request is the same one when asked again, and expires without leaving a document
    again = client.post("/overviews", json={"docs": ids, "group": group["id"]}).json()
    assert again["listen"]["state"] == "queued" and len(requests.ids()) == 1
    (rid,) = requests.ids()
    record = requests.get(rid)
    requests.put(rid, {**record, "requested": "2000-01-01T00:00:00Z"})
    state = client.post("/overviews", json={"docs": ids, "group": group["id"]}).json()["listen"]
    assert state["state"] == "queued"  # asked again: a fresh request, still no document
    assert not _combined(store)


def test_a_changed_document_makes_a_new_combination(client, store, trio, requests, tmp_path):
    group, ids = trio
    body = {"docs": ids[:2], "group": group["id"]}
    client.post("/overviews", json=body)
    _work(store, requests, tmp_path)
    (first,) = _combined(store)
    store.publish(text="# Bees\n\nNow about wasps too.", replace=ids[0])
    out = client.post("/overviews", json=body).json()
    assert out["doc"] is None  # not the old one: the documents changed
    _work(store, requests, tmp_path)
    assert len(_combined(store)) == 2 and first["id"] in [m["id"] for m in _combined(store)]


def test_a_selection_must_belong_to_the_group(client, store, trio):
    group, _ = trio
    other = store.publish(text="# Else", title="Else")["id"]
    for docs in ([other], [], "x", [""]):
        r = client.post("/overviews", json={"docs": docs, "group": group["id"]})
        assert r.status_code == 422, docs


def test_another_site_cannot_spend_on_a_group(client, trio, store):
    group, ids = trio
    r = client.post("/overviews", json={"docs": ids, "group": group["id"]}, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    assert not any(overview.COMBINED_TAG in (m.get("tags") or []) for m in store.list())


def test_a_combined_document_counts_as_what_it_combines(client, store, trio, requests, tmp_path):
    group, ids = trio
    client.post("/overviews", json={"docs": ids, "group": group["id"]})
    _work(store, requests, tmp_path)
    (first,) = [m["id"] for m in _combined(store)]
    # the group's "all" now includes the combined document: still the same three, reused
    everything = store.group(group["id"])["docs"]
    assert first in everything
    again = client.post("/overviews", json={"docs": everything, "group": group["id"]}).json()
    assert again["doc"] == first
    assert store.read_text(first).count("About bees.") == 1


def test_documents_from_anywhere_can_be_reviewed_together(client, store, trio, requests, tmp_path):
    _, ids = trio
    out = client.post("/overviews", json={"docs": [ids[0], ids[2]]}).json()
    assert out["listen"]["state"] == "queued"
    _work(store, requests, tmp_path)
    (combined,) = _combined(store)
    assert not any(combined["id"] in g["docs"] for g in store.list_groups())


def test_presses_at_once_make_one_combined_document(client, store, trio, requests, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    group, ids = trio
    body = {"docs": ids, "group": group["id"]}
    with ThreadPoolExecutor(6) as pool:
        outs = list(pool.map(lambda _: client.post("/overviews", json=body), range(6)))
    assert {r.status_code for r in outs} == {200}
    assert len(requests.ids()) == 1 and not _combined(store)
    _work(store, requests, tmp_path)
    again = client.post("/overviews", json=body).json()
    combined = _combined(store)
    assert len(combined) == 1 and again["doc"] == combined[0]["id"]
    assert store.group(group["id"])["docs"].count(combined[0]["id"]) == 1


def test_too_much_text_is_refused_before_anything_is_made(store, trio):
    group, ids = trio
    with pytest.raises(ValueError, match="bytes of text"):
        overview.combined_document(store, [store.meta(i) for i in ids], title="T", max_bytes=10)
    assert not any(overview.COMBINED_TAG in (m.get("tags") or []) for m in store.list())


def test_any_pick_of_documents_as_one_markdown_file(client, trio):
    _, ids = trio
    text = client.get("/aggregate", params={"doc": [ids[0], ids[2]]}).text
    assert "About bees." in text and "About bridges." in text and "tides" not in text


# -- the maker is down: say why, wait, and make what waited once it works ---------------
LOGIN = "import sys\nsys.exit('Failed to authenticate: this login reached its time limit')"


@pytest.fixture
def pair(store):
    return [store.publish(text=f"# D{i}\n\nText.", title=f"D{i}")["id"] for i in range(2)]


def test_the_same_fast_failure_twice_marks_the_maker_down(client, store, pair, requests, tmp_path):
    for d in pair:
        overview.request(store, requests, d, minutes=3)
    results = overview.work(store, requests, command=_maker(tmp_path, LOGIN))
    assert [r["state"] for r in results] == ["failed", "waiting"]
    audio = client.get("/audio").json()
    assert "time limit" in audio["down"]["reason"] and audio["down"]["link"] is None
    # the first failure was the same one, so it waits too: nothing offers a Try again
    assert {u["state"] for u in audio["unmade"]} == {"waiting"}
    assert client.get(f"/docs/{pair[0]}/overview").json()["down"] == audio["down"]


def test_one_document_failing_twice_is_that_document(store, doc, requests, tmp_path):
    for _ in range(2):
        overview.request(store, requests, doc, minutes=3, force=True)
        overview.work(store, requests, command=_maker(tmp_path, LOGIN))
    assert overview.maker_down(requests) is None and requests.get(doc)["state"] == "failed"


def _probe_due_now(requests):
    requests.put_mark({**requests.mark(), "tried": "2020-01-01T00:00:00+00:00"})


def test_different_failures_are_the_documents_not_the_maker(store, pair, requests, tmp_path):
    for d in pair:
        overview.request(store, requests, d, minutes=3)
    bad = "import sys\nsys.exit('too short' if 'D0' in open(source).read() else 'not english')"
    overview.work(store, requests, command=_maker(tmp_path, bad))
    assert overview.maker_down(requests) is None
    assert {requests.get(d)["state"] for d in pair} == {"failed"}


def test_while_down_a_request_waits_and_nothing_is_spent(client, store, doc, requests, tmp_path):
    overview.mark_down(requests, "the login expired")  # whoever marks it just saw it fail
    assert client.post(f"/docs/{doc}/overview", json={"minutes": 3}).json()["state"] == "waiting"
    marker = tmp_path / "ran"
    overview.work(store, requests, command=_maker(tmp_path, f"open({str(marker)!r}, 'w')\n" + GOOD))
    assert not marker.exists() and requests.started_today() == 0
    seen = client.get(f"/docs/{doc}/overview").json()
    assert seen["state"] == "waiting" and seen["error"] == "the login expired"


def test_a_probe_that_works_clears_the_mark_and_makes_what_waited(client, store, pair, requests, tmp_path):
    overview.mark_down(requests, "the login expired")
    _probe_due_now(requests)
    for d in pair:
        overview.request(store, requests, d, minutes=3)
    results = overview.work(store, requests, command=_maker(tmp_path, GOOD))
    assert [r["state"] for r in results] == ["done", "done"]
    assert client.get("/audio").json()["down"] is None


def test_a_probe_that_fails_again_keeps_the_rest_waiting(store, pair, requests, tmp_path):
    overview.mark_down(requests, "the login expired")
    _probe_due_now(requests)
    for d in pair:
        overview.request(store, requests, d, minutes=3)
    overview.work(store, requests, command=_maker(tmp_path, LOGIN))
    assert {requests.get(d)["state"] for d in pair} == {"waiting"}
    assert requests.started_today() == 1  # one probe, not one per request
    assert overview.maker_down(requests)["reason"] == "the login expired"  # the agent's words stay


def test_an_agent_links_the_fix_and_clears_it_by_hand(client, store, pair, requests, tmp_path):
    from annals import tools

    for d in pair:
        overview.request(store, requests, d, minutes=3)
    overview.work(store, requests, command=_maker(tmp_path, LOGIN))
    issue = "https://github.com/someone/platform/issues/563"
    here = {"target": str(store.target.root)}
    out = tools.listen_down("the server's login expired", link=issue, **here)
    assert out["down"]["reason"] == "the server's login expired" and out["down"]["link"] == issue
    assert client.get("/audio").json()["down"]["link"] == issue
    assert tools.listen_down(**here)["down"]["link"] == issue  # nothing given: just shows it
    with pytest.raises(ValueError, match="web address"):
        tools.listen_down(link="javascript:alert(1)", **here)
    assert sorted(tools.listen_down(clear=True, **here)["queued"]) == sorted(pair)
    assert overview.maker_down(requests) is None
    assert {requests.get(d)["state"] for d in pair} == {"queued"}
    with pytest.raises(ValueError, match="not marked down"):
        tools.listen_down(link=issue, **here)  # a link alone never takes a working maker down


@pytest.mark.parametrize("probe", ["import time\ntime.sleep(0.2)\nraise SystemExit('slow')", "pass"])
def test_a_probe_that_fails_otherwise_keeps_its_place(store, doc, requests, tmp_path, monkeypatch, probe):
    monkeypatch.setattr(overview, "FAST_FAILURE_S", 0.1)  # so the slow one counts as slow
    overview.mark_down(requests, "the login expired")
    _probe_due_now(requests)
    overview.request(store, requests, doc, minutes=3)
    overview.work(store, requests, command=_maker(tmp_path, probe))
    assert requests.get(doc)["state"] == "waiting" and overview.maker_down(requests)


def test_the_daily_limit_never_drops_what_waited(store, doc, requests, tmp_path):
    overview.mark_down(requests, "the login expired")
    _probe_due_now(requests)
    overview.request(store, requests, doc, minutes=3)
    overview.work(store, requests, command=_maker(tmp_path, GOOD), daily_limit=0)
    assert requests.get(doc)["state"] == "waiting"
    assert overview._probe_due(requests), "a probe that did not run does not use up its slot"
    overview.mark_up(requests)  # back, but the day's limit is spent: it still waits
    overview.work(store, requests, command=_maker(tmp_path, GOOD), daily_limit=0)
    assert requests.get(doc)["state"] == "waiting"
    overview.work(store, requests, command=_maker(tmp_path, GOOD))
    assert requests.get(doc)["state"] == "done"


@pytest.mark.parametrize("junk", [{"docs": "ab", "reason": 3}, {"docs": None}, []])
def test_a_damaged_mark_breaks_no_page(client, doc, requests, junk):
    import json

    requests.folder.mkdir(parents=True, exist_ok=True)
    (requests.folder / overview.DOWN_FILE).write_text(json.dumps(junk))
    assert client.get(f"/docs/{doc}").status_code == 200
    assert client.get("/audio").json()["down"] is None


def test_request_files_are_readable_by_another_user(store, doc, requests):
    """A root worker and a sandboxed server read each other's request files (seen on a server:
    the page polled a request the worker had rewritten 0600, and got a 500)."""
    overview.request(store, requests, doc, minutes=3)
    requests.put_mark({"reason": "x"})
    for path in requests.folder.iterdir():
        if path.suffix == ".json" or path.name == overview.DOWN_FILE:
            assert stat.S_IMODE(path.stat().st_mode) & 0o044 == 0o044, path.name


# -- a combination is made by the worker: what can go wrong between asking and working ------


def test_too_much_text_is_refused_through_the_api_before_a_request_is_queued(
    client, store, trio, requests, monkeypatch
):
    group, ids = trio
    # each document alone fits: only the total is over the limit
    monkeypatch.setattr("annals.api.MAX_AGGREGATE_BYTES", 60)
    r = client.post("/overviews", json={"docs": ids, "group": group["id"]})
    assert r.status_code == 400 and "bytes of text" in r.text
    assert requests.ids() == [] and not _combined(store)


def test_a_crash_after_the_document_is_made_costs_one_review(client, store, trio, requests, tmp_path):
    group, ids = trio
    body = {"docs": ids, "group": group["id"]}
    client.post("/overviews", json=body)
    (rid,) = requests.ids()
    overview._make_combined(store, requests.get(rid))  # the worker died right after this
    out = client.post("/overviews", json=body).json()
    assert out["doc"] and out["listen"]["state"] == "queued"
    assert requests.ids() == [out["doc"]]  # the combination's own request is gone
    _work(store, requests, tmp_path)
    assert len(_combined(store)) == 1
    assert len([m for m in store.list() if overview.TAG in (m.get("tags") or [])]) == 1


def test_members_trashed_before_the_worker_runs_are_left_out(client, store, trio, requests, tmp_path):
    group, ids = trio
    client.post("/overviews", json={"docs": ids, "group": group["id"]})
    store.trash(ids[2])
    results = _work(store, requests, tmp_path)
    (combined,) = _combined(store)
    assert results[0]["doc"] == combined["id"] and results[0]["state"] == "done"
    assert "bridges" not in store.read_text(combined["id"])


def test_a_selection_trashed_entirely_fails_free(client, store, trio, requests, tmp_path):
    group, ids = trio
    client.post("/overviews", json={"docs": ids, "group": group["id"]})
    for i in ids:
        store.trash(i)
    (result,) = _work(store, requests, tmp_path)
    assert result["state"] == "failed"
    assert not _combined(store) and requests.started_today() == 0


def test_a_combination_waits_while_the_maker_is_down(client, store, trio, requests, tmp_path):
    group, ids = trio
    overview.mark_down(requests, "login expired")
    out = client.post("/overviews", json={"docs": ids, "group": group["id"]}).json()
    assert out["doc"] is None and out["listen"]["state"] == "waiting"
    _work(store, requests, tmp_path)
    assert not _combined(store)  # waiting is not working: still nothing published
    (row,) = client.get("/audio").json()["unmade"]
    assert row["state"] == "waiting" and row["doc"] is None


def test_unmade_lists_a_combination_with_what_to_ask_again_with(client, store, trio, requests, tmp_path):
    group, ids = trio
    client.post("/overviews", json={"docs": ids[:2], "group": group["id"], "minutes": 3})
    (row,) = client.get("/audio").json()["unmade"]
    assert row["doc"] is None and row["state"] == "queued" and row["minutes"] == 3
    assert "2 documents together" in row["title"]
    assert row["combine"] == {"docs": ids[:2], "group": group["id"]}
    # asking again with exactly that is the retry: the same request, no second one
    again = client.post("/overviews", json={**row["combine"], "minutes": row["minutes"]}).json()
    assert again["doc"] is None and len(requests.ids()) == 1
    _work(store, requests, tmp_path)
    assert client.get("/audio").json()["unmade"] == []


def test_ids_tolerates_a_request_deleted_while_it_lists(requests, monkeypatch):
    from pathlib import Path

    requests.put("a", {"state": "queued"})
    requests.put("b", {"state": "queued"})
    real = Path.stat

    def stat(self, *args, **kwargs):
        if self.name == "a.json":
            raise FileNotFoundError(self.name)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    assert requests.ids() == ["b"]


def test_a_second_press_while_the_worker_runs_it_leaves_one_request(client, store, trio, requests, tmp_path):
    group, ids = trio
    body = {"docs": ids, "group": group["id"]}
    client.post("/overviews", json=body)
    (rid,) = requests.ids()
    record = requests.get(rid)
    doc = overview._make_combined(store, record)
    requests.put(rid, {**record, "state": "running", "started": overview._now()})  # the worker is on it
    out = client.post("/overviews", json=body).json()
    assert out["doc"] == doc and out["listen"]["state"] == "running"
    assert requests.ids() == [rid]  # nothing queued on the document, the running one not deleted
    assert requests.get(rid)["state"] == "running"


def test_a_failed_combination_is_dropped_when_its_retry_succeeds_in_being_asked(client, store, trio, requests):
    group, ids = trio
    body = {"docs": ids, "group": group["id"]}
    client.post("/overviews", json=body)
    (rid,) = requests.ids()
    requests.put(rid, {**requests.get(rid), "state": "failed", "error": "x"})
    store.publish(text="# Bees\n\nChanged.", replace=ids[0])  # the retry is a new key
    client.post("/overviews", json=body)
    assert len(requests.ids()) == 1 and requests.ids() != [rid]


def _maker_with_url(tmp_path, body):
    script = tmp_path / "maker_url.py"
    script.write_text(f"import sys, os\nsource, minutes, out, url = sys.argv[1:5]\n{body}\n")
    return [sys.executable, str(script), "{source}", "{minutes}", "{out}", "{url}"]


def test_the_engine_contract(client, store, requests, tmp_path):
    """misc/docs/design.md "The overview engine contract": what an engine may rely on and owes."""
    plain = store.publish(text="First line.\n\nSecond.", title="Plain title")["id"]
    page = store.publish(
        text="<html><head><title>x</title><script>no()</script></head><body><p>Spoken &amp; read.</p></body></html>",
        title="A page", filename="p.html",
    )["id"]
    for d in (plain, page):
        client.post(f"/docs/{d}/overview", json={"minutes": 3})
    seen = tmp_path / "seen.json"
    probe = (
        "import json, sys\n"
        f"seen = {str(seen)!r}\n"
        "rows = json.load(open(seen)) if os.path.exists(seen) else []\n"
        "rows.append(dict(source_text=open(source).read(), minutes=minutes, url=url,\n"
        "    cwd_files=sorted(os.listdir('.')), stdin=sys.stdin.read(), out_name=os.path.basename(out)))\n"
        "json.dump(rows, open(seen, 'w'))\n"
        "open(out, 'w').write('<!doctype html><title>P</title>')\n"
    )
    overview.work(store, requests, command=_maker_with_url(tmp_path, probe), doc_url=lambda i: f"https://h/annals/d/{i}")
    import json

    rows = {r["url"]: r for r in json.loads(seen.read_text())}
    p, h = rows[f"https://h/annals/d/{plain}"], rows[f"https://h/annals/d/{page}"]
    assert p["source_text"] == "# Plain title\n\nFirst line.\n\nSecond.\n"  # the title, a blank line, the text
    assert "# A page" in h["source_text"] and "Spoken & read." in h["source_text"] and "no()" not in h["source_text"]
    assert p["minutes"] == "3" and p["stdin"] == "" and p["cwd_files"] == ["source.md"]
    assert client.get(f"/docs/{plain}/overview").json()["state"] == "done"


def test_the_engine_failure_contract(client, store, doc, requests, tmp_path):
    """Exit 0 without a page, a non-zero exit with the last line as the reason, no output at all."""
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    overview.work(store, requests, command=_maker(tmp_path, "import sys\nprint('the voice said so')"))
    assert client.get(f"/docs/{doc}/overview").json()["error"] == "the overview command wrote no page"
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    noisy = "import sys\nprint('progress 10%'); print('still working', file=sys.stderr); print('the voice ran out'); print('')\nsys.exit(3)"
    overview.work(store, requests, command=_maker(tmp_path, noisy))
    assert client.get(f"/docs/{doc}/overview").json()["error"] == "the voice ran out"
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    overview.work(store, requests, command=_maker(tmp_path, "import sys\nsys.exit(4)"))
    assert client.get(f"/docs/{doc}/overview").json()["error"] == "the overview command exited 4"


def test_the_same_failure_from_two_documents_marks_the_maker_down(client, store, requests, tmp_path):
    ids = [store.publish(text=f"# D{i}\n\ntext {i}", title=f"D{i}")["id"] for i in range(3)]
    for d in ids:
        client.post(f"/docs/{d}/overview", json={"minutes": 3})
    overview.work(store, requests, command=_maker(tmp_path, "import sys\nsys.exit('the account is out of credit (code 4%d)' % len(source))"))
    assert overview.maker_down(requests)
    states = {client.get(f"/docs/{d}/overview").json()["state"] for d in ids}
    assert "waiting" in states  # the rest wait for the fix instead of failing


def test_a_long_failure_reason_is_cut(client, store, doc, requests, tmp_path):
    client.post(f"/docs/{doc}/overview", json={"minutes": 3})
    long_reason = "x" * (overview.MAX_ERROR_CHARS + 100)
    overview.work(store, requests, command=_maker(tmp_path, f"import sys\nsys.exit({long_reason!r})"))
    assert client.get(f"/docs/{doc}/overview").json()["error"] == "x" * overview.MAX_ERROR_CHARS


def test_a_command_must_name_source_and_out():
    with pytest.raises(ValueError, match="source"):
        overview.work(None, None, command=["maker", "{minutes}"])
