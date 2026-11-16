"""Rooms: ``mk_api(room=True)`` serves documents to an outside audience, and a ``room``
target never receives provenance (``publish``/``copy --to <room>``)."""

import io
import json

import pytest
from fastapi.testclient import TestClient

from annals.__main__ import run
from annals.api import mk_api
from annals.config import load_settings
from annals.store import DocStore

SECRET = {"host": "the-mac", "cwd": "/Users/someone/proj", "session": "sess-x"}


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "room")


@pytest.fixture
def docs(store, tmp_path):
    page = tmp_path / "vision.html"
    page.write_text("<!doctype html><title>Vision</title><p>the plan</p>")
    a = store.publish(page, source={**SECRET, "corpus": "oinq"})
    b = store.publish(
        title="Notes",
        text="# Notes\n\nhello",
        source=SECRET,
        artifact="https://claude.ai/artifact/abc",
    )
    gone = store.publish(title="Withdrawn", text="# Withdrawn", source=SECRET)
    store.trash(gone["id"])
    g = store.make_group("Pack", [a["id"], b["id"]])
    return {"a": a["id"], "b": b["id"], "gone": gone["id"], "group": g["id"]}


@pytest.fixture
def client(store):
    return TestClient(mk_api(store=store, room=True))


def _no_provenance(payload):
    text = json.dumps(payload)
    for word in ("the-mac", "/Users/someone", "sess-x", "oinq", "claude.ai"):
        assert word not in text, word


def test_a_reader_reads_documents_groups_and_files(client, docs):
    listed = client.get("/docs").json()["docs"]
    assert {d["id"] for d in listed} == {docs["a"], docs["b"]}
    assert client.get(f"/docs/{docs['a']}").status_code == 200
    assert client.get(f"/groups/{docs['group']}").status_code == 200
    raw = client.get(f"/raw/{docs['a']}/vision.html")
    assert raw.status_code == 200 and "the plan" in raw.text
    assert client.get("/sources").json()["room"] is True


def test_no_provenance_anywhere(client, docs):
    for path in (
        "/docs",
        f"/docs/{docs['a']}",
        f"/docs/{docs['b']}",
        "/groups",
        f"/groups/{docs['group']}",
        "/items",
        "/health",
        "/docs?q=pack",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        _no_provenance(r.json())
    # nothing found by searching for what was redacted
    assert client.get("/docs", params={"q": "the-mac"}).json()["docs"] == []
    assert client.get("/docs", params={"session": "sess-x"}).json()["docs"] == []


def test_the_bin_is_not_in_the_room(client, docs):
    assert client.get(f"/docs/{docs['gone']}").status_code == 404
    assert client.get("/docs", params={"trash": True}).json()["docs"] == []


@pytest.mark.parametrize(
    "path",
    ["/shares", "/audio", "/listening/x", "/docs/x/overview", "/docs/x/shareable"],
)
def test_owner_features_are_not_there(client, docs, path):
    assert client.get(path.replace("x", docs["a"])).status_code == 404


@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/docs/{a}/trash"),
        ("delete", "/docs/{a}"),
        ("post", "/groups"),
        ("post", "/shares"),
        ("patch", "/items/published:{a}"),
    ],
)
def test_a_room_is_read_only(client, docs, store, method, path):
    r = getattr(client, method)(path.format(a=docs["a"]))
    assert r.status_code == 405
    assert store.meta(docs["a"])["in_trash"] is False


def test_a_room_refuses_owner_features_up_front(store):
    for kw in (
        {"sources": {"ledgers": "/tmp"}},
        {"overviews": True},
        {"share_base_url": "https://x.test"},
    ):
        with pytest.raises(ValueError, match="a room"):
            mk_api(store=store, room=True, **kw)


def test_the_owner_api_is_unchanged(store, docs):
    owner = TestClient(mk_api(store=store, sources={}))
    assert owner.get(f"/docs/{docs['a']}").json()["source"]["host"] == "the-mac"
    assert owner.get("/sources").json()["room"] is False


# -- the publishing side ---------------------------------------------------------------


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ANNALS_TARGET", raising=False)
    monkeypatch.delenv("ANNALS_BASE_URL", raising=False)
    monkeypatch.setenv("ANNALS_CONFIG", str(tmp_path / "cfg" / "config.toml"))
    main, room = tmp_path / "main", tmp_path / "roomdir"
    _run(["configure", "--target", str(main), "--base-url", "https://a.test/annals"])
    _run(
        [
            "configure",
            "--to",
            "client",
            "--target",
            str(room),
            "--base-url",
            "https://a.test/client",
            "--room",
        ]
    )
    return main, room


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = run(argv, out=out, err=err)
    assert code == 0, err.getvalue()
    return out.getvalue().strip()


def _metas_on_disk(root):
    return [json.loads(p.read_text()) for p in root.rglob("meta.json")]


def test_configure_room_is_saved_and_kept(env):
    assert load_settings(to="client").room is True
    assert load_settings().room is False
    _run(["configure", "--to", "client", "--base-url", "https://a.test/client2"])
    assert load_settings(to="client").room is True


def test_publish_to_a_room_writes_no_provenance(env, tmp_path):
    _, room = env
    f = tmp_path / "r.md"
    f.write_text("# R\n\nbody")
    _run(["publish", str(f), "--to", "client", "--session", "sess-x"])
    (meta,) = _metas_on_disk(room)
    assert meta["source"] == {}


def test_copy_to_a_room_strips_every_meta(env, tmp_path):
    main, room = env
    f = tmp_path / "r.md"
    f.write_text("# R\n\nv1")
    link = _run(["publish", str(f), "--session", "sess-x"])
    f.write_text("# R\n\nv2")
    _run(["publish", str(f), "--replace", link, "--session", "sess-x"])
    assert any(m.get("source") for m in _metas_on_disk(main))
    _run(["copy", link, "--to", "client"])
    copied = _metas_on_disk(room)
    assert len(copied) >= 2  # the document and its earlier version
    assert all("source" not in m for m in copied)


def test_only_named_fields_reach_a_reader(store, client, docs):
    path = store.target.local_path(f"docs/{docs['a']}/meta.json")
    meta = json.loads(path.read_text())
    path.write_text(json.dumps({**meta, "publisher_box": "the-mac"}))
    _no_provenance(client.get(f"/docs/{docs['a']}").json())
    _no_provenance(client.get("/docs").json())


def test_a_group_with_nothing_to_show_is_absent(store, client, docs):
    doc = store.publish(title="Plan", text="# Plan", source=SECRET)
    hidden = store.make_group("Secret plans", [doc["id"]])
    store.trash(doc["id"])
    assert client.get(f"/groups/{hidden['id']}").status_code == 404
    assert "Secret plans" not in client.get("/groups").text


def test_a_room_takes_no_reader_of_its_own(store):
    with pytest.raises(ValueError, match="reader"):
        mk_api(store=store, room=True, reader=lambda request: "x")


def test_copying_a_group_to_a_room_leaves_the_bin_behind(env, tmp_path):
    main, room = env
    links = []
    for name in ("keep", "binned"):
        f = tmp_path / f"{name}.md"
        f.write_text(f"# {name}\n\nbody")
        links.append(_run(["publish", str(f)]))
    ids = [link.rsplit("/", 1)[1] for link in links]
    group_link = DocStore(main).make_group("Pack", ids)["id"]
    _run(["trash", links[1].rsplit("/", 1)[1]])
    _run(["copy", group_link, "--to", "client"])
    titles = {m["title"] for m in _metas_on_disk(room)}
    assert titles == {"keep"}
    with pytest.raises(AssertionError):  # a single binned document is refused
        _run(["copy", links[1], "--to", "client"])
