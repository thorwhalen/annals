"""The published documents as records for a retrieval index, so an agent can find one by meaning.

annals keeps its own full-text index for the page's search box (:mod:`annals.search`).
Searching by meaning ("the report comparing local TTS engines") is ``ir``'s job, and ``ir``
takes any package's records through a named callable: register this one once (from Python;
``ir register`` on the command line has no records option) and ``ir`` rebuilds from it::

    import ir, annals.records
    ir.register("annals", "records", fetcher="annals.records:records",
                metadata_keys=list(annals.records.METADATA_KEYS))
    ir.build_corpus("annals")       # then: ir discover annals "the report comparing local TTS engines"

One record per current document (the bin and earlier versions are not indexed). A markdown,
text or html document brings its text (html without its markup); a folder or a document of
several markdown files brings them as one text, as ``annals aggregate`` makes it; any other
kind (an image, a PDF) brings its title and excerpt, so it can still be found. Overviews and
combined documents duplicate their sources, so they are left out unless asked for. A document
the owner or the publisher tagged ``noindex`` or ``private`` (any case) is never yielded.

Run it where the documents are: it refuses an outbox and a remote target, because the
owner's tags (the privacy gate) live beside the documents, and an index built from a partial
view would drop the rest. Two things belong to the index, not to this function: ``ir`` decides
a record changed by hashing its ``text``, so a retag or retitle reaches the index's filters
only on a rebuild that is ``full`` (which also prunes a document trashed, purged or newly
tagged ``noindex``; register with full builds). ``url`` uses this machine's ``base_url``.

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

from annals.aggregate import aggregate_markdown, doc_markdown_files
from annals.catalog import default_tags
from annals.config import MAX_INLINE_TEXT_BYTES, load_settings
from annals.overview import COMBINED_TAG, TAG as OVERVIEW_TAG, html_to_text
from annals.sources import PUBLISHED, mk_key
from annals.store import TEXT_KINDS, DocStore
from annals.target import LocalTarget, parse_target

#: a document with one of these tags (any case) is never indexed
DFLT_SKIP_TAGS = frozenset({"noindex", "private"})
#: the tags of documents made from other documents: overviews and combined files
DERIVED_TAGS = frozenset({OVERVIEW_TAG, COMBINED_TAG})
#: the record fields that are filters in the index (``ir``'s ``metadata_keys``)
METADATA_KEYS = ("title", "url", "kind", "session", "tags", "created", "updated")
#: a text is cut to this many characters, so one huge document cannot swamp an index
MAX_TEXT_CHARS = MAX_INLINE_TEXT_BYTES


def _text_of(store: DocStore, meta: dict) -> str:
    """What a document says: its text, a folder's markdown files joined, else its title and excerpt."""
    try:
        if meta["kind"] in TEXT_KINDS | {"html"}:
            text = store.read_text(meta["id"])
            text = html_to_text(text) if meta["kind"] == "html" else text
        else:
            pairs = list(
                doc_markdown_files(
                    [(meta, meta.get("files", []))], read=store.read_text
                )
            )
            text = (
                aggregate_markdown(dict(pairs), title=meta["title"], toc=False)
                if pairs
                else ""
            )
    except (KeyError, ValueError, OSError):
        text = ""
    return (text or f"{meta['title']}\n\n{meta.get('excerpt', '')}")[:MAX_TEXT_CHARS]


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
    if settings.outbox or not isinstance(store.target, LocalTarget):
        raise ValueError(
            "index the documents where they are: this target is remote or an outbox, "
            "so the owner's tags (what keeps a document out) and some documents are not here"
        )
    owner = default_tags(store)
    skip = {t.casefold() for t in skip_tags} | (
        set() if include_derived else {t.casefold() for t in DERIVED_TAGS}
    )
    for meta in store.list():
        own = owner.get(mk_key(PUBLISHED, meta["id"]))
        tags = list(own) if own is not None else list(meta.get("tags") or [])
        every = {t.casefold() for t in [*tags, *(meta.get("tags") or [])]}
        if skip & every:  # the publisher's tag still counts after an owner's retag
            continue
        yield {
            "id": meta["id"],
            "text": _text_of(store, meta),
            "title": meta["title"],
            "url": f"{settings.base_url}/d/{meta['id']}",
            "kind": meta["kind"],
            "session": (meta.get("source") or {}).get("session", ""),
            "tags": ",".join(tags),
            "created": meta.get("created", ""),
            "updated": meta.get("updated") or meta.get("created", ""),
        }
