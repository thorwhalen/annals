"""Each reader's highlights: passages of documents kept with a name, tags and a note.

A reader selects text on a document's page and keeps it. The page side is the
`manicules <https://github.com/thorwhalen/manicules>`_ widget (vendored under
``ui/vendor/manicules/``); this module is the server side it talks to: what a highlight is
allowed to be, where each reader's are kept, and how they are searched. A highlight of a
document's whole title keeps the document itself, which is how a reader marks a favourite.

A highlight, as stored (the shape of manicules' ``highlight.schema.json``)::

    {"id": "hmf3k2x9a1b2c3", "name": "Bread notes-highlight-1",
     "target": {"source": {"id": "<doc id>", "title": "Bread notes", "url": "d/<doc id>"},
                "part": "body",
                "quote": {"exact": "85 percent water", "prefix": "A rye loaf takes ", "suffix": ", and"},
                "position": {"start": 310, "end": 327}},
     "comment": "the number I keep forgetting", "tags": ["rye"], "color": "green",
     "created": "2026-11-27T10:00:00+00:00"}

The target is two W3C Web Annotation selectors (the quote with its context, and where it
was): the page finds the passage again from them after the document changed. ``whole`` in a
target means the entire part, whatever it says now. The server never interprets a target;
it bounds its size and keeps it.

Records live under the data root, one JSON file per reader
(``highlights/<reader>.json``, ``{id: highlight}``, the layout manicules' own file store and
CLI use), through :class:`annals.jsonstore.JsonFileStore`; each reader's two settings (the
default colour, and whether a page shows all its highlights when it opens) are beside them
(``highlight-settings/<reader>.json``). :func:`for_reader` is the seam: any
``(reader) -> ReaderHighlights`` callable can replace it (``mk_api(highlights=...)``), its
records being anything with the three calls of :class:`Records`. The routes the widget
talks to are :func:`annals.highlights_api.mk_router`.

>>> rec = clean({"target": {"source": {"id": "d1", "title": "Notes"}, "quote": {"exact": "three sites"}}},
...             names=["Notes-highlight-1"], now="2026-11-27T10:00:00+00:00", new_id=lambda: "h1")
>>> rec["name"], rec["target"]["part"], rec["tags"], rec["comment"]
('Notes-highlight-2', 'body', [], '')
>>> [h["id"] for h in search({"h1": rec}, "SITES notes")]
['h1']
>>> search({"h1": rec}, "sites absent")
[]
>>> clean_patch({"comment": "why", "color": None, "tags": ["b", "A", "a"]})
{'comment': 'why', 'color': None, 'tags': ['A', 'b']}
"""

# extraction candidate: the Python side of manicules (a store, validation and search for a
# FastAPI host), once a second host needs it. Of the rest of annals this imports only the
# JSON file store, the tag rules and the reader's file name.

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from annals.jsonstore import JsonFileStore
from annals.listening import reader_file
from annals.tags import normalize_tags

FOLDER = "highlights"
#: the reader an agent surface (the CLI, the MCP server) answers for when none is named
ENV_READER = "ANNALS_HIGHLIGHTS_READER"
SETTINGS_FOLDER = "highlight-settings"
#: the colours a highlight may have (manicules' palette; each is legible in light and dark)
PALETTE = ("yellow", "green", "blue", "pink", "orange", "purple")
#: what a reader gets before choosing anything
DEFAULT_SETTINGS = {"color": "yellow", "showOthers": True}
DEFAULT_PART = "body"
MAX_NAME_LEN = 200
MAX_COMMENT_LEN = 10_000
MAX_EXACT_LEN = 20_000
MAX_CONTEXT_LEN = 600
MAX_SOURCE_ID_LEN = 500
MAX_TITLE_LEN = 500
MAX_URL_LEN = 2000
MAX_PART_LEN = 64
MAX_ID_LEN = 64
#: at most this many highlights per reader: the file is read whole on every page
MAX_HIGHLIGHTS = 5000
#: and their file at most this big: every list, search and page view reads it whole
MAX_STORE_BYTES = 20_000_000
_NAME_SUFFIX = "-highlight-"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,%d}$" % MAX_ID_LEN)
_PART_RE = re.compile(r"^[A-Za-z0-9_-]{1,%d}$" % MAX_PART_LEN)
#: ids the API's own routes use (``/highlights/settings``)
RESERVED_IDS = frozenset({"settings"})
#: the fields a reader may change afterwards; the target never changes
PATCHABLE = ("name", "comment", "tags", "color")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    """A new id: sortable by creation time, unique enough for one reader's collection."""
    return "h" + _base36(int(time.time() * 1000)) + secrets.token_hex(3)


def _base36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out or "0"


def default_name(title: str, names: Iterable[str] = ()) -> str:
    """``<title>-highlight-<n>``, ``n`` the first number no highlight of that page uses.

    >>> default_name("Notes", ["a", "Notes-highlight-3"])
    'Notes-highlight-4'
    >>> default_name("  ")
    'page-highlight-1'
    """
    names = list(names)
    stem = (title.strip() or "page")[: MAX_NAME_LEN - len(_NAME_SUFFIX) - 6]
    stem += _NAME_SUFFIX
    n = len(names) + 1
    while f"{stem}{n}" in names:
        n += 1
    return f"{stem}{n}"


def _text(
    value: Any,
    *,
    what: str,
    max_len: int,
    required: bool = False,
    strip: bool = True,
    verbatim: bool = False,
) -> str:
    """A text field, bounded. ``verbatim`` is text taken from a document as it is (a passage,
    its context): it may hold any character a document holds, an escape code of a log
    included; a field a person types (a name, an id) may not hold control characters. Half of
    a character (a lone surrogate, which a cut by length can leave) is refused everywhere: it
    cannot be written to the file."""
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what} is text, not {type(value).__name__}")
    if strip:
        value = value.strip()
    if required and not value:
        raise ValueError(f"{what} is required")
    if len(value) > max_len:
        raise ValueError(f"{what} is longer than {max_len} characters")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError(f"{what} holds half of a character (a lone surrogate)")
    if not verbatim and any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError(f"{what} holds a control character")
    return value


#: a page's address under the page's base: a relative path with its query, nothing a browser
#: could read as a scheme, a host or an escape
_URL_RE = re.compile(r"^[A-Za-z0-9_~.%!$&'()*+,;=:@/?-]+$")


def _page_url(value: Any) -> str:
    """``source.url`` as stored: relative to the page's base, or refused.

    >>> _page_url("d/20261127-notes-a1b2?f=a.md")
    'd/20261127-notes-a1b2?f=a.md'
    >>> for bad in ("javascript:alert(1)", "java\\tscript:alert(1)", "//evil.example/x", "/etc", "https://x.example"):
    ...     try: _page_url(bad)
    ...     except ValueError: print("refused")
    refused
    refused
    refused
    refused
    refused
    """
    url = _text(value, what="source url", max_len=MAX_URL_LEN)
    if not url:
        return ""
    first = url.split("/", 1)[0].split("?", 1)[0]
    if not _URL_RE.match(url) or url.startswith("/") or ":" in first:
        raise ValueError("source url is a page's address relative to this site")
    return url


def href(record: Mapping) -> str:
    """A highlight's page, opened on it, relative to the page's base (``""`` when it names none).

    The one place that address is built: the API's ``href``, the CLI's ``url`` and the page
    all come from here.

    >>> href({"id": "h1", "target": {"source": {"id": "d1", "url": "d/d1?f=a.md"}}})
    'd/d1?f=a.md&h=h1'
    """
    url = str(((record.get("target") or {}).get("source") or {}).get("url") or "")
    if not url:
        return ""
    return f"{url}{'&' if '?' in url else '?'}h={quote(str(record.get('id', '')), safe='')}"


def _colour(value: Any) -> str | None:
    if value is None:
        return None
    if value not in PALETTE:
        raise ValueError(
            f"color is one of {', '.join(PALETTE)}, or null for the default"
        )
    return value


def _offset(value: Any, *, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{what} is a whole number, 0 or more")
    return value


def clean_target(target: Any) -> dict:
    """A target as stored: its source, its part, and the selectors, each bounded.

    Raises ``ValueError`` for a target with no source id, with neither a quote nor
    ``whole``, or with a field of the wrong kind or size.
    """
    if not isinstance(target, Mapping):
        raise ValueError("a highlight needs a target")
    source = target.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("a target names its source (the page)")
    out_source = {
        "id": _text(
            source.get("id"), what="source id", max_len=MAX_SOURCE_ID_LEN, required=True
        )
    }
    title = _text(source.get("title"), what="source title", max_len=MAX_TITLE_LEN)
    if title:
        out_source["title"] = title
    url = _page_url(source.get("url"))
    if url:
        out_source["url"] = url
    part = target.get("part") or DEFAULT_PART
    if not isinstance(part, str) or not _PART_RE.match(part):
        raise ValueError("part is a short name (letters, digits, - and _)")
    out: dict = {"source": out_source, "part": part}
    quote = target.get("quote")
    if quote is not None:
        if not isinstance(quote, Mapping):
            raise ValueError("quote is an object with the passage in `exact`")
        out_quote = {
            "exact": _text(
                quote.get("exact"),
                what="the passage",
                max_len=MAX_EXACT_LEN,
                required=True,
                strip=False,
                verbatim=True,
            )
        }
        for key in ("prefix", "suffix"):
            text = _text(
                quote.get(key),
                what=key,
                max_len=MAX_CONTEXT_LEN,
                strip=False,
                verbatim=True,
            )
            if text:
                out_quote[key] = text
        out["quote"] = out_quote
    position = target.get("position")
    if position is not None:
        if not isinstance(position, Mapping):
            raise ValueError("position is an object with `start` and `end`")
        start = _offset(position.get("start"), what="position start")
        end = _offset(position.get("end"), what="position end")
        if end < start:
            raise ValueError("position ends before it starts")
        out["position"] = {"start": start, "end": end}
    if target.get("whole") is True:
        out["whole"] = True
    if "quote" not in out and "whole" not in out:
        raise ValueError("a target has a quote, or is the whole part")
    return out


def clean_patch(patch: Any) -> dict:
    """What a reader may change (:data:`PATCHABLE`), validated; anything else is refused."""
    if not isinstance(patch, Mapping):
        raise ValueError("send the fields to change as an object")
    extra = set(patch) - set(PATCHABLE)
    if extra:
        raise ValueError(
            f"only {', '.join(PATCHABLE)} can be changed, not {', '.join(sorted(extra))}"
        )
    out: dict = {}
    if "name" in patch:
        out["name"] = _text(
            patch["name"], what="name", max_len=MAX_NAME_LEN, required=True
        )
    if "comment" in patch:
        out["comment"] = _text(
            patch["comment"], what="comment", max_len=MAX_COMMENT_LEN, strip=False
        )
    if "color" in patch:
        out["color"] = _colour(patch["color"])
    if "tags" in patch:
        if not isinstance(patch["tags"], list):
            raise ValueError("tags is a list of strings")
        out["tags"] = normalize_tags(patch["tags"])
    return out


def clean(
    data: Any,
    *,
    names: Iterable[str] = (),
    now: str | None = None,
    new_id: Callable[[], str] = new_id,
) -> dict:
    """A complete highlight from what a caller sent, validated and bounded.

    ``names`` are the names of the page's other highlights, for the default name. An ``id``
    or ``created`` the caller sent is kept when well formed (the page makes the id, so an
    undo puts back the very same highlight); unknown fields are dropped.
    """
    if not isinstance(data, Mapping):
        raise ValueError("a highlight is an object")
    target = clean_target(data.get("target"))
    hid = data.get("id")
    if hid is None:
        hid = new_id()
    elif not isinstance(hid, str) or not _ID_RE.match(hid) or hid in RESERVED_IDS:
        raise ValueError(
            "id is 1 to 64 letters, digits, - or _ (and not a reserved word)"
        )
    fields = clean_patch({k: data[k] for k in PATCHABLE if data.get(k) is not None})
    created = data.get("created")
    if created is not None:
        created = _text(created, what="created", max_len=40, required=True)
        try:
            datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("created is an ISO date and time") from None
    record = {
        "id": hid,
        "name": fields.get("name")
        or default_name(target["source"].get("title") or target["source"]["id"], names),
        "target": target,
        "comment": fields.get("comment", ""),
        "tags": fields.get("tags", []),
        "created": created or now or _now(),
    }
    if fields.get("color"):
        record["color"] = fields["color"]
    return record


def apply_patch(record: dict, patch: Mapping, *, now: str | None = None) -> dict:
    """``record`` with a cleaned patch applied; a ``None`` colour goes back to the default."""
    out = {**record, **patch, "modified": now or _now()}
    if out.get("color") is None:
        out.pop("color", None)
    return out


def clean_settings(patch: Any) -> dict:
    """The settings a reader may set, validated: ``color`` and ``showOthers``."""
    if not isinstance(patch, Mapping):
        raise ValueError("send the settings to change as an object")
    extra = set(patch) - set(DEFAULT_SETTINGS)
    if extra:
        raise ValueError(f"no such setting: {', '.join(sorted(extra))}")
    out: dict = {}
    if "color" in patch:
        colour = _colour(patch["color"])
        if colour is None:
            raise ValueError(f"color is one of {', '.join(PALETTE)}")
        out["color"] = colour
    if "showOthers" in patch:
        if not isinstance(patch["showOthers"], bool):
            raise ValueError("showOthers is true or false")
        out["showOthers"] = patch["showOthers"]
    return out


def readers(target) -> list[str]:
    """Who has highlights under a data root, read through its ``Target`` (so over ssh too)."""
    from urllib.parse import unquote

    return sorted(
        unquote(name[: -len(".json")])
        for name in target.list_files(FOLDER)
        if name.endswith(".json") and not name.startswith(".")
    )


def read_records(target, reader: str) -> dict[str, dict]:
    """One reader's highlights by id, read through a ``Target`` (a local folder, or over
    ssh): for a caller that only reads. The one other place that knows the file layout is
    :func:`for_reader`."""
    import json

    rel = f"{FOLDER}/{reader_file(reader)}"
    if not target.exists(rel):
        return {}
    records = json.loads(target.read_text(rel) or "{}")
    if not isinstance(records, dict):
        return {}
    return {k: v for k, v in records.items() if isinstance(v, dict)}


def search_text(record: Mapping) -> str:
    """What a highlight is found by: its name, passage, note, tags and its page's title."""
    target = record.get("target") or {}
    return "\n".join(
        [
            str(record.get("name") or ""),
            str((target.get("quote") or {}).get("exact") or ""),
            str(record.get("comment") or ""),
            " ".join(record.get("tags") or []),
            str((target.get("source") or {}).get("title") or ""),
        ]
    ).lower()


def search(
    records: Mapping[str, dict],
    q: str = "",
    *,
    source: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    """The highlights matching every word of ``q`` (case ignored), newest first.

    ``source`` keeps one page's (its source id), ``tag`` the ones carrying a tag. This is
    the function a wider search calls to list a reader's highlights beside documents.
    """
    words = q.lower().split()
    tag = tag.lower() if tag else None

    def wanted(r: dict) -> bool:
        if source and (r.get("target") or {}).get("source", {}).get("id") != source:
            return False
        if tag and not any(t.lower() == tag for t in r.get("tags") or []):
            return False
        if not words:
            return True
        text = search_text(r)
        return all(w in text for w in words)

    found = [r for r in records.values() if wanted(r)]
    return sorted(found, key=lambda r: str(r.get("created") or ""), reverse=True)


class Records(Protocol):
    """One reader's highlights, as this module and the API use them: any store with these
    three calls can stand behind the seam (a table in a database as well as a file)."""

    def get(self, key: str, default: Any = None) -> Any: ...

    def modify(self, key: str, change: Callable[[Any], Any]) -> Any:
        """Set ``key`` to ``change(current or None)`` atomically (``None`` deletes it)."""
        ...

    def snapshot(self) -> dict[str, Any]: ...


class HighlightStore(JsonFileStore):
    """One reader's highlights: ``{id: highlight}`` in one JSON file."""

    label = "annals highlights"

    def valid(self, value) -> bool:
        return isinstance(value, dict) and isinstance(value.get("target"), dict)

    def has_room(self) -> bool:
        """Whether another highlight may be added: the file is read whole on every page,
        so it is bounded in bytes (:data:`MAX_STORE_BYTES`) as well as in number."""
        try:
            return self.path.stat().st_size <= MAX_STORE_BYTES
        except FileNotFoundError:
            return True


class SettingsStore(JsonFileStore):
    """One reader's settings: ``{setting: value}`` in one JSON file."""

    label = "annals highlight settings"

    def valid(self, value) -> bool:
        return isinstance(value, (str, bool))


@dataclass(frozen=True)
class ReaderHighlights:
    """What the API keeps for one reader: the highlights (:class:`Records`), and the
    settings beside them (a mapping of setting name to value, with ``snapshot()``)."""

    records: Records
    settings: Any


ForReader = Callable[[str], ReaderHighlights]


def for_reader(root: Path | str) -> ForReader:
    """The default seam: ``<root>/highlights/<reader>.json`` and ``highlight-settings/``."""
    root = Path(root)
    cache: dict[str, ReaderHighlights] = {}

    def get(reader: str) -> ReaderHighlights:
        name = reader_file(reader)
        if name not in cache:
            cache[name] = ReaderHighlights(
                HighlightStore(root / FOLDER / name),
                SettingsStore(root / SETTINGS_FOLDER / name),
            )
        return cache[name]

    return get


def settings_of(store: Mapping[str, Any]) -> dict:
    """A reader's settings over the defaults (a stored value of the wrong kind is ignored)."""
    out = dict(DEFAULT_SETTINGS)
    try:
        out.update(
            clean_settings({k: store[k] for k in DEFAULT_SETTINGS if k in store})
        )
    except ValueError:
        pass
    return out


def add(records: Records, data: Any) -> dict:
    """Keep a new highlight. Raises ``ValueError`` when it is invalid, when its id is taken,
    or when the reader already has :data:`MAX_HIGHLIGHTS`."""
    existing = records.snapshot()
    if len(existing) >= MAX_HIGHLIGHTS:
        raise ValueError(f"at most {MAX_HIGHLIGHTS} highlights are kept")
    has_room = getattr(records, "has_room", None)  # a store that is bounded says so
    if has_room is not None and not has_room():
        raise ValueError("these highlights take too much room: remove some first")
    source = clean_target(
        (data or {}).get("target") if isinstance(data, Mapping) else None
    )
    names = [
        r.get("name", "")
        for r in existing.values()
        if (r.get("target") or {}).get("source", {}).get("id") == source["source"]["id"]
    ]
    record = clean(data, names=names)

    def create(current):
        if current is not None:
            raise ValueError(f"a highlight with id {record['id']} already exists")
        return record

    return records.modify(record["id"], create)


def edit(records: Records, hid: str, patch: Any) -> dict:
    """Change a highlight's name, note, tags or colour. ``KeyError`` when there is none."""
    cleaned = clean_patch(patch)

    def change(current):
        if current is None:
            raise KeyError(hid)
        return apply_patch(current, cleaned)

    return records.modify(hid, change)


def remove(records: Records, hid: str) -> dict:
    """Delete a highlight and return it. ``KeyError`` when there is none."""
    gone: dict = {}

    def drop(current):
        if current is None:
            raise KeyError(hid)
        gone.update(current)
        return None

    records.modify(hid, drop)
    return gone
