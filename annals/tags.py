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

import re
from collections.abc import Iterable

from annals.jsonstore import JsonFileStore

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


class JsonTagStore(JsonFileStore):
    """``{item key: [tags]}`` in one JSON file (see :class:`annals.jsonstore.JsonFileStore`).

    Safe with several server processes on one machine; a damaged file reads as empty and is
    kept aside (``tags.json.damaged``) at the next write.
    """

    label = "annals tags"

    def valid(self, value) -> bool:
        return isinstance(value, list) and all(isinstance(t, str) for t in value)

    def clean(self, value: Iterable[str]) -> list[str]:
        return normalize_tags(value)
