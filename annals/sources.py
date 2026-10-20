"""Item sources: everything the page lists, wherever it lives, as rows of one shape.

A *source* is a named, read-mostly collection of items. Two kinds exist:

* :class:`PublishedSource`: the documents agents published (a :class:`annals.store.DocStore`).
* :class:`FolderSource`: a folder of files owned by someone else, read in place and never
  written (the crowsnest ledgers, and any other personal folder later). Its items are the
  folder's files, keyed by their path relative to the folder.

Every source yields the same row shape, which the page lists, searches and filters:

``key``      ``<source>:<id>``, unique across sources (the API's item id)
``source``   the source's name; ``id`` the item's id within it
``title``, ``kind`` (see :func:`annals.store.kind_of`), ``session`` (who wrote it)
``time``     ISO 8601, UTC: publication time, or a file's last modification
``size``, ``tags`` (the item's own; the catalog overlays the owner's), ``excerpt``

Sources are plain objects with a few methods (the :class:`Source` protocol), so a new kind
of folder is a new class or a new keyword argument, never a change to the API.
"""

from __future__ import annotations

import fnmatch
import os
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Protocol

from annals.config import DFLT_MAX_CACHED_TEXTS, MAX_INLINE_TEXT_BYTES
from annals.store import (
    DFLT_EXCLUDE,
    HEAD_CHARS,
    TEXT_KINDS,
    DocStore,
    kind_of,
    title_and_excerpt,
)

PUBLISHED = "published"
KEY_SEP = ":"
#: a source name is a url segment and part of every item key
SOURCE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
#: names the page uses for its own routes (``/all``, ``/trash``) or the published documents
RESERVED_SOURCE_NAMES = frozenset({PUBLISHED, "all", "trash"})


def check_source_name(name: str) -> str:
    """``name`` if it can name an extra source; ``ValueError`` saying why not otherwise."""
    if not SOURCE_NAME_RE.match(name):
        raise ValueError(
            f"a source name is lowercase letters, digits, - and _: {name!r}"
        )
    if name in RESERVED_SOURCE_NAMES:
        raise ValueError(f"{name!r} is reserved; pick another source name")
    return name


class Source(Protocol):
    """What the catalog needs from a source of items."""

    name: str
    title: str

    def rows(self, *, trash: bool = False) -> list[dict]:
        """Listing rows, newest first."""
        ...

    def item(self, item_id: str) -> dict:
        """One row plus what the page shows (``text`` for text kinds). ``KeyError`` if absent."""
        ...

    def text(self, item_id: str) -> str:
        """The item's full text for search (``""`` when it has none)."""
        ...


def mk_key(source: str, item_id: str) -> str:
    return f"{source}{KEY_SEP}{item_id}"


def split_key(key: str) -> tuple[str, str]:
    """``"ledgers:a/b.md"`` -> ``("ledgers", "a/b.md")``; ``KeyError`` when malformed."""
    source, sep, item_id = key.partition(KEY_SEP)
    if not sep or not source or not item_id:
        raise KeyError(key)
    return source, item_id


def iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


# -- published documents ---------------------------------------------------------------


def with_thumb(meta: dict) -> dict:
    """Add ``thumb`` (the first image, main file first) and fix pre-media kinds.

    Documents published before media kinds existed say ``file`` for an image or a video;
    their kind is recomputed from the main file so they show inline too.
    """
    if meta.get("kind") == "file" and meta.get("main"):
        meta["kind"] = kind_of(meta["main"])
    files = (
        [meta["main"]] + meta.get("files", [])
        if meta.get("main")
        else meta.get("files", [])
    )
    meta["thumb"] = next((f for f in files if kind_of(f) == "image"), None)
    return meta


def list_meta(meta: dict) -> dict:
    """A listing row: the meta without its per-file tables (a folder can hold thousands)."""
    row = with_thumb(dict(meta))
    row["n_files"] = len(row.pop("files", []) or [])
    row.pop("sizes", None)
    return row


class PublishedSource:
    """The documents agents published, as rows (a view over a :class:`DocStore`).

    Always named ``published``: the page links its items to ``/d/<id>``.
    """

    def __init__(
        self,
        store: DocStore,
        *,
        title: str = "Published",
        max_cached_texts: int = DFLT_MAX_CACHED_TEXTS,
    ):
        self.store = store
        self.name = PUBLISHED
        self.title = title
        self.max_cached_texts = max_cached_texts
        # id -> (its ``updated`` stamp, text), least recently used first: a replace changes
        # the stamp, a purge calls :meth:`forget`, and the size is bounded
        self._texts: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._stamps: dict[str, str] = {}  # id -> its ``updated``, as last listed
        self._lock = threading.Lock()  # sync endpoints run in a thread pool

    def _row(self, meta: dict) -> dict:
        row = list_meta(meta)
        row.update(
            key=mk_key(self.name, meta["id"]),
            source=self.name,
            session=(meta.get("source") or {}).get("session", ""),
            host=(meta.get("source") or {}).get("host", ""),
            time=meta.get("updated") or meta.get("created", ""),
            tags=list(meta.get("tags") or []),
        )
        return row

    def rows(self, *, trash: bool = False) -> list[dict]:
        metas = self.store.list(trash=trash)
        with self._lock:
            if not trash:  # a live listing is every id there is to cache; the rest are gone
                listed = {m["id"] for m in metas}
                for gone in set(self._stamps) - listed:
                    self._stamps.pop(gone, None)
                    self._texts.pop(gone, None)
            self._stamps.update((m["id"], m.get("updated", "")) for m in metas)
        return [self._row(m) for m in metas]

    def item(self, item_id: str) -> dict:
        try:
            meta = self.store.meta(item_id)
        except ValueError:
            raise KeyError(item_id)
        row = self._row(meta)
        row["files"] = meta.get("files", [])
        row["in_trash"] = meta.get("in_trash", False)
        if row["kind"] in TEXT_KINDS and meta.get("size", 0) <= MAX_INLINE_TEXT_BYTES:
            row["text"] = self.store.read_text(item_id)
        return row

    def text(self, item_id: str) -> str:
        with self._lock:
            cached = self._texts.get(item_id)
            if cached and cached[0] == self._stamps.get(item_id, ""):
                self._texts.move_to_end(item_id)
                return cached[1]
        try:
            meta = self.store.meta(item_id)
            ok = (
                meta["kind"] in TEXT_KINDS
                and meta.get("size", 0) <= MAX_INLINE_TEXT_BYTES
            )
            text = self.store.read_text(item_id) if ok else ""
        except (KeyError, ValueError, OSError):
            return ""
        with self._lock:
            # a purge that ran while we read must not get its text cached again
            if item_id in self._stamps or not self._stamps:
                self._texts[item_id] = (meta.get("updated", ""), text)
                self._texts.move_to_end(item_id)
                while len(self._texts) > self.max_cached_texts:
                    self._texts.popitem(last=False)
        return text

    def forget(self, item_id: str) -> None:
        """Drop what is cached for a document that is gone for good (purged)."""
        with self._lock:
            self._texts.pop(item_id, None)
            self._stamps.pop(item_id, None)


# -- a folder read in place ------------------------------------------------------------


def top_level_name(rel: str) -> str:
    """Who wrote a file in a folder of per-session files: ``a.md`` -> ``a``, ``b/c.md`` -> ``b``."""
    parts = PurePosixPath(rel).parts
    return parts[0] if len(parts) > 1 else PurePosixPath(parts[0]).stem


class FolderSource(Mapping):
    """A folder of files, read in place and never written, as a ``Mapping`` of rows.

    Keys are paths relative to ``root`` (``"annals.md"``, ``"cw-liaise/design.md"``), values
    listing rows. The folder is walked on every listing (a stat per file, cheap for
    hundreds), and a file is re-read only when its size or mtime changed. Hidden files and
    caches are skipped (``exclude``, the same patterns a directory publish skips), and so
    is anything that resolves outside ``root``.

    ``session_of(rel)`` names who wrote a file; the default suits a folder of per-session
    files and sub-folders (:func:`top_level_name`).
    """

    def __init__(
        self,
        root: Path | str,
        *,
        name: str,
        title: str | None = None,
        exclude: Iterable[str] = DFLT_EXCLUDE,
        session_of: Callable[[str], str] = top_level_name,
    ):
        check_source_name(name)
        self.root = Path(root).expanduser()
        self.name = name
        self.title = title or name.replace("-", " ").replace("_", " ").capitalize()
        self.exclude = tuple(exclude)
        self.session_of = session_of
        self._rows: dict[str, tuple[tuple, dict]] = {}
        self._texts: dict[str, tuple[tuple, str]] = {}
        self._lock = threading.Lock()

    # -- the Mapping ---------------------------------------------------------------

    def _skip(self, name: str) -> bool:
        return any(fnmatch.fnmatch(name, pat) for pat in self.exclude)

    def _walk(self, rel_dir: str = "") -> Iterator[tuple[str, os.DirEntry]]:
        """``(rel, entry)`` for every file kept, sorted.

        Sub-folders are walked, but a symlinked folder never is (a link to ``.`` would
        loop); a symlinked file is kept only when its target is itself a file :meth:`file_path`
        would serve (inside the root, not hidden).
        """
        try:
            with os.scandir(os.path.join(self.root, rel_dir)) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            if self._skip(e.name):
                continue
            rel = f"{rel_dir}/{e.name}" if rel_dir else e.name
            try:
                if e.is_symlink():
                    self.file_path(rel)  # KeyError unless the target is servable
                    yield rel, e
                elif e.is_dir():
                    yield from self._walk(rel)
                elif e.is_file():
                    yield rel, e
            except (KeyError, OSError):
                continue

    def _inside(self, path: Path) -> bool:
        """Inside the root, and not hidden there (the resolved path, so a link cannot dodge)."""
        root = self.root.resolve()
        if not path.is_relative_to(root):
            return False
        return not any(self._skip(part) for part in path.relative_to(root).parts)

    def __iter__(self) -> Iterator[str]:
        return (rel for rel, _ in self._walk())

    def __len__(self) -> int:
        return sum(1 for _ in self._walk())

    def __getitem__(self, rel: str) -> dict:
        path = self.file_path(rel)
        return self._row(rel, str(path), path.stat())

    def _row(self, rel: str, path: str, st: os.stat_result) -> dict:
        """The row for a file, re-read only when its size or mtime changed."""
        stamp = (st.st_mtime_ns, st.st_size)
        cached = self._rows.get(rel)
        if cached and cached[0] == stamp:
            return cached[1]
        kind = kind_of(rel)
        head = ""
        if kind in TEXT_KINDS or kind == "html":
            with open(path, encoding="utf-8", errors="replace") as f:
                head = f.read(HEAD_CHARS)
        title, excerpt = title_and_excerpt(head, kind)
        row = {
            "key": mk_key(self.name, rel),
            "source": self.name,
            "id": rel,
            "title": title or PurePosixPath(rel).stem.replace("_", " "),
            "kind": kind,
            "session": self.session_of(rel),
            "time": iso_utc(st.st_mtime),
            "size": st.st_size,
            "tags": [],
            "excerpt": excerpt,
        }
        with self._lock:
            self._rows[rel] = (stamp, row)
        return row

    def __contains__(self, rel: object) -> bool:
        try:
            self.file_path(str(rel))
            return True
        except KeyError:
            return False

    # -- the Source protocol -------------------------------------------------------

    def file_path(self, rel: str) -> Path:
        """The file on disk; ``KeyError`` if it is absent, hidden, or escapes the root.

        Only the canonical spelling of a path is accepted (``a/b.md``, not ``./a/b.md``,
        ``a//b.md`` or ``a/b.md/``), so one file has one key.
        """
        p = PurePosixPath(rel)
        if (
            not rel
            or "\x00" in rel
            or str(p) != rel
            or p.is_absolute()
            or ".." in p.parts
            or any(self._skip(s) for s in p.parts)
        ):
            raise KeyError(rel)
        try:
            path = (self.root / rel).resolve()
            if not self._inside(path) or not path.is_file():
                raise KeyError(rel)
        except (OSError, ValueError):
            raise KeyError(rel)
        return path

    def rows(self, *, trash: bool = False) -> list[dict]:
        if trash:
            return []  # nothing here is ever binned: annals does not own these files
        out = []
        for rel, entry in self._walk():
            try:
                out.append(dict(self._row(rel, entry.path, entry.stat())))
            except OSError:
                continue  # vanished between the walk and the stat
        return sorted(out, key=lambda r: r["time"], reverse=True)

    def item(self, rel: str) -> dict:
        row = dict(self[rel])
        if row["kind"] in TEXT_KINDS and row["size"] <= MAX_INLINE_TEXT_BYTES:
            row["text"] = self.text(rel)
        return row

    def text(self, rel: str) -> str:
        """The file's text (cached until it changes); ``""`` for binaries and huge files."""
        cached = self._texts.get(rel)
        row = self._rows.get(rel)
        if cached and row and cached[0] == row[0]:
            # a listing just stat'ed it: the cached text is current for that listing
            return cached[1]
        try:
            path = self.file_path(rel)
            st = path.stat()
        except (KeyError, OSError):
            return ""
        if (
            kind_of(rel) not in TEXT_KINDS | {"html"}
            or st.st_size > MAX_INLINE_TEXT_BYTES
        ):
            return ""
        stamp = (st.st_mtime_ns, st.st_size)
        if cached and cached[0] == stamp:
            return cached[1]
        text = path.read_text(encoding="utf-8", errors="replace")
        with self._lock:
            self._texts[rel] = (stamp, text)
        return text


def as_source(name: str, spec: Source | Path | str) -> Source:
    """A source from a source, or from a folder path (read in place as a :class:`FolderSource`)."""
    if isinstance(spec, (str, Path)):
        return FolderSource(spec, name=name)
    return spec


def parse_sources_spec(spec: str) -> dict[str, str]:
    """``"ledgers=~/x, notes=/y"`` -> ``{"ledgers": "~/x", "notes": "/y"}`` (the env form)."""
    out = {}
    for part in spec.split(","):
        name, sep, path = part.strip().partition("=")
        if part.strip() and (not sep or not name.strip() or not path.strip()):
            raise ValueError(f"expected name=path, got {part.strip()!r}")
        if sep:
            out[name.strip()] = path.strip()
    return out
