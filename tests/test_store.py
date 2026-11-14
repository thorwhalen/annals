"""The store on a local target: publish, list, search, bin, groups, and the id format."""

import json
import re
from pathlib import Path

import pytest

from annals.store import DocStore, check_id, kind_of, mk_id, slugify


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
    assert kind_of("notes.txt") == "text" and kind_of("img.png") == "image" and kind_of("x.bin") == "file"
    assert [kind_of(f) for f in ("a.mp4", "b.MP3", "c.pdf", "d.webp")] == ["video", "audio", "pdf", "image"]


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


def test_directory_publish_skips_junk_unless_asked(tmp_path):
    d = tmp_path / "out"
    (d / "__pycache__").mkdir(parents=True)
    (d / "page.md").write_text("# P")
    (d / ".DS_Store").write_bytes(b"x")
    (d / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"x")
    s = DocStore(tmp_path / "data")
    assert s.publish(d)["files"] == ["page.md"]
    assert len(s.publish(d, exclude=())["files"]) == 3


def test_groups_of_a_document(store):
    """The groups a document is in, newest first: its page links to each."""
    a = store.publish(text="# A", title="A")
    b = store.publish(text="# B", title="B")
    g1 = store.make_group("First", [a["id"], b["id"]])
    g2 = store.make_group("Second", [a["id"]])
    assert {g["id"] for g in store.groups_of(a["id"])} == {g1["id"], g2["id"]}
    assert store.groups_of(b["id"]) == [{"id": g1["id"], "title": "First", "n": 2}]
    assert store.groups_of("nowhere") == []


def test_audio_with_its_timed_text_beside_it_is_an_audio_document(tmp_path):
    store = DocStore(tmp_path / "data")
    talk = tmp_path / "talk"
    talk.mkdir()
    for name in ("talk.mp3", "talk.vtt", "talk.chapters.vtt", "talk.cues.json"):
        (talk / name).write_bytes(b"x")
    meta = store.publish(talk, title="Talk")
    assert (meta["kind"], meta["main"]) == ("audio", "talk.mp3")
    # a file that is not its timed text keeps it a folder
    (talk / "notes.vtt").write_bytes(b"x")
    assert store.publish(talk, title="Talk and notes")["kind"] == "folder"


@pytest.mark.parametrize(
    "names, kind",
    [
        (("talk.mp3", "talk.VTT"), "audio"),  # the suffix in any case
        (("a/talk.mp3", "b/talk.vtt"), "folder"),  # timed text sits beside its audio
        (("talk.mp4", "talk.vtt"), "folder"),  # video does not show it yet
    ],
)
def test_which_files_are_timed_text_of_an_audio_file(tmp_path, names, kind):
    store = DocStore(tmp_path / "data")
    root = tmp_path / "doc"
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"x")
    assert store.publish(root, title="Doc")["kind"] == kind
