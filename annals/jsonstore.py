"""A ``MutableMapping`` kept in one JSON file, safe with several server processes.

The owner's tags (:mod:`annals.tags`) and each reader's listening progress
(:mod:`annals.listening`) are small, server-side records that the page changes one entry at
a time. :class:`JsonFileStore` is that one mechanism: a JSON object in a file, written
atomically under an exclusive ``flock``, re-read whenever another process changed it, and
never broken by a damaged file (it reads as empty and is kept aside at the next write).

A subclass says what a valid value is (:meth:`JsonFileStore.valid`) and how a value is
cleaned before it is stored (:meth:`JsonFileStore.clean`). :meth:`JsonFileStore.update`
changes one entry from its current value under the lock, so two devices reporting at once
never lose each other's change.

>>> import tempfile, pathlib
>>> s = JsonFileStore(pathlib.Path(tempfile.mkdtemp()) / "x.json")
>>> s["a"] = {"n": 1}
>>> s.update("a", lambda v: {"n": (v or {}).get("n", 0) + 1})
{'n': 2}
>>> dict(s)
{'a': {'n': 2}}
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable, Iterator, MutableMapping
from pathlib import Path
from typing import Any

try:  # POSIX: writers in several processes (a server's workers) take turns
    import fcntl
except ImportError:  # pragma: no cover - Windows: one process, the thread lock suffices
    fcntl = None

log = logging.getLogger(__name__)

#: the suffix a damaged file is kept under, so a hand edit gone wrong can be recovered
DAMAGED_SUFFIX = ".damaged"


class JsonFileStore(MutableMapping):
    """``{key: value}`` in one JSON file, re-read when another process changed it.

    A write takes an exclusive ``flock`` on ``<file>.lock``, re-reads the file, changes it
    and replaces it atomically. A read re-reads the file whenever its inode, size or mtime
    changed (every write makes a new inode). ``label`` names the store in log messages.
    """

    label = "annals store"

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()
        self._data: dict[str, Any] = {}
        self._stamp: tuple | None = None
        self._damaged = False
        self._lock = threading.Lock()

    # -- what a subclass decides ----------------------------------------------------
    def valid(self, value: Any) -> bool:
        """Whether a value read from the file is kept (an invalid one is logged and skipped)."""
        return True

    def clean(self, value: Any) -> Any:
        """The value as stored; raise ``ValueError`` to refuse it."""
        return value

    # -- the mechanism --------------------------------------------------------------
    @contextlib.contextmanager
    def _writing(self):
        """The thread lock, plus an exclusive lock other processes respect."""
        with self._lock:
            if fcntl is None:
                yield
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path.with_name(self.path.name + ".lock"), "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _load(self, *, force: bool = False) -> dict[str, Any]:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            self._data, self._stamp = {}, None
            return self._data
        stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
        if force or stamp != self._stamp:
            self._data = self._parse(
                self.path.read_text(encoding="utf-8", errors="replace")
            )
            self._stamp = stamp
        return self._data

    def _parse(self, text: str) -> dict[str, Any]:
        """The file's entries; a damaged file or entry is logged and skipped, never fatal."""
        self._damaged = False
        try:
            data = json.loads(text or "{}")
        except json.JSONDecodeError as e:
            log.warning(
                "%s: %s is not valid JSON (%s); reading it as empty",
                self.label,
                self.path,
                e,
            )
            self._damaged = True
            return {}
        if not isinstance(data, dict):
            log.warning(
                "%s: %s is not a JSON object; reading it as empty",
                self.label,
                self.path,
            )
            self._damaged = True
            return {}
        out = {}
        for k, v in data.items():
            if self.valid(v):
                out[str(k)] = v
            else:
                log.warning(
                    "%s: skipping %r in %s: not a valid entry", self.label, k, self.path
                )
        return out

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._damaged and self.path.exists():
            os.replace(self.path, self.path.with_name(self.path.name + DAMAGED_SUFFIX))
            self._damaged = False
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, sort_keys=True, ensure_ascii=False)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        st = self.path.stat()
        self._data, self._stamp = data, (st.st_ino, st.st_mtime_ns, st.st_size)

    def update(self, key: str, change: Callable[[Any], Any]) -> Any:
        """Set ``key`` to ``change(current value or None)``, atomically; returns the stored value.

        ``change`` returning ``None`` deletes the entry (and returns ``None``).
        """
        with self._writing():
            data = dict(self._load(force=True))
            new = change(_copy(data.get(key)))
            if new is None:
                if key not in data:
                    return None
                del data[key]
            else:
                data[key] = new = self.clean(new)
            self._save(data)
            return _copy(new)

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return _copy(self._load()[key])

    def __setitem__(self, key: str, value: Any) -> None:
        value = self.clean(value)
        with self._writing():
            data = dict(self._load(force=True))
            data[key] = value
            self._save(data)

    def __delitem__(self, key: str) -> None:
        with self._writing():
            data = dict(self._load(force=True))
            del data[key]
            self._save(data)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(list(self._load()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._load())

    def snapshot(self) -> dict[str, Any]:
        """Every entry at once, under one read (what a listing overlays)."""
        with self._lock:
            return {k: _copy(v) for k, v in self._load().items()}


def _copy(value: Any) -> Any:
    """A copy a caller may change without changing the store's cache."""
    return json.loads(json.dumps(value)) if isinstance(value, (dict, list)) else value
