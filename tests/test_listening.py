"""Listening progress: what each reader heard of each audio overview, kept on the server.

The owner asked for a place to find the audio overviews and to see what they still have to
listen to (2026-11-09), on a phone, across devices. These pin the model (spans merged so a
replay counts once, one listen per play that reaches the end), the API (per reader, refuses
bad reports and cross-site writes) and the relay injected into html pages.
"""

import pytest
from fastapi.testclient import TestClient

from annals import listening as L
from annals.api import mk_api, mk_app, serve_html
from annals.auth import no_auth
from annals.overview import TAG
from annals.store import DocStore


# -- the model ---------------------------------------------------------------------
def test_spans_merge_so_a_replayed_minute_counts_once():
    rec = L.apply_report(None, {"spans": [[0, 60]], "duration": 300, "position": 60})
    rec = L.apply_report(rec, {"spans": [[0, 60], [30, 90]], "position": 90})
    assert rec["heard"] == [[0.0, 90.0]]
    assert L.percent(rec) == 30 and L.status(rec) == L.STARTED


def test_a_listen_counts_once_per_play_however_often_it_is_reported():
    rec = None
    for play in ("a", "a", "b"):
        rec = L.apply_report(rec, {"spans": [[0, 10]], "duration": 10, "position": 10, "ended": play})
    assert rec["listens"] == 2 and L.status(rec) == L.DONE


def test_status_reads_heard_share_and_the_readers_own_mark():
    assert L.status(None) == L.NOT_STARTED
    stray = L.apply_report(None, {"spans": [[0, 1]], "duration": 100})
    assert L.status(stray) == L.NOT_STARTED  # a stray tap on play is not "in progress"
    nearly = L.apply_report(None, {"spans": [[0, 96]], "duration": 100})
    assert L.status(nearly) == L.DONE  # skipping the outro still counts as heard
    assert L.status(L.apply_mark(None, True)) == L.DONE
    assert L.status(L.apply_mark(nearly, False)) == L.STARTED
    assert L.status(L.apply_mark(L.apply_mark(nearly, False), None)) == L.DONE


def test_spans_beyond_the_duration_are_cut_and_a_record_stays_small():
    rec = L.apply_report(None, {"spans": [[90, 500]], "duration": 100})
    assert rec["heard"] == [[90.0, 100.0]]
    many = [[i * 2, i * 2 + 1] for i in range(L.MAX_SPANS + 50)]
    assert len(L.merge_spans(many)) == L.MAX_SPANS


@pytest.mark.parametrize(
    "report",
    [
        {"spans": [[0, "x"]]},
        {"spans": [[0]]},
        {"spans": [[-1, 2]]},
        {"spans": [[0, float("nan")]]},
        {"spans": [[0, 1]], "duration": True},
        {"spans": [], "ended": ""},
        {"spans": [], "ended": "x" * 100},
        {"spans": [], "secret": 1},
        {"spans": [[0, 1]] * (L.MAX_REPORT_SPANS + 1)},
        [],
    ],
)
def test_a_bad_report_is_refused(report):
    with pytest.raises(ValueError):
        L.apply_report(None, report)


def test_reader_files_are_path_safe_and_never_shared():
    assert L.reader_file("Me@Example.com") == "me@example.com.json"
    assert "/" not in L.reader_file("../../etc/passwd") and not L.reader_file("..").startswith(".")
    names = ["a/b", "a_b", "a%2Fb", "..", "owner", ".owner"]
    assert len({L.reader_file(n) for n in names}) == len(names)
    with pytest.raises(ValueError):
        L.reader_file("")


def test_a_listen_needs_the_audio_heard_almost_whole():
    dragged = L.apply_report(None, {"spans": [[0, 2], [97, 100]], "duration": 100, "ended": "p"})
    assert dragged["listens"] == 0 and L.status(dragged) == L.STARTED
    heard = L.apply_report(None, {"spans": [[0, 100]], "duration": 100, "ended": "p"})
    assert heard["listens"] == 1


def test_a_retried_end_never_counts_twice_even_after_another_device_ended():
    rec = None
    for play in ("phone", "tablet", "phone"):  # the phone's retry lands after the tablet's
        rec = L.apply_report(rec, {"spans": [[0, 10]], "duration": 10, "ended": play})
    assert rec["listens"] == 2


def test_the_tag_store_is_still_a_whole_mutable_mapping(tmp_path):
    from annals.tags import JsonTagStore

    tags = JsonTagStore(tmp_path / "tags.json")
    tags.update({"x:1": ["b", "a"]})  # MutableMapping.update, not the atomic modify
    assert tags["x:1"] == ["a", "b"]
    assert tags.modify("x:1", lambda v: v + ["c"]) == ["a", "b", "c"]


# -- the API ---------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


@pytest.fixture
def docs(store):
    over = store.publish(text="<p>hi</p><audio src=a.mp3></audio>", title="Listen: Bees", filename="o.html", tags=[TAG])
    plain = store.publish(text="# Bees", title="Bees", filename="bees.md")
    return {"over": over["id"], "plain": plain["id"]}


def _client(store, who="me@example.com", **kw):
    def as_reader(request):
        return who

    return TestClient(mk_api(store=store, reader=as_reader, **kw))


def test_the_audio_list_holds_the_overviews_with_each_readers_progress(store, docs):
    me, you = _client(store), _client(store, who="you@example.com")
    r = me.post(f"/listening/{docs['over']}", json={"spans": [[0, 30]], "duration": 60, "position": 30})
    assert r.status_code == 200 and r.json()["percent"] == 50
    rows = me.get("/audio").json()
    assert [d["id"] for d in rows["docs"]] == [docs["over"]]
    assert rows["docs"][0]["listening"]["status"] == L.STARTED
    assert rows["statuses"] == list(L.STATUSES) and rows["tracked"] is True
    assert you.get("/audio").json()["docs"][0]["listening"]["status"] == L.NOT_STARTED
    assert me.get("/audio", params={"q": "wasps"}).json()["docs"] == []


def test_progress_survives_a_new_server_like_another_device(store, docs):
    _client(store).post(f"/listening/{docs['over']}", json={"spans": [[0, 20]], "duration": 60, "position": 20})
    again = _client(DocStore(store.target.root))  # another process over the same data root
    got = again.get(f"/listening/{docs['over']}").json()
    assert got["heard"] == [[0.0, 20.0]] and got["position"] == 20


def test_mark_and_forget(store, docs):
    c = _client(store)
    assert c.patch(f"/listening/{docs['over']}", json={"done": True}).json()["status"] == L.DONE
    assert c.patch(f"/listening/{docs['over']}", json={"done": "yes"}).status_code == 422
    assert c.patch(f"/listening/{docs['over']}", json={"other": 1}).status_code == 422
    assert c.delete(f"/listening/{docs['over']}").json()["status"] == L.NOT_STARTED
    assert c.get(f"/listening/{docs['over']}").json()["status"] == L.NOT_STARTED


def test_bad_reports_unknown_docs_and_cross_site_writes_are_refused(store, docs):
    c = _client(store)
    assert c.post(f"/listening/{docs['over']}", json={"spans": "x"}).status_code == 422
    assert c.post("/listening/nope", json={"spans": []}).status_code == 404
    r = c.post(f"/listening/{docs['over']}", json={"spans": []}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


@pytest.mark.parametrize("off", [None, False])
def test_no_listening_store_means_no_progress_but_the_list_still_works(store, docs, off):
    c = _client(store, listening=off)
    assert c.get(f"/listening/{docs['over']}").status_code == 404
    rows = c.get("/audio").json()
    assert rows["tracked"] is False and rows["docs"][0]["listening"]["status"] == L.NOT_STARTED


def test_the_standalone_reader_is_the_gates_user(store, docs):
    c = TestClient(mk_app(store=store, authorizer=no_auth))
    c.post(f"/annals/api/listening/{docs['over']}", json={"spans": [[0, 5]], "duration": 10})
    assert (store.target.root / L.FOLDER / "owner.json").exists()
    assert c.get("/annals/audio").status_code == 200  # the page shell, routed by the browser


def test_a_document_says_whether_its_listening_is_recorded(store, docs):
    c = _client(store)
    assert c.get(f"/docs/{docs['over']}").json()["listenable"] is True
    assert c.get(f"/docs/{docs['plain']}").json()["listenable"] is False
    assert _client(store, listening=None).get(f"/docs/{docs['over']}").json()["listenable"] is False


# -- the relay ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "page",
    [
        b"<html><body><audio src=a.mp3></audio></body></html>",
        b'<body><script>var a = d("audio", {preload: "auto"});</script></body>',  # @zodal/speech
        b"<body><script>var a = new Audio(url);</script></body>",
    ],
)
def test_html_that_plays_media_gets_the_relay(page):
    assert b"annalsMedia" in serve_html(page)


@pytest.mark.parametrize(
    "page",
    [
        b"<html><body><p>An audio overview of the video.</p></body></html>",
        b'<html data-annals-media="off"><body><audio></audio></body></html>',
    ],
)
def test_html_that_plays_nothing_or_opts_out_does_not(page):
    assert b"annalsMedia" not in serve_html(page)


def test_a_shared_page_carries_no_relay():
    assert b"annalsMedia" not in serve_html(b"<body><audio></audio></body>", media_relay=False)
