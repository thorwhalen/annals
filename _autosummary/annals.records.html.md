# annals.records

The published documents as records for a retrieval index, so an agent can find one by meaning.

annals keeps its own substring search for the page’s filter box. Searching by meaning (“the
report comparing local TTS engines”) is `ir`’s job, and `ir` takes any package’s records
through a named callable: register this one once and `ir` rebuilds from it on its own:

```default
ir register annals --records annals.records:records      # the exact command is ir's
ir discover annals "the report comparing local TTS engines"
```

One record per current document (the bin and earlier versions are not indexed). A markdown,
text or html document brings its text (html without its markup); a folder or a document of
several markdown files brings them as one text, as `annals aggregate` makes it; any other
kind (an image, a PDF) brings its title and excerpt, so it can still be found. Overviews and
combined documents duplicate their sources, so they are left out unless asked for. A document
the owner or the publisher tagged `noindex` or `private` (any case) is never yielded.

Run it where the documents are: it refuses an outbox and a remote target, because the
owner’s tags (the privacy gate) live beside the documents, and an index built from a partial
view would drop the rest. Two things belong to the index, not to this function: `ir` decides
a record changed by hashing its `text`, so a retag or retitle reaches the index’s filters
only on a rebuild that is `full` (which also prunes a document trashed, purged or newly
tagged `noindex`; register with full builds). `url` uses this machine’s `base_url`.

```pycon
>>> import tempfile, pathlib
>>> from annals.store import DocStore
>>> root = pathlib.Path(tempfile.mkdtemp())
>>> store = DocStore(root)
>>> _ = store.publish(text="# Local TTS engines\n\nPiper and Kokoro compared.", title="TTS", tags=["research"])
>>> _ = store.publish(text="# Secret\n\nnot for an index", title="S", tags=["noindex"])
>>> [(r["title"], r["tags"], "Kokoro" in r["text"]) for r in records(target=str(root))]
[('TTS', 'research', True)]
```

### Module Attributes

| [`DFLT_SKIP_TAGS`](#annals.records.DFLT_SKIP_TAGS)   | a document with one of these tags (any case) is never indexed                     |
|-------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`DERIVED_TAGS`](#annals.records.DERIVED_TAGS)     | overviews and combined files                                                      |
| [`METADATA_KEYS`](#annals.records.METADATA_KEYS)    | the record fields that are filters in the index (`ir`'s `metadata_keys`)          |
| [`MAX_TEXT_CHARS`](#annals.records.MAX_TEXT_CHARS)   | a text is cut to this many characters, so one huge document cannot swamp an index |

### Functions

| [`records`](#annals.records.records)(\*[, target, to, skip_tags, ...])   | One dict per indexable document: `id`, `text` and the [`METADATA_KEYS`](#annals.records.METADATA_KEYS).   |
|----------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|

### annals.records.DERIVED_TAGS *= frozenset({'combined', 'overview'})*

overviews and combined files

* **Type:**
  the tags of documents made from other documents

### annals.records.DFLT_SKIP_TAGS *= frozenset({'noindex', 'private'})*

a document with one of these tags (any case) is never indexed

### annals.records.MAX_TEXT_CHARS *= 2000000*

a text is cut to this many characters, so one huge document cannot swamp an index

### annals.records.METADATA_KEYS *= ('title', 'url', 'kind', 'session', 'tags', 'created', 'updated')*

the record fields that are filters in the index (`ir`’s `metadata_keys`)

### annals.records.records(, target=None, to=None, skip_tags=frozenset({'noindex', 'private'}), include_derived=False)

One dict per indexable document: `id`, `text` and the [`METADATA_KEYS`](#annals.records.METADATA_KEYS).

`target` / `to` choose the store as `annals ls` does (default: the configured one).
`tags` is one comma-separated string, since an index filters on scalars.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
