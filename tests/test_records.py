"""The published documents as records for an ir index: current, indexable, with their metadata."""

from annals.records import records
from annals.store import DocStore


def _store(tmp_path):
    return DocStore(tmp_path)


def test_current_documents_come_with_text_and_metadata(tmp_path):
    store = _store(tmp_path)
    doc = store.publish(text="# TTS\n\nPiper and Kokoro.", title="TTS", tags=["a", "b"], source={"session": "s1"})
    (row,) = list(records(target=str(tmp_path)))
    assert row["id"] == doc["id"] and "Kokoro" in row["text"]
    assert (row["title"], row["tags"], row["session"], row["kind"]) == ("TTS", "a,b", "s1", "md")
    assert row["url"].endswith(f"/d/{doc['id']}") and row["updated"]


def test_the_bin_versions_derived_and_noindex_are_left_out(tmp_path):
    store = _store(tmp_path)
    keep = store.publish(text="# Keep\n\nx", title="Keep")
    gone = store.publish(text="# Gone\n\nx", title="Gone")
    store.trash(gone["id"])
    store.publish(text="# Over\n\nx", title="Over", tags=["overview"])
    store.publish(text="# Priv\n\nx", title="Priv", tags=["private"])
    v1 = store.publish(text="# Ver\n\nfirst", title="Ver")
    store.publish(text="# Ver\n\nsecond", title="Ver", replace=v1["id"])
    got = {r["title"]: r for r in records(target=str(tmp_path))}
    assert set(got) == {"Keep", "Ver"} and "second" in got["Ver"]["text"] and keep["id"] == got["Keep"]["id"]
    assert "Over" in {r["title"] for r in records(target=str(tmp_path), include_derived=True)}


def test_an_owner_tag_can_keep_a_document_out(tmp_path):
    from annals.catalog import mk_catalog
    from annals.sources import PUBLISHED, mk_key

    store = _store(tmp_path)
    doc = store.publish(text="# Hide\n\nx", title="Hide")
    mk_catalog(store).set_tags(mk_key(PUBLISHED, doc["id"]), ["noindex"])
    assert list(records(target=str(tmp_path))) == []


def test_a_document_without_text_is_found_by_its_title(tmp_path):
    store = _store(tmp_path)
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    store.publish(img, title="Wasp photo")
    (row,) = list(records(target=str(tmp_path)))
    assert row["text"].startswith("Wasp photo")
