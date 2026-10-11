"""The catalog: every source's items as one list, with search and the owner's tags.

:class:`Catalog` is the facade the HTTP API stands on. It combines named sources (see
:mod:`annals.sources`) and a tag store (see :mod:`annals.tags`):

* :meth:`Catalog.rows` lists items newest first, across sources or within one, filtered by
  a full-text query (every word must appear in the title, tags, session, excerpt or full
  text; case-insensitive), each row with the owner's tags overlaid and, when there is a
  query, a ``snippet`` of the text around the first match.
* :meth:`Catalog.item` is one item, :meth:`Catalog.set_tags` replaces its tags (in the tag
  store, never in the item), :meth:`Catalog.tag_counts` lists every tag in use.

Facets (kind, session, date, tag) are not computed here: the page counts them over the rows
it received, so every toggle is instant and the counts are always the ones the current
query would give.
"""

from __future__ import annotations

import re
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
from annals.store import DocStore
from annals.tags import TAGS_DIR, TAGS_FILE, JsonTagStore, normalize_tags

SNIPPET_CHARS = 90


def _words(q: str) -> list[str]:
    return [w for w in q.lower().split() if w]


def _snippet(text: str, words: list[str], *, width: int = SNIPPET_CHARS) -> str:
    """The text around the first occurrence of any query word, on one line."""
    low = text.lower()
    hits = [i for i in (low.find(w) for w in words) if i >= 0]
    if not hits:
        return ""
    i = min(hits)
    start, end = max(0, i - width), min(len(text), i + width)
    s = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("…" if start else "") + s + ("…" if end < len(text) else "")


class Catalog:
    """Named sources plus the owner's tags, listed, searched and tagged as one collection."""

    def __init__(
        self, sources: Mapping[str, Source], *, tags: MutableMapping[str, list[str]]
    ):
        self.sources = dict(sources)
        self.tags = tags

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
        """Items newest first, from one source or all, matching every word of ``q``."""
        names = [source] if source else list(self.sources)
        tags = self._tag_snapshot()
        rows = [
            self._overlay(row, tags)
            for name in names
            for row in self._source(name).rows(trash=trash)
        ]
        rows.sort(key=lambda r: r.get("time", ""), reverse=True)
        words = _words(q)
        if not words:
            return rows
        out = []
        for row in rows:
            meta = " ".join(
                [
                    row.get("title", ""),
                    " ".join(row.get("tags", [])),
                    row.get("session", ""),
                    row.get("excerpt", ""),
                    row.get("id", ""),
                ]
            ).lower()
            missing = [w for w in words if w not in meta]
            text = self.sources[row["source"]].text(row["id"]) if missing else ""
            low = text.lower()
            if all(w in low for w in missing):
                row["snippet"] = _snippet(text, words) if text else ""
                out.append(row)
        return out

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
        """Drop an item's tags (when the item itself is gone for good)."""
        self.tags.pop(key, None)

    def tag_counts(self) -> dict[str, int]:
        """Every tag in use on a listed item, with how many items carry it."""
        counts = Counter(t for r in self.rows() for t in r.get("tags", []))
        return dict(sorted(counts.items(), key=lambda kv: kv[0].lower()))


def mk_catalog(
    store: DocStore,
    *,
    sources: Mapping[str, Source | Path | str] | None = None,
    tags: MutableMapping[str, list[str]] | None = None,
) -> Catalog:
    """The published documents first, then the extra sources; the owner's tags beside them.

    ``sources`` maps a name to a folder path (read in place) or a :class:`Source`; by
    default the folders named in ``ANNALS_SOURCES``. ``tags`` defaults to one JSON file
    under the data root (``tags/tags.json``), or a dict when the data root is remote.
    The API, and any CLI or agent tool that tags items, build their catalog here.
    """
    if sources is None:
        sources = parse_sources_spec(os.environ.get(ENV_SOURCES, ""))
    if tags is None:
        root = store.target.local_path(".")
        tags = JsonTagStore(root / TAGS_DIR / TAGS_FILE) if root is not None else {}
    named: dict[str, Source] = {PUBLISHED: PublishedSource(store)}
    for name, spec in sources.items():
        named[check_source_name(name)] = as_source(name, spec)
    return Catalog(named, tags=tags)
