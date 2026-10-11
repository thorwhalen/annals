"""The owner's tags: a ``MutableMapping`` from item key to tag list, kept apart from the items.

Tags the owner adds on the page are stored here, never in the items themselves: a folder
source belongs to whoever writes it (a crowsnest ledger belongs to its session), so annals
must not edit it, and a published document's ``meta.json`` is the publisher's record.
An entry, once present, is the item's whole tag list (it replaces the item's own tags, so
removing a tag the publisher set works too); deleting the entry falls back to them.

:class:`JsonTagStore`, the default, is one JSON file under the data root
(``<data root>/tags/tags.json``), written atomically. Any ``MutableMapping[str, list[str]]``
can replace it (``mk_api(tags=...)``), e.g. a table in a database.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from collections.abc import Iterable, Iterator, MutableMapping
from pathlib import Path

TAGS_DIR = "tags"
TAGS_FILE = "tags.json"
MAX_TAG_LEN = 64
MAX_TAGS_PER_ITEM = 50


def normalize_tags(tags: Iterable[str]) -> list[str]:
    """Trimmed, single-spaced, de-duplicated (ignoring case), sorted; refuses junk.

    Raises ``ValueError`` for a tag that is not a string, is longer than ``MAX_TAG_LEN``,
    holds control characters, or for more than ``MAX_TAGS_PER_ITEM`` tags.
    """
    out: dict[str, str] = {}
    for t in tags:
        if not isinstance(t, str):
            raise ValueError(f"a tag is a string, not {type(t).__name__}")
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        if len(t) > MAX_TAG_LEN:
            raise ValueError(f"tag longer than {MAX_TAG_LEN} characters: {t[:20]!r}…")
        if any(ord(c) < 32 for c in t):
            raise ValueError(f"tag holds a control character: {t!r}")
        out.setdefault(t.lower(), t)
    if len(out) > MAX_TAGS_PER_ITEM:
        raise ValueError(f"at most {MAX_TAGS_PER_ITEM} tags per item")
    return sorted(out.values(), key=str.lower)


class JsonTagStore(MutableMapping):
    """``{item key: [tags]}`` in one JSON file, re-read when another process changed it."""

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()
        self._data: dict[str, list[str]] = {}
        self._stamp: tuple | None = None
        self._lock = threading.Lock()

    def _load(self) -> dict[str, list[str]]:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            self._data, self._stamp = {}, None
            return self._data
        stamp = (st.st_mtime_ns, st.st_size)
        if stamp != self._stamp:
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            self._data = {str(k): list(v) for k, v in data.items()}
            self._stamp = stamp
        return self._data

    def _save(self, data: dict[str, list[str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, sort_keys=True, ensure_ascii=False)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        st = self.path.stat()
        self._data, self._stamp = data, (st.st_mtime_ns, st.st_size)

    def __getitem__(self, key: str) -> list[str]:
        with self._lock:
            return list(self._load()[key])

    def __setitem__(self, key: str, tags: Iterable[str]) -> None:
        with self._lock:
            data = dict(self._load())
            data[key] = normalize_tags(tags)
            self._save(data)

    def __delitem__(self, key: str) -> None:
        with self._lock:
            data = dict(self._load())
            del data[key]
            self._save(data)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(list(self._load()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._load())

    def snapshot(self) -> dict[str, list[str]]:
        """Every entry at once, under one read (what a listing overlays)."""
        with self._lock:
            return {k: list(v) for k, v in self._load().items()}
