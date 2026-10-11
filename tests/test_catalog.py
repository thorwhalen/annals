"""Sources, the owner's tags, and the catalog over them, through the API and directly."""

import hashlib
import json
import os

import pytest
from fastapi.testclient import TestClient

from annals.api import mk_api, mk_app
from annals.auth import no_auth
from annals.catalog import Catalog
from annals.sources import FolderSource, PublishedSource, parse_sources_spec, split_key
from annals.store import DocStore
from annals.tags import JsonTagStore, normalize_tags


def _write(path, text, *, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


@pytest.fixture
def ledgers(tmp_path):
    root = tmp_path / "ledger"
    _write(root / "old.md", "# old ledger\n\nCorpus: the old one.", mtime=1_700_000_000)
    _write(
        root / "new.md",
        "# new ledger\n\nCorpus: fresh.\n\n"
        + "filler " * 60
        + "\n\nDeep in the text: zanzibar.",
        mtime=1_800_000_000,
    )
    _write(
        root / "team" / "plan.md", "# The plan\n\n![fig](fig.png)", mtime=1_750_000_000
    )
    _write(root / "team" / "notes.yaml", "a: 1\n", mtime=1_750_000_001)
    _write(root / ".hidden.md", "# secret", mtime=1_900_000_000)
    _write(root / "__pycache__" / "x.md", "# cache")
    (tmp_path / "outside.md").write_text("# outside")
    os.symlink(tmp_path / "outside.md", root / "escape.md")
    return root


def _digest(root):
    h = hashlib.sha1()
    for dirpath, _, files in sorted(os.walk(root)):
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            h.update(p.encode())
            if not os.path.islink(p):
                h.update(open(p, "rb").read())
                h.update(str(os.stat(p).st_mtime_ns).encode())
    return h.hexdigest()


@pytest.fixture
def store(tmp_path):
    s = DocStore(tmp_path / "data")
    s.publish(
        text="# Report\n\nquarterly numbers",
        title="Report",
        tags=["q3"],
        source={"session": "pub-agent"},
    )
    return s


@pytest.fixture
def client(store, ledgers):
    api = mk_api(store=store, sources={"ledgers": ledgers})
    return TestClient(api)


# -- FolderSource ------------------------------------------------------------------------


def test_folder_source_lists_newest_first_and_skips_hidden_and_escapes(ledgers):
    src = FolderSource(ledgers, name="ledgers")
    rows = src.rows()
    assert [r["id"] for r in rows] == [
        "new.md",
        "team/notes.yaml",
        "team/plan.md",
        "old.md",
    ]
    new = rows[0]
    assert (
        new["title"] == "new ledger" and new["session"] == "new" and new["kind"] == "md"
    )
    assert new["key"] == "ledgers:new.md" and new["excerpt"].startswith(
        "Corpus: fresh."
    )
    assert rows[1]["session"] == "team" and rows[1]["kind"] == "text"
    assert set(src) == {r["id"] for r in rows} and len(src) == 4
    for bad in [
        ".hidden.md",
        "escape.md",
        "__pycache__/x.md",
        "../outside.md",
        "/etc/passwd",
        "nope.md",
    ]:
        assert bad not in src
        with pytest.raises(KeyError):
            src.file_path(bad)
    assert src.rows(trash=True) == []


def test_folder_source_rereads_a_changed_file(ledgers):
    src = FolderSource(ledgers, name="ledgers")
    assert src["old.md"]["title"] == "old ledger"
    assert "zanzibar" in src.text("new.md")
    _write(ledgers / "old.md", "# old ledger, grown\n\nmore", mtime=1_850_000_000)
    assert src["old.md"]["title"] == "old ledger, grown"
    assert src.rows()[0]["id"] == "old.md"
    assert src.item("old.md")["text"].endswith("more")


def test_parse_sources_spec():
    assert parse_sources_spec("ledgers=~/a, notes=/b") == {
        "ledgers": "~/a",
        "notes": "/b",
    }
    assert parse_sources_spec("") == {}
    with pytest.raises(ValueError):
        parse_sources_spec("ledgers")


# -- tags --------------------------------------------------------------------------------


def test_normalize_tags():
    assert normalize_tags([" b ", "A", "a", "", "two  words"]) == [
        "A",
        "b",
        "two words",
    ]
    for bad in [["x" * 65], ["a\x07b"], [3], [str(i) for i in range(51)]]:
        with pytest.raises(ValueError):
            normalize_tags(bad)


def test_json_tag_store_persists_and_sees_other_writers(tmp_path):
    path = tmp_path / "tags" / "tags.json"
    a, b = JsonTagStore(path), JsonTagStore(path)
    a["x:1"] = ["red", "Red", "blue"]
    assert b["x:1"] == ["blue", "red"] and len(b) == 1 and list(b) == ["x:1"]
    b["x:2"] = ["green"]
    os.utime(path, ns=(1, 1))  # force a different stamp even within one mtime tick
    assert a.snapshot() == {"x:1": ["blue", "red"], "x:2": ["green"]}
    del a["x:1"]
    assert "x:1" not in JsonTagStore(path) and json.loads(path.read_text()) == {
        "x:2": ["green"]
    }


# -- the catalog -------------------------------------------------------------------------


def test_catalog_merges_sources_searches_full_text_and_overlays_tags(store, ledgers):
    cat = Catalog(
        {
            "published": PublishedSource(store),
            "ledgers": FolderSource(ledgers, name="ledgers"),
        },
        tags={},
    )
    keys = [r["key"] for r in cat.rows()]
    assert keys[0] == "ledgers:new.md" and any(k.startswith("published:") for k in keys)
    hits = cat.rows("zanzibar")
    assert [r["key"] for r in hits] == ["ledgers:new.md"] and "zanzibar" in hits[0][
        "snippet"
    ]
    assert [r["source"] for r in cat.rows("quarterly")] == ["published"]
    assert [r["id"] for r in cat.rows("plan", source="ledgers")] == ["team/plan.md"]
    assert cat.rows("zanzibar nowhere-at-all") == []
    pub = next(r for r in cat.rows() if r["source"] == "published")
    assert pub["tags"] == ["q3"] and pub["session"] == "pub-agent"
    row = cat.set_tags(pub["key"], ["final"])  # replaces the publisher's tags
    assert row["tags"] == ["final"] and cat.tag_counts() == {"final": 1}
    cat.set_tags("ledgers:old.md", ["final", "archive"])
    assert cat.tag_counts() == {"archive": 1, "final": 2}
    assert [r["id"] for r in cat.rows("archive")] == ["old.md"]
    with pytest.raises(KeyError):
        cat.set_tags("ledgers:nope.md", ["x"])
    with pytest.raises(KeyError):
        cat.rows(source="nope")
    assert split_key("ledgers:team/plan.md") == ("ledgers", "team/plan.md")


# -- the API -----------------------------------------------------------------------------


def test_items_api_list_get_patch_and_tags(client, ledgers, store, tmp_path):
    before = _digest(ledgers)
    body = client.get("/items").json()
    assert body["total"] == 5 and body["data"][0]["key"] == "ledgers:new.md"
    assert [
        r["id"]
        for r in client.get(
            "/items", params={"source": "ledgers", "q": "zanzibar"}
        ).json()["data"]
    ] == ["new.md"]
    assert client.get("/items", params={"source": "nope"}).status_code == 404
    assert client.get("/sources").json()["sources"] == [
        {"name": "published", "title": "Published"},
        {"name": "ledgers", "title": "Ledgers"},
    ]

    item = client.get("/items/ledgers:team/plan.md").json()
    assert item["title"] == "The plan" and item["text"].startswith("# The plan")
    # the encoding @zodal/store-http's provider sends: the whole key, percent-encoded
    assert client.get("/items/ledgers%3Ateam%2Fplan.md").json()["id"] == "team/plan.md"
    assert client.get("/items/ledgers:escape.md").status_code == 404
    assert client.get("/items/ledgers:..%2F..%2Foutside.md").status_code == 404
    assert client.get("/items/nokey").status_code == 404

    r = client.patch("/items/ledgers:new.md", json={"tags": ["todo", " Todo ", "read"]})
    assert r.status_code == 200 and r.json()["tags"] == ["read", "todo"]
    assert (
        client.get("/items", params={"q": "todo"}).json()["data"][0]["key"]
        == "ledgers:new.md"
    )
    assert client.get("/tags").json() == {"tags": {"q3": 1, "read": 1, "todo": 1}}
    assert client.patch("/items/ledgers:new.md", json={"title": "x"}).status_code == 422
    assert (
        client.patch("/items/ledgers:new.md", json={"tags": "todo"}).status_code == 422
    )
    assert (
        client.patch("/items/ledgers:new.md", json={"tags": ["x" * 99]}).status_code
        == 422
    )
    assert client.patch("/items/ledgers:nope.md", json={"tags": []}).status_code == 404

    # tags live under the data root, and the ledger folder is never written
    assert json.loads((tmp_path / "data" / "tags" / "tags.json").read_text()) == {
        "ledgers:new.md": ["read", "todo"]
    }
    assert _digest(ledgers) == before


def test_folder_files_are_sandboxed_and_revalidated(client):
    r = client.get("/files/ledgers/team/plan.md")
    assert r.status_code == 200 and r.text.startswith("# The plan")
    assert (
        "sandbox" in r.headers["content-security-policy"]
        and r.headers["cache-control"] == "private, no-cache"
    )
    for bad in [
        "/files/ledgers/escape.md",
        "/files/ledgers/.hidden.md",
        "/files/published/x",
        "/files/nope/x.md",
    ]:
        assert client.get(bad).status_code == 404


def test_purge_forgets_a_documents_tags(client, store):
    key = next(
        r["key"]
        for r in client.get("/items").json()["data"]
        if r["source"] == "published"
    )
    doc_id = key.split(":", 1)[1]
    client.patch(f"/items/{key}", json={"tags": ["gone-soon"]})
    client.post(f"/docs/{doc_id}/trash")
    assert client.get("/items", params={"trash": True}).json()["data"][0]["tags"] == [
        "gone-soon"
    ]
    client.delete(f"/docs/{doc_id}")
    assert client.get("/tags").json() == {"tags": {}}


def test_sources_from_env_and_standalone_routes(store, ledgers, monkeypatch):
    monkeypatch.setenv("ANNALS_SOURCES", f"ledgers={ledgers}")
    c = TestClient(mk_app(store=store, authorizer=no_auth), follow_redirects=False)
    assert c.get("/annals/api/items", params={"source": "ledgers"}).json()["total"] == 4
    for path in ["/annals/all", "/annals/s/ledgers", "/annals/i/ledgers/team/plan.md"]:
        assert c.get(path).status_code == 200
    with pytest.raises(ValueError):
        mk_api(store=store, sources={"published": ledgers})


def test_document_endpoints_show_the_owners_tags(client):
    key = next(
        r["key"]
        for r in client.get("/items").json()["data"]
        if r["source"] == "published"
    )
    doc_id = key.split(":", 1)[1]
    assert client.get(f"/docs/{doc_id}").json()["tags"] == ["q3"]
    client.patch(f"/items/{key}", json={"tags": ["mine"]})
    assert client.get(f"/docs/{doc_id}").json()["tags"] == ["mine"]
    assert client.get("/docs").json()["docs"][0]["tags"] == ["mine"]
