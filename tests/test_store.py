"""The store on a local target: publish, list, search, bin, groups, and the id format."""

import json
import re
from pathlib import Path

import pytest

from intray.store import DocStore, check_id, kind_of, mk_id, slugify


def test_slugify_and_id_shape():
    assert slugify("Star Wars: the Report!") == "star-wars-the-report"
    assert slugify("   ") == "doc"
    doc_id = mk_id("Hello World")
    assert re.match(r"^\d{8}-\d{6}-hello-world-[0-9a-f]{4}$", doc_id)
    assert check_id(doc_id) == doc_id
    with pytest.raises(ValueError):
        check_id("../etc/passwd")


def test_kind_of():
    assert kind_of("a.md") == "md" and kind_of("x.HTML") == "html"
    assert kind_of("notes.txt") == "text" and kind_of("img.png") == "file"


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


def test_publish_markdown_infers_title_and_excerpt(store, tmp_path):
    src = tmp_path / "report.md"
    src.write_text("# Quarterly report\n\nSome **bold** findings here.\n", encoding="utf-8")
    meta = store.publish(src, tags=["q3", " finance "])
    assert meta["title"] == "Quarterly report"
    assert meta["kind"] == "md" and meta["main"] == "report.md"
    assert meta["tags"] == ["finance", "q3"]
    assert "bold findings" in meta["excerpt"]
    on_disk = json.loads((store.target.root / "docs" / meta["id"] / "meta.json").read_text())
    assert on_disk["id"] == meta["id"]
    assert store.read_text(meta["id"]).startswith("# Quarterly")


def test_publish_html_directory_picks_index(store, tmp_path):
    d = tmp_path / "site"
    d.mkdir()
    (d / "index.html").write_text("<html><head><title>My artifact</title></head><body>hi</body></html>")
    (d / "style.css").write_text("body{}")
    meta = store.publish(d)
    assert meta["title"] == "My artifact" and meta["kind"] == "html"
    assert meta["main"] == "index.html" and sorted(meta["files"]) == ["index.html", "style.css"]


def test_publish_text_and_list_order(store):
    a = store.publish(text="# A\n\nfirst", title="A")
    b = store.publish(text="# B\n\nsecond", title="B")
    ids = [m["id"] for m in store.list()]
    assert ids.index(b["id"]) < ids.index(a["id"])  # newest first
    assert [m["id"] for m in store.search("second")] == [b["id"]]
    assert store.search("nothing-like-this") == []


def test_trash_restore_purge(store):
    m = store.publish(text="x", title="Doomed")
    assert store.meta(m["id"])["in_trash"] is False
    with pytest.raises(PermissionError):
        store.purge(m["id"])
    t = store.trash(m["id"])
    assert t["in_trash"] is True and "trashed" in t
    assert [x["id"] for x in store.list(trash=True)] == [m["id"]] and store.list() == []
    store.trash(m["id"])  # idempotent
    r = store.restore(m["id"])
    assert r["in_trash"] is False and "trashed" not in r
    assert [x["id"] for x in store.list()] == [m["id"]]
    store.trash(m["id"])
    store.purge(m["id"])
    with pytest.raises(KeyError):
        store.meta(m["id"])


def test_groups(store):
    a = store.publish(text="a", title="A")
    b = store.publish(text="b", title="B")
    g = store.make_group("Both", [a["id"], b["id"]])
    assert store.group(g["id"])["docs"] == [a["id"], b["id"]]
    store.add_to_group(g["id"], [b["id"], a["id"]])  # no duplicates
    assert store.group(g["id"])["docs"] == [a["id"], b["id"]]
    assert [x["id"] for x in store.list_groups()] == [g["id"]]
    with pytest.raises(KeyError):
        store.group(mk_id("nope"))


def test_missing_source_raises(store, tmp_path):
    with pytest.raises(FileNotFoundError):
        store.publish(tmp_path / "absent.md")
