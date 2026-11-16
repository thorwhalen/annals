"""Exact filters over a document's meta, for a caller that polls: since, session, tag, source.

One place for the rules, so the CLI (``annals ls``), MCP and the HTTP ``/docs`` route cannot
drift: ``since`` is an ISO date or time (local time unless it has an offset) or an age
(``6h``, ``2d``); ``session``, ``tag`` and each ``source`` key match whole values, never
substrings; all given filters must hold. They are pure: the caller lists the documents (and
puts the owner's tags in, :func:`annals.catalog.with_owner_tags`) and this narrows them.

>>> docs = [{"id": "a", "tags": ["x"], "created": "2026-11-12T10:00:00+00:00", "source": {"session": "s1"}},
...         {"id": "b", "tags": ["y"], "created": "2026-11-10T10:00:00+00:00", "source": {"session": "s2"}}]
>>> [d["id"] for d in DocFilter.of(since="2026-11-11T00:00:00+00:00").apply(docs)]
['a']
>>> [d["id"] for d in DocFilter.of(session="s2", tag="y").apply(docs)]
['b']
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

#: provenance annals fills in itself; ``--meta`` cannot overwrite it
RESERVED_META = frozenset({"host", "cwd", "session"})


def parse_meta(meta, *, reserved: frozenset[str] = RESERVED_META) -> dict[str, str]:
    """``["corpus=x", "issue=12"]`` (or one such string) as ``{"corpus": "x", "issue": "12"}``.

    A key in ``reserved`` (what annals records itself) is refused: writing it would forge
    provenance. A filter reads any key, so it passes ``reserved=frozenset()``.

    >>> parse_meta(["corpus=annals", "issue=64"])
    {'corpus': 'annals', 'issue': '64'}
    >>> parse_meta(None)
    {}
    >>> parse_meta("oops")
    Traceback (most recent call last):
    ...
    ValueError: --meta takes key=value (for example corpus=annals), got 'oops'
    >>> parse_meta(["host=h"])
    Traceback (most recent call last):
    ...
    ValueError: --meta cannot set 'host': annals records it (use --session for the session)
    """
    out = {}
    for item in [meta] if isinstance(meta, str) else list(meta or ()):
        key, eq, value = item.partition("=")
        if not eq or not key.strip():
            raise ValueError(
                f"--meta takes key=value (for example corpus=annals), got {item!r}"
            )
        if key.strip() in reserved:
            raise ValueError(
                f"--meta cannot set {key.strip()!r}: annals records it (use --session for the session)"
            )
        out[key.strip()] = value
    return out


SINCE_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_iso(text: str) -> datetime:
    """An ISO date or time as an aware datetime; one with no offset is local time."""
    text = re.sub(r"(?<=\d) (?=\d\d:\d\d$)", "+", text.strip())  # a "+" in a URL query arrives as a space
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.astimezone()


def parse_since(since: str, *, now: datetime | None = None) -> datetime:
    """A moment, as an aware datetime: an ISO date or time (local time when it has no offset), or an age.

    >>> parse_since("2026-11-12T09:00+00:00").isoformat()
    '2026-11-12T09:00:00+00:00'
    >>> parse_since("2d", now=datetime(2026, 11, 14, tzinfo=timezone.utc)).date().isoformat()
    '2026-11-12'
    """
    bad = ValueError(
        f"since takes an ISO date or time (2026-11-12, 2026-11-12T09:00; local time unless it has an offset) "
        f"or an age (6h, 2d), got {since!r}"
    )
    m = re.fullmatch(r"(\d+)\s*([mhdw])", since.strip().lower())
    try:
        if m:
            age = timedelta(**{SINCE_UNITS[m.group(2)]: int(m.group(1))})
            return (now or datetime.now(timezone.utc)) - age
        return parse_iso(since)
    except (ValueError, OverflowError):
        raise bad from None


def changed_at(meta: dict) -> datetime | None:
    """When a document last changed: a replaced one counts from its newest version."""
    try:
        return parse_iso(str(meta.get("updated") or meta.get("created", "")))
    except (ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class DocFilter:
    """What a caller wants of a listing: any of since, session, tag and source keys; empty means all."""

    since: datetime | None = None
    session: str | None = None
    tag: str | None = None
    source: Mapping[str, str] = field(default_factory=dict, hash=False)

    @classmethod
    def of(
        cls,
        *,
        since: str | None = None,
        session: str | None = None,
        tag: str | None = None,
        meta: Iterable[str] | str | None = None,
    ) -> "DocFilter":
        """From the CLI's spelling: ``since`` text, ``meta`` as ``key=value`` strings."""
        source = parse_meta(meta, reserved=frozenset())
        if session and source.get("session", session) != session:
            raise ValueError(
                f"session given twice, differently: {session!r} and {source['session']!r}"
            )
        return cls(
            since=parse_since(since) if since else None,
            session=session or None,
            tag=tag or None,
            source=MappingProxyType(source),
        )

    def matches(self, doc: dict) -> bool:
        """Whether ``doc`` (a meta) passes every filter that was given."""
        if self.since is not None:
            changed = changed_at(doc)
            if changed is None or changed < self.since:
                return False
        if self.tag is not None and self.tag not in (doc.get("tags") or ()):
            return False
        wanted = {**self.source, **({"session": self.session} if self.session else {})}
        have = doc.get("source") or {}
        return all(have.get(k) == v for k, v in wanted.items())

    def apply(self, docs: Iterable[dict]) -> list[dict]:
        """The documents that pass, in their order."""
        return [d for d in docs if self.matches(d)]
