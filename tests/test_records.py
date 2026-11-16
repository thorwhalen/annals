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


def test_html_and_folder_documents_bring_their_text(tmp_path):
    store = _store(tmp_path)
    store.publish(text="<html><body><script>var x=1</script><p>Wasps build paper nests.</p></body></html>", title="Page", filename="p.html")
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "01-a.md").write_text("# A\n\nalpha text")
    (folder / "02-b.md").write_text("# B\n\nbeta text")
    store.publish(folder, title="Notes")
    got = {r["title"]: r["text"] for r in records(target=str(tmp_path))}
    assert "paper nests" in got["Page"] and "var x" not in got["Page"]
    assert "alpha text" in got["Notes"] and "beta text" in got["Notes"]


def test_tag_case_and_a_publisher_noindex_survive_an_owner_retag(tmp_path):
    from annals.catalog import mk_catalog
    from annals.sources import PUBLISHED, mk_key

    store = _store(tmp_path)
    store.publish(text="# One\n\nx", title="One", tags=["NoIndex"])
    two = store.publish(text="# Two\n\nx", title="Two", tags=["private"])
    mk_catalog(store).set_tags(mk_key(PUBLISHED, two["id"]), ["research"])  # the owner's tags replace it
    assert list(records(target=str(tmp_path))) == []


def test_a_remote_target_is_refused_not_indexed_partially(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="where they are"):
        list(records(target="somehost:/srv/annals"))


def test_a_huge_text_is_cut(tmp_path, monkeypatch):
    from annals import records as mod

    monkeypatch.setattr(mod, "MAX_TEXT_CHARS", 50)
    _store(tmp_path).publish(text="# Big\n\n" + "word " * 100, title="Big")
    (row,) = list(records(target=str(tmp_path)))
    assert len(row["text"]) == 50
