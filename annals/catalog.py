"""The catalog: every source's items as one list, with search and the owner's tags.

:class:`Catalog` is the facade the HTTP API stands on. It combines named sources (see
:mod:`annals.sources`) and a tag store (see :mod:`annals.tags`):

* :meth:`Catalog.rows` lists items newest first, across sources or within one, each row
  with the owner's tags overlaid. With a query, the catalog's search strategy (its
  ``search`` keyword; see :mod:`annals.search`) picks the matching rows, best first, each
  with a ``snippet`` of the text around the match and, when it ranks, a ``score``.
* :meth:`Catalog.item` is one item, :meth:`Catalog.set_tags` replaces its tags (in the tag
  store, never in the item), :meth:`Catalog.tag_counts` lists every tag in use.

Facets (kind, session, date, tag) are not computed here: the page counts them over the rows
it received, so every toggle is instant and the counts are always the ones the current
query would give.
"""

from __future__ import annotations

import shutil
from collections import Counter
from collections.abc import Mapping, MutableMapping

import os
from pathlib import Path

from annals.config import ENV_SOURCES
from annals.sources import (
    PUBLISHED,
    PublishedSource,
    Source,
    as_source,
    check_source_name,
    mk_key,
    parse_sources_spec,
    split_key,
)
from annals.search import SearchStrategy, default_search, query_words, scan_search
from annals.store import THUMB_CACHE, DocStore
from annals.tags import TAGS_DIR, TAGS_FILE, JsonTagStore, normalize_tags


class Catalog:
    """Named sources plus the owner's tags, listed, searched and tagged as one collection."""

    def __init__(
        self,
        sources: Mapping[str, Source],
        *,
        tags: MutableMapping[str, list[str]],
        search: SearchStrategy = scan_search,
    ):
        self.sources = dict(sources)
        self.tags = tags
        self.search = search

    def _source(self, name: str) -> Source:
        try:
            return self.sources[name]
        except KeyError:
            raise KeyError(f"no source named {name!r}")

    def _overlay(self, row: dict, tags: Mapping[str, list[str]]) -> dict:
        own = tags.get(row["key"])
        if own is not None:
            row["tags"] = list(own)
        return row

    def _tag_snapshot(self) -> dict[str, list[str]]:
        snap = getattr(self.tags, "snapshot", None)
        return snap() if snap else dict(self.tags)

    def sources_info(self) -> list[dict]:
        """Each source's name and title, in the order given."""
        return [{"name": n, "title": s.title} for n, s in self.sources.items()]

    def rows(
        self, q: str = "", *, source: str | None = None, trash: bool = False
    ) -> list[dict]:
        """Items from one source or all: newest first, or, with a query ``q``, the ones
        the search strategy matched, best first."""
        names = [source] if source else list(self.sources)
        tags = self._tag_snapshot()
        rows = [
            self._overlay(row, tags)
            for name in names
            for row in self._source(name).rows(trash=trash)
        ]
        rows.sort(key=lambda r: r.get("time", ""), reverse=True)
        if not query_words(q):
            return rows
        return self.search(q, rows, self._text_of)

    def _text_of(self, row: dict) -> str:
        return self.sources[row["source"]].text(row["id"])

    def item(self, key: str) -> dict:
        """One item, with what the page shows; ``KeyError`` if there is none."""
        source, item_id = split_key(key)
        return self._overlay(self._source(source).item(item_id), self._tag_snapshot())

    def set_tags(self, key: str, tags: list[str]) -> dict:
        """Replace an item's tags (in the tag store); the item's row, with them."""
        source, item_id = split_key(key)
        self._source(source).item(item_id)  # KeyError for an item that does not exist
        self.tags[mk_key(source, item_id)] = normalize_tags(tags)
        return self.item(key)

    def forget(self, key: str) -> None:
        """Drop an item's tags, its search entry and any cached text (when the item itself
        is gone for good)."""
        self.tags.pop(key, None)
        drop_indexed = getattr(self.search, "forget", None)
        if drop_indexed:
            drop_indexed(key)
        try:
            source, item_id = split_key(key)
        except KeyError:
            return
        drop = getattr(self.sources.get(source), "forget", None)
        if drop:
            drop(item_id)

    def tag_counts(self) -> dict[str, int]:
        """Every tag in use on a listed item, with how many items carry it."""
        counts = Counter(t for r in self.rows() for t in r.get("tags", []))
        return dict(sorted(counts.items(), key=lambda kv: kv[0].lower()))


def purge_document(store: DocStore, catalog: Catalog, doc_id: str) -> dict:
    """Delete a document that is in the bin for good: its files, its tags, its cached thumbnails.

    ``PermissionError`` for one that is not in the bin. Every surface purges through here.
    """
    store.purge(doc_id)
    catalog.forget(mk_key(PUBLISHED, doc_id))
    root = store.target.local_path(".")
    if root is not None:
        shutil.rmtree(root / THUMB_CACHE / doc_id, ignore_errors=True)
    return {"ok": True, "id": doc_id}


def owner_tags(store: DocStore) -> dict[str, list[str]]:
    """The owner's tags (set by ``annals tag`` or the page), keyed by item key, as one snapshot."""
    tags = default_tags(store)
    snap = getattr(tags, "snapshot", None)
    return snap() if snap else dict(tags)


def with_owner_tags(metas: list[dict], tags: Mapping[str, list[str]]) -> list[dict]:
    """``metas`` (documents' meta) with each one's tags replaced by the owner's, where the owner set them.

    >>> with_owner_tags([{"id": "a", "tags": ["x"]}, {"id": "b", "tags": ["y"]}], {"published:a": ["z"]})
    [{'id': 'a', 'tags': ['z']}, {'id': 'b', 'tags': ['y']}]
    """
    return [
        {**m, "tags": list(tags.get(mk_key(PUBLISHED, m["id"]), m.get("tags", [])))}
        for m in metas
    ]


def default_tags(store: DocStore) -> MutableMapping[str, list[str]]:
    """Where the owner's tags live by default: one JSON file under the data root
    (``tags/tags.json``), or a dict when the data root is not on this machine."""
    root = store.target.local_path(".")
    return JsonTagStore(root / TAGS_DIR / TAGS_FILE) if root is not None else {}


def mk_catalog(
    store: DocStore,
    *,
    sources: Mapping[str, Source | Path | str] | None = None,
    tags: MutableMapping[str, list[str]] | None = None,
    search: SearchStrategy | None = None,
) -> Catalog:
    """The published documents first, then the extra sources; the owner's tags beside them.

    ``sources`` maps a name to a folder path (read in place) or a :class:`Source`; by
    default the folders named in ``ANNALS_SOURCES``. ``tags`` defaults to one JSON file
    under the data root (``tags/tags.json``), or a dict when the data root is remote.
    ``search`` answers queries (see :mod:`annals.search`); by default a full-text index
    kept under the data root, or a plain scan when the data root is remote.
    The API, and any CLI or agent tool that tags items, build their catalog here.
    """
    if sources is None:
        sources = parse_sources_spec(os.environ.get(ENV_SOURCES, ""))
    if tags is None:
        tags = default_tags(store)
    if search is None:
        search = default_search(store.target.local_path("."))
    named: dict[str, Source] = {PUBLISHED: PublishedSource(store)}
    for name, spec in sources.items():
        named[check_source_name(name)] = as_source(name, spec)
    return Catalog(named, tags=tags, search=search)
