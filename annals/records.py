"""The published documents as records for a retrieval index, so an agent can find one by meaning.

annals keeps its own substring search for the page's filter box. Searching by meaning ("the
report comparing local TTS engines") is ``ir``'s job, and ``ir`` takes any package's records
through a named callable: register this one once and ``ir`` rebuilds from it on its own::

    ir register annals --records annals.records:records      # the exact command is ir's
    ir discover annals "the report comparing local TTS engines"

One record per current document (the bin and earlier versions are not indexed). A markdown
or text document brings its text; any other kind (an image, a page, a PDF) brings its title and
excerpt, so it can still be found. Overviews and combined documents duplicate their sources,
so they are left out unless asked for. A document the owner or the publisher tagged
``noindex`` or ``private`` is never yielded: decided here, before the first build, because an
index on another machine cannot take it back.

>>> import tempfile, pathlib
>>> from annals.store import DocStore
>>> root = pathlib.Path(tempfile.mkdtemp())
>>> store = DocStore(root)
>>> _ = store.publish(text="# Local TTS engines\\n\\nPiper and Kokoro compared.", title="TTS", tags=["research"])
>>> _ = store.publish(text="# Secret\\n\\nnot for an index", title="S", tags=["noindex"])
>>> [(r["title"], r["tags"], "Kokoro" in r["text"]) for r in records(target=str(root))]
[('TTS', 'research', True)]
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from annals.catalog import default_tags
from annals.config import load_settings
from annals.sources import PUBLISHED, PublishedSource, mk_key
from annals.store import DocStore
from annals.target import parse_target

#: a document with one of these tags is never indexed
DFLT_SKIP_TAGS = frozenset({"noindex", "private"})
#: the tags of documents made from other documents: overviews and combined files
DERIVED_TAGS = frozenset({"overview", "combined"})
#: the record fields that are filters in the index (``ir``'s ``metadata_keys``)
METADATA_KEYS = ("title", "url", "kind", "session", "tags", "created", "updated")


def records(
    *,
    target: str | None = None,
    to: str | None = None,
    skip_tags: Iterable[str] = DFLT_SKIP_TAGS,
    include_derived: bool = False,
) -> Iterator[dict]:
    """One dict per indexable document: ``id``, ``text`` and the :data:`METADATA_KEYS`.

    ``target`` / ``to`` choose the store as ``annals ls`` does (default: the configured one).
    ``tags`` is one comma-separated string, since an index filters on scalars.
    """
    settings = load_settings(target=target, to=to)
    store = DocStore(parse_target(settings.target), settle=not settings.outbox)
    source = PublishedSource(store)
    owner = default_tags(store)
    skip = set(skip_tags) | (set() if include_derived else DERIVED_TAGS)
    for row in source.rows():
        tags = list(owner.get(mk_key(PUBLISHED, row["id"]), row["tags"]))
        if skip & set(tags):
            continue
        text = source.text(row["id"]) or f"{row['title']}\n\n{row.get('excerpt', '')}"
        yield {
            "id": row["id"],
            "text": text,
            "title": row["title"],
            "url": f"{settings.base_url}/d/{row['id']}",
            "kind": row["kind"],
            "session": row.get("session", ""),
            "tags": ",".join(tags),
            "created": row.get("created", ""),
            "updated": row.get("updated") or row.get("created", ""),
        }
