"""What each reader has heard of each audio document: percent heard, listens, where they stopped.

The page reports what was played, a few seconds at a time, as spans of the audio's own
timeline (``[[start, end], ...]`` in seconds). The server keeps the **union** of those spans
per reader and document, so the percent heard counts each second once, however often it was
replayed or skipped back to, and two devices reporting the same minute add nothing twice.
A listen is counted when playback reaches the end of audio that has been heard almost
whole (:data:`DONE_SHARE`), so dragging to the end is not a listen; a report carries the
id of the play it belongs to, so a report sent twice (a retry, a page closing) counts one.

A record, per reader and document::

    {"heard": [[0.0, 61.5], [90.0, 120.0]], "duration": 300.0, "position": 120.0,
     "listens": 1, "done": true, "updated": "2026-11-09T10:00:00+00:00"}

``done`` is the reader's own mark ("I have heard this"), set or cleared from the page; it
is absent until they set it. :func:`status` reads a record as one of :data:`STATUSES`.

Records live under the data root, one JSON file per reader (``listening/<reader>.json``),
through :class:`annals.jsonstore.JsonFileStore`. :func:`for_reader` is the seam: any
``(reader) -> store`` callable whose stores are :class:`Records` can replace it
(``mk_api(listening=...)``).

>>> merge_spans([[5, 10], [0, 3], [2, 6], [20, 20]])
[[0.0, 10.0]]
>>> rec = apply_report(None, {"spans": [[0, 30]], "duration": 100, "position": 30})
>>> percent(rec), status(rec)
(30, 'started')
>>> apply_report(None, {"spans": [[95, 100]], "duration": 100, "ended": "p0"})["listens"]  # dragged to the end
0
>>> rec = apply_report(rec, {"spans": [[30, 100]], "duration": 100, "position": 100, "ended": "p1"})
>>> rec = apply_report(rec, {"spans": [], "duration": 100, "position": 100, "ended": "p1"})
>>> percent(rec), rec["listens"], status(rec)
(100, 1, 'done')
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from annals.jsonstore import JsonFileStore

FOLDER = "listening"
NOT_STARTED, STARTED, DONE = "not_started", "started", "done"
#: what a record reads as, in the order the page offers them as filters
STATUSES = (NOT_STARTED, STARTED, DONE)
#: heard at least this share of the audio counts as done, without a listen to the end
DONE_SHARE = 0.95
#: heard less than this many seconds is not started (a stray tap on play)
MIN_STARTED_S = 3.0
#: at most this many separate spans are kept; past it the closest ones are joined
MAX_SPANS = 200
#: a report holds at most this many spans
MAX_REPORT_SPANS = 500
#: longest audio a report may claim, in seconds (a sanity bound, not a feature limit)
MAX_DURATION_S = 24 * 3600
MAX_PLAY_ID_LEN = 64
#: the plays that reached the end, remembered so a retried report counts none twice
RECENT_PLAYS = 20
MAX_READER_LEN = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seconds(x: Any, *, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(f"{what} is a number of seconds, not {x!r}")
    if x < 0 or x > MAX_DURATION_S:
        raise ValueError(f"{what} out of range: {x!r}")
    return float(x)


def merge_spans(spans: Iterable[Iterable[float]], *, max_spans: int = MAX_SPANS) -> list[list[float]]:
    """The union of ``spans`` as sorted, disjoint ``[start, end]`` pairs; empty spans dropped.

    Past ``max_spans`` pairs, the ones with the smallest gap between them are joined, so a
    record stays small whatever a reader does (the percent heard can only grow by that).
    """
    pairs = sorted(
        (min(a, b), max(a, b)) for a, b in ((float(s[0]), float(s[1])) for s in spans)
    )
    out: list[list[float]] = []
    for a, b in pairs:
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    while len(out) > max_spans:
        i = min(range(len(out) - 1), key=lambda j: out[j + 1][0] - out[j][1])
        out[i][1] = out.pop(i + 1)[1]
    return [[round(a, 2), round(b, 2)] for a, b in out]


def heard_seconds(record: dict | None) -> float:
    """How many distinct seconds of the audio were heard."""
    return sum(b - a for a, b in (record or {}).get("heard", []))


def percent(record: dict | None) -> int:
    """The share of the audio heard, 0 to 100 (0 while the duration is unknown)."""
    d = (record or {}).get("duration") or 0
    if d <= 0:
        return 0
    return min(100, int(round(100 * heard_seconds(record) / d)))


def status(record: dict | None) -> str:
    """``done``, ``started`` or ``not_started``; the reader's own mark wins when set."""
    if not record:
        return NOT_STARTED
    mark = record.get("done")
    if mark is not None:
        return DONE if mark else (STARTED if heard_seconds(record) >= MIN_STARTED_S else NOT_STARTED)
    d = record.get("duration") or 0
    if record.get("listens", 0) > 0 or (d > 0 and heard_seconds(record) >= DONE_SHARE * d):
        return DONE
    return STARTED if heard_seconds(record) >= MIN_STARTED_S else NOT_STARTED


def summary(record: dict | None) -> dict:
    """A record as the page shows it: the record plus ``percent`` and ``status``."""
    out = {"heard": [], "duration": None, "position": 0.0, "listens": 0}
    out.update(record or {})
    out.pop("recent_plays", None)
    out["percent"] = percent(record)
    out["status"] = status(record)
    return out


def apply_report(record: dict | None, report: dict) -> dict:
    """``record`` with a report from the page folded in. Raises ``ValueError`` on a bad report.

    A report: ``{"spans": [[a, b], ...], "duration": s, "position": s, "ended"?: play_id}``.
    ``ended`` names the play that reached the end; each play id counts one listen.
    """
    if not isinstance(report, dict):
        raise ValueError("a report is a JSON object")
    extra = set(report) - {"spans", "duration", "position", "ended"}
    if extra:
        raise ValueError(f"unknown fields in a report: {sorted(extra)}")
    spans = report.get("spans", [])
    if not isinstance(spans, list) or len(spans) > MAX_REPORT_SPANS:
        raise ValueError(f"spans is a list of at most {MAX_REPORT_SPANS} [start, end] pairs")
    clean = []
    for s in spans:
        if not isinstance(s, (list, tuple)) or len(s) != 2:
            raise ValueError("a span is a [start, end] pair")
        clean.append((_seconds(s[0], what="a span"), _seconds(s[1], what="a span")))
    rec = dict(record or {})
    if report.get("duration") is not None:
        rec["duration"] = round(_seconds(report["duration"], what="duration"), 2)
    d = rec.get("duration")
    if d:
        clean = [(min(a, d), min(b, d)) for a, b in clean]
    rec["heard"] = merge_spans(list(rec.get("heard", [])) + clean)
    if report.get("position") is not None:
        rec["position"] = round(_seconds(report["position"], what="position"), 2)
    ended = report.get("ended")
    if ended is not None:
        if not isinstance(ended, str) or not 0 < len(ended) <= MAX_PLAY_ID_LEN:
            raise ValueError("ended is the id of the play that reached the end")
        recent = [p for p in rec.get("recent_plays", []) if isinstance(p, str)]
        whole = d and heard_seconds(rec) >= DONE_SHARE * d
        if whole and ended not in recent:
            rec["listens"] = int(rec.get("listens", 0)) + 1
            rec["recent_plays"] = (recent + [ended])[-RECENT_PLAYS:]
    rec.setdefault("listens", 0)
    rec["updated"] = _now()
    return rec


def apply_mark(record: dict | None, done: bool | None) -> dict | None:
    """``record`` with the reader's own mark set (``True``/``False``) or cleared (``None``)."""
    if done is not None and not isinstance(done, bool):
        raise ValueError("done is true, false or null")
    rec = dict(record or {})
    if done is None:
        rec.pop("done", None)
    else:
        rec["done"] = done
    rec.setdefault("heard", [])
    rec.setdefault("listens", 0)
    rec["updated"] = _now()
    return rec


class ListeningStore(JsonFileStore):
    """One reader's records: ``{doc id: record}`` in one JSON file."""

    label = "annals listening"

    def valid(self, value) -> bool:
        return isinstance(value, dict) and isinstance(value.get("heard", []), list)


def reader_file(reader: str) -> str:
    """The file name a reader's records are kept under: their identity, percent-encoded.

    The encoding is one-to-one, so two readers never share a file, and never a path.
    """
    who = reader.strip().lower()
    if not who or len(who) > MAX_READER_LEN:
        raise ValueError(f"a reader is 1 to {MAX_READER_LEN} characters")
    name = quote(who, safe="@+")
    if name.startswith("."):
        name = "%2E" + name[1:]
    return name + ".json"


class Records(Protocol):
    """One reader's records, as the API uses them."""

    def get(self, key: str, default: Any = None) -> Any: ...

    def modify(self, key: str, change: Callable[[Any], Any]) -> Any:
        """Set ``key`` to ``change(current or None)`` atomically (``None`` deletes it)."""
        ...

    def snapshot(self) -> dict[str, Any]: ...


ForReader = Callable[[str], Records]


def for_reader(root: Path | str) -> ForReader:
    """The default seam: each reader's records in ``<root>/listening/<reader>.json``."""
    folder = Path(root) / FOLDER
    cache: dict[str, ListeningStore] = {}

    def get(reader: str) -> ListeningStore:
        name = reader_file(reader)
        if name not in cache:
            cache[name] = ListeningStore(folder / name)
        return cache[name]

    return get
