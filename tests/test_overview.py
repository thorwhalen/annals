"""Spoken overviews: asking from the page, the worker, and what a reader sees of each state."""

import stat
import sys

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
    requests.put(doc, {"state": "running", "minutes": 3, "version": 1})
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

    class Remote:
        target = object()

    with pytest.raises(ValueError, match="on this machine"):
        mk_api(store=Remote(), overviews=True)
