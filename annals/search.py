"""How the catalog answers a query: the search strategies.

A strategy is a callable ``(query, rows, text_of) -> rows``: given every listed row (the
catalog has already listed them and overlaid the owner's tags) and a way to get an item's
full text, it returns the rows that match, best first, each with a ``snippet`` of the
text around the match and, when it ranks, a ``score`` (higher is better). The catalog
takes one as its ``search`` keyword (:class:`annals.catalog.Catalog`), so a smarter one
(semantic, hybrid, an agent that rewrites the query) plugs in at the same place.

Two ship here:

* :class:`IndexedSearch`, the default when the data root is on this machine: a SQLite
  FTS5 index kept on disk (``cache/search/index.sqlite`` under the data root). Each query
  brings it up to date first, re-reading only items whose stamp (time and size) changed,
  so the first query after a restart costs one pass over the texts and every later one a
  few milliseconds. Matching is by word prefix with English stemming (``rate`` finds
  "rates" and "rated", not "separate"), every word required, ranked by BM25 with the
  title weighted most.
* :func:`scan_search`, the index-free fallback (a remote data root, tests): every word
  must appear as a substring of the title, tags, session, excerpt, id or full text;
  newest first, as listed.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Protocol

#: characters of context on each side of the first match, in a snippet
SNIPPET_CHARS = 90
#: tokens in an index snippet (FTS5's own window)
SNIPPET_TOKENS = 24
#: the best rows that get a snippet (each costs ~5 ms); the rest show their excerpt.
#: One page of the list (the page's ``LIST_PAGE``).
SNIPPET_ROWS = 60
#: the most rows a ranked query returns; the page shows a few dozen at a time
MAX_RESULTS = 500
#: column weights for BM25, in the order of :data:`_COLUMNS` (the title matters most)
DFLT_WEIGHTS = (10.0, 5.0, 2.0, 1.0, 1.0)
#: the index's columns: what a row is searched by
_COLUMNS = ("title", "tags", "meta", "excerpt", "body")
#: the index file, under the data root
INDEX_REL = "cache/search/index.sqlite"
#: bumped when the schema or what is indexed changes: an old index is rebuilt
SCHEMA_VERSION = "2"
#: rows indexed per write transaction, so a first build never holds the lock for long
SYNC_BATCH = 200
#: bound variables per statement (SQLite's default limit is far above; this stays safe)
SQL_VARS = 500

TextOf = Callable[[dict], str]


class SearchStrategy(Protocol):
    """``(query, rows, text_of) -> matching rows, best first``."""

    def __call__(
        self, query: str, rows: Sequence[dict], text_of: TextOf
    ) -> list[dict]: ...


def query_words(q: str) -> list[str]:
    """The words of a query, lowercased: ``"Data  Rates"`` -> ``["data", "rates"]``."""
    return [w for w in q.lower().split() if w]


def snippet_around(text: str, words: Iterable[str], *, width: int = SNIPPET_CHARS) -> str:
    """The text around the first occurrence of any of ``words``, on one line.

    >>> snippet_around("alpha beta gamma", ["beta"], width=6)
    '…alpha beta gamma'
    """
    low = text.lower()
    hits = [i for i in (low.find(w) for w in words) if i >= 0]
    if not hits:
        return ""
    i = min(hits)
    start, end = max(0, i - width), min(len(text), i + width)
    s = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("…" if start else "") + s + ("…" if end < len(text) else "")


def _meta_text(row: dict) -> str:
    return " ".join([row.get("session", ""), row.get("id", ""), row.get("source", "")])


def scan_search(query: str, rows: Sequence[dict], text_of: TextOf) -> list[dict]:
    """Every word a substring of the row's fields or full text; rows kept in their order.

    The full text is read only for rows whose fields lack a word.
    """
    words = query_words(query)
    if not words:
        return list(rows)
    out = []
    for row in rows:
        fields = " ".join(
            [
                row.get("title", ""),
                " ".join(row.get("tags", [])),
                row.get("session", ""),
                row.get("excerpt", ""),
                row.get("id", ""),
            ]
        ).lower()
        missing = [w for w in words if w not in fields]
        text = text_of(row) if missing else ""
        low = text.lower()
        if all(w in low for w in missing):
            row["snippet"] = snippet_around(text, words) if text else ""
            out.append(row)
    return out


def fts_query(q: str) -> str:
    """A user's words as an FTS5 query: every word required, each a prefix.

    Each word is quoted, so FTS5 syntax typed by the user (``AND``, ``-``, ``:``, quotes)
    is searched for as text, never run as an operator.

    >>> fts_query('data rates')
    '"data"* "rates"*'
    >>> fts_query('a"b NOT')
    '"a""b"* "not"*'
    >>> fts_query('  ')
    ''
    """
    return " ".join('"' + w.replace('"', '""') + '"*' for w in query_words(q))


def _stamp(row: dict) -> str:
    """What changes when the indexed content does: the time, the size, the title, and the
    tags (the owner's are overlaid after listing, so editing them changes no file)."""
    return "|".join(
        [
            str(row.get("time", "")),
            str(row.get("size", "")),
            str(row.get("updated", "")),
            row.get("title", ""),
            ",".join(row.get("tags", [])),
        ]
    )


class IndexedSearch:
    """A SQLite FTS5 index of every row's fields and text, synced per query by stamp.

    ``path`` is the index file (made on first use; ``":memory:"`` keeps it in memory).
    ``weights`` are BM25's per-column weights (title, tags, session/id/source, excerpt,
    text). ``max_results`` caps a ranked answer; the best ``snippet_rows`` of it carry a
    ``snippet`` (the rest show their excerpt). Safe across threads (one sync at a time:
    queries that arrive during a sync wait for it rather than redo it) and across
    processes sharing the file (two web workers): writes are short transactions.
    """

    def __init__(
        self,
        path: Path | str = ":memory:",
        *,
        weights: Sequence[float] = DFLT_WEIGHTS,
        max_results: int = MAX_RESULTS,
        snippet_tokens: int = SNIPPET_TOKENS,
        snippet_rows: int = SNIPPET_ROWS,
    ):
        if len(weights) != len(_COLUMNS):
            raise ValueError(f"weights: one per column {_COLUMNS}, got {len(weights)}")
        self.path = str(path)
        self.weights = tuple(float(w) for w in weights)
        self.max_results = max_results
        self.snippet_tokens = snippet_tokens
        self.snippet_rows = snippet_rows
        self._lock = threading.Lock()  # the connection
        self._syncing = threading.Lock()  # one sync at a time
        self._db: sqlite3.Connection | None = None

    # -- the connection ------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._db is not None:
            return self._db
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        db.execute("PRAGMA busy_timeout=30000")
        if self.path != ":memory:":
            db.execute("PRAGMA journal_mode=WAL")
        version = None
        try:
            version = db.execute("SELECT v FROM info WHERE k='schema'").fetchone()
        except sqlite3.OperationalError:
            pass
        if not version or version[0] != SCHEMA_VERSION:
            with db:
                for table in ("fts", "stamps", "info"):
                    db.execute(f"DROP TABLE IF EXISTS {table}")
                db.execute("CREATE TABLE info (k TEXT PRIMARY KEY, v TEXT)")
                db.execute("INSERT INTO info VALUES ('schema', ?)", (SCHEMA_VERSION,))
                # an item's id in ``stamps`` is its rowid in ``fts``
                db.execute(
                    "CREATE TABLE stamps "
                    "(id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, stamp TEXT)"
                )
                db.execute(
                    "CREATE VIRTUAL TABLE fts USING fts5("
                    + ", ".join(_COLUMNS)
                    + ", tokenize='porter unicode61 remove_diacritics 2')"
                )
        self._db = db
        return db

    # -- keeping it current --------------------------------------------------------

    def sync(self, rows: Sequence[dict], text_of: TextOf) -> int:
        """(Re)index the rows whose stamp changed; returns how many.

        Nothing is dropped here: a query only ever answers with the rows it was given, so
        an item listed elsewhere (in the bin, behind a hiding store, or gone) simply does
        not come back, and two catalogs sharing one index never undo each other's work.
        :meth:`forget` drops an item for good.
        """
        with self._syncing:
            with self._lock:
                have = dict(self._connect().execute("SELECT key, stamp FROM stamps"))
            changed = [r for r in rows if have.get(r["key"]) != _stamp(r)]
            for at in range(0, len(changed), SYNC_BATCH):
                self._index(changed[at : at + SYNC_BATCH], text_of)
            return len(changed)

    def _index(self, rows: Sequence[dict], text_of: TextOf) -> None:
        # texts are read before the write transaction, so a slow read never holds it
        docs = [
            (
                r["key"],
                _stamp(r),
                r.get("title", ""),
                " ".join(r.get("tags", [])),
                _meta_text(r),
                r.get("excerpt", ""),
                text_of(r),
            )
            for r in rows
        ]
        with self._lock, self._connect() as db:
            for key, stamp, *cols in docs:
                found = db.execute("SELECT id FROM stamps WHERE key=?", (key,)).fetchone()
                if found:
                    rowid = found[0]
                    db.execute("DELETE FROM fts WHERE rowid=?", (rowid,))
                    db.execute("UPDATE stamps SET stamp=? WHERE id=?", (stamp, rowid))
                else:
                    rowid = db.execute(
                        "INSERT INTO stamps (key, stamp) VALUES (?, ?)", (key, stamp)
                    ).lastrowid
                db.execute(
                    "INSERT INTO fts (rowid, " + ", ".join(_COLUMNS) + ") "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (rowid, *cols),
                )

    def forget(self, key: str) -> None:
        """Drop an item from the index (it is gone for good)."""
        with self._lock, self._connect() as db:
            found = db.execute("SELECT id FROM stamps WHERE key=?", (key,)).fetchone()
            if found:
                db.execute("DELETE FROM fts WHERE rowid=?", found)
                db.execute("DELETE FROM stamps WHERE id=?", found)

    # -- the strategy --------------------------------------------------------------

    def __call__(self, query: str, rows: Sequence[dict], text_of: TextOf) -> list[dict]:
        match = fts_query(query)
        if not match:
            return list(rows)
        self.sync(rows, text_of)
        by_key = {r["key"]: r for r in rows}
        weights = ", ".join(map(str, self.weights))
        with self._lock:
            db = self._connect()
            ranked = db.execute(
                f"SELECT s.id, s.key, bm25(fts, {weights}) AS rank FROM fts "
                "JOIN stamps s ON s.id = fts.rowid WHERE fts MATCH ? ORDER BY rank",
                (match,),
            ).fetchall()
            # only the rows asked about (not the bin's, not another store's), capped
            kept = [(i, k, rank) for i, k, rank in ranked if k in by_key]
            kept = kept[: self.max_results]
            body = _COLUMNS.index("body")
            snips = {}
            wanted = kept[: self.snippet_rows]
            for at in range(0, len(wanted), SQL_VARS):
                ids = [i for i, _, _ in wanted[at : at + SQL_VARS]]
                snips.update(
                    db.execute(
                        f"SELECT rowid, snippet(fts, {body}, '', '', '…', "
                        f"{int(self.snippet_tokens)}) FROM fts WHERE fts MATCH ? "
                        f"AND rowid IN ({', '.join('?' * len(ids))})",
                        (match, *ids),
                    ).fetchall()
                )
        out = []
        for rowid, key, rank in kept:
            row = by_key[key]
            row["score"] = round(-rank, 6)  # bm25 is lower-is-better; a score is not
            snip = snips.get(rowid)
            if snip:
                row["snippet"] = re.sub(r"\s+", " ", snip).strip()
            out.append(row)
        return out


def default_search(data_root: Path | None) -> SearchStrategy:
    """The index under ``data_root`` when it is on this machine, else the scan."""
    if data_root is None:
        return scan_search
    return IndexedSearch(Path(data_root) / INDEX_REL)
