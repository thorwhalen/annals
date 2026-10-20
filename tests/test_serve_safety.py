"""``annals serve`` refuses an open non-loopback server; purged documents leave the text cache (annals#8)."""

import pytest

pytest.importorskip("uvicorn")
import uvicorn

from annals import api
from annals.sources import PublishedSource
from annals.store import DocStore

AUTH_VARS = ("ANNALS_WHOAMI_URL", "ANNALS_ALLOWED_USERS", "ANNALS_BASIC_USER", "ANNALS_BASIC_PASSWORD")


@pytest.fixture
def ran(monkeypatch, tmp_path):
    for v in AUTH_VARS:
        monkeypatch.delenv(v, raising=False)
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    monkeypatch.setenv("ANNALS_DATA_DIR", str(tmp_path / "data"))
    return calls


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "example.org"])
def test_a_reachable_host_without_auth_is_refused(ran, host) -> None:
    with pytest.raises(ValueError, match="no auth is configured"):
        api.serve(host=host)
    assert ran == []


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]", "::ffff:127.0.0.1"])
def test_loopback_without_auth_is_fine(ran, host) -> None:
    api.serve(host=host)
    assert ran[0]["host"] == host


def test_allow_open_overrides(ran) -> None:
    api.serve(host="0.0.0.0", allow_open=True)
    assert ran[0]["host"] == "0.0.0.0"


def test_a_reachable_host_with_auth_is_fine(ran, monkeypatch) -> None:
    monkeypatch.setenv("ANNALS_BASIC_USER", "u")
    monkeypatch.setenv("ANNALS_BASIC_PASSWORD", "p")
    api.serve(host="0.0.0.0")
    assert ran[0]["host"] == "0.0.0.0"


def test_the_text_cache_is_bounded_and_forgets_purged_documents(tmp_path) -> None:
    store = DocStore(tmp_path)
    ids = [store.publish(text=f"# d{i}", title=f"d{i}")["id"] for i in range(4)]
    source = PublishedSource(store, max_cached_texts=2)
    source.rows()
    for i in ids:
        assert source.text(i).startswith("# d")
    assert len(source._texts) == 2
    source.text(ids[-1])
    source.forget(ids[-1])
    assert ids[-1] not in source._texts and ids[-1] not in source._stamps


def test_catalog_forget_reaches_the_published_text_cache(tmp_path) -> None:
    from annals.catalog import mk_catalog
    from annals.sources import PUBLISHED, mk_key

    store = DocStore(tmp_path)
    doc_id = store.publish(text="# gone", title="gone")["id"]
    catalog = mk_catalog(store)
    catalog.rows()
    source = catalog.sources[PUBLISHED]
    source.text(doc_id)
    assert doc_id in source._texts
    catalog.forget(mk_key(PUBLISHED, doc_id))
    assert doc_id not in source._texts


def test_a_live_listing_drops_documents_that_vanished_elsewhere(tmp_path) -> None:
    store = DocStore(tmp_path)
    doc_id = store.publish(text="# x", title="x")["id"]
    source = PublishedSource(store)
    source.rows()
    source.text(doc_id)
    store.trash(doc_id)
    store.purge(doc_id)  # as another process would
    source.rows()
    assert doc_id not in source._texts and doc_id not in source._stamps
