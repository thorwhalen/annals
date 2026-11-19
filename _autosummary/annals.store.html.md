# annals.store

The document store: a flat set of documents, tags, groups and a recycle bin, as plain files.

Layout under the data root (local or remote, see [`annals.target`](annals.target.html.md#module-annals.target)):

```default
docs/<id>/meta.json         one document: metadata
docs/<id>/<main file>       its content (index.html, report.md, ...), plus any assets
docs/<id>/.versions/<n>/    an earlier version, whole (its own meta.json and files)
docs/<id>.r<stamp>-<hex>/   a replacement not applied yet (``publish(replace=<id>)``)
trash/<id>/...              the same shape; the recycle bin is a move
groups/<gid>.json           a named, ordered list of document ids with its own URL
```

Flat on purpose: agents from many corpora do not share a hierarchy, and every placement
decision costs tokens. Tags and groups carry the structure. Ids are time-sortable and
readable (`20261003-203301-starwars-theme-report-3f9a`), so a listing is already in
publication order and a URL says what it points to.

Plain files, written whole, because the same tree is written by rsync from another machine
and read by the server; there is no index to keep consistent.

Living documents (one link that stays current) are a replace: the new files are written as
a *pending* replacement next to the document, never over it, and whoever reads the store
applies it ([`DocStore.settle()`](#annals.store.DocStore.settle)): the current files move under `.versions/<n>/` and
the replacement takes the id. Writing beside rather than over is what lets a replace travel
through an outbox (a directory another machine pulls and empties): the pending directory is
just another new directory to pull, and the store on the reading side applies it. Applying
is a sequence of renames, each claimed atomically, so two readers never apply the same
replacement twice and nothing is ever deleted.

### Module Attributes

| [`HEAD_CHARS`](#annals.store.HEAD_CHARS)         | how much of a file is read to find its title and excerpt                                                                                                                                                                                          |
|---------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_EXCLUDE`](#annals.store.DFLT_EXCLUDE)       | hidden files, caches, compiled python                                                                                                                                                                                                             |
| [`VERSIONS`](#annals.store.VERSIONS)           | a published folder's own content skips hidden names, and a document that carries one anyway is refused)                                                                                                                                           |
| [`VERSION_SEP`](#annals.store.VERSION_SEP)        | `<id>@<n>` names version `n` of a document; `@` is not an id character                                                                                                                                                                            |
| [`PENDING_SEP`](#annals.store.PENDING_SEP)        | `<id>.r<stamp>-<hex>` is a pending replacement of `<id>`                                                                                                                                                                                          |
| [`LOCK_PREFIX`](#annals.store.LOCK_PREFIX)        | `<root>/.lock-<id>/` is held while a replacement of `<id>` is applied; it is also the working directory, holding `next` (the replacement) and `old` (the version being archived) between renames, and `lock.json` (what a recovery needs to know) |
| [`LOCK_STALE_S`](#annals.store.LOCK_STALE_S)       | its work is finished or undone                                                                                                                                                                                                                    |
| [`GROUP_LOCK_WAIT_S`](#annals.store.GROUP_LOCK_WAIT_S)  | how long a group write waits for another writer of the same group, and how often it looks                                                                                                                                                         |
| [`GROUP_LOCK_STALE_S`](#annals.store.GROUP_LOCK_STALE_S) | a group lock is held for milliseconds, so one older than this is a dead holder's (the lock's note carries it, so recovery on another machine knows)                                                                                               |
| [`MAX_GROUP_TITLE`](#annals.store.MAX_GROUP_TITLE)    | the longest title a group may have (a longer one is refused, not cut)                                                                                                                                                                             |
| [`SWAP_WAIT_S`](#annals.store.SWAP_WAIT_S)        | a reader that misses a document being swapped waits for it this long, in steps                                                                                                                                                                    |
| [`SWAP_STEP_S`](#annals.store.SWAP_STEP_S)        | a reader that misses a document being swapped waits for it this long, in steps                                                                                                                                                                    |
| [`INCOMING_PREFIX`](#annals.store.INCOMING_PREFIX)    | a replacement is written under this hidden name, then renamed into place whole                                                                                                                                                                    |
| [`RESERVED`](#annals.store.RESERVED)           | the store's bookkeeping lives there                                                                                                                                                                                                               |
| [`ARTIFACT_HOSTS`](#annals.store.ARTIFACT_HOSTS)     | the interactive version of a page lives there, and the document's page links out to it                                                                                                                                                            |
| [`THUMB_CACHE`](#annals.store.THUMB_CACHE)        | where the page's thumbnails are cached, under the data root (beside the documents, never inside one)                                                                                                                                              |
| [`SIDECAR_SUFFIXES`](#annals.store.SIDECAR_SUFFIXES)   | timed text published beside an audio file, named `<stem><suffix>` in the same folder (the suffix in any case): a transcript (`.cues.json`, `.vtt` or `.srt`) and chapters (`.chapters.vtt`).                                                      |
| [`PROVENANCE_KEYS`](#annals.store.PROVENANCE_KEYS)    | `source` (the publisher's host, cwd, session and `--meta` keys) and `artifact` (a claude.ai link only the owner can open).                                                                                                                        |
| [`ROOM_META_KEYS`](#annals.store.ROOM_META_KEYS)     | everything a reader's page needs, and nothing else, so a field added later stays out until named here                                                                                                                                             |

### Functions

| [`check_artifact_url`](#annals.store.check_artifact_url)(url, \*[, hosts])   | `url` if it is an `https` link to one of `hosts` (or a subdomain), else raise.                                                                               |
|-----------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`check_id`](#annals.store.check_id)(doc_id)                       | Raise `ValueError` on an id that could not have come from [`mk_id()`](#annals.store.mk_id).                                          |
| [`clean_title`](#annals.store.clean_title)(title)                     | A title as the page shows it: control and invisible format characters dropped, whitespace collapsed.                                                         |
| [`is_sidecar_of`](#annals.store.is_sidecar_of)(path, media)             | True when `path` is timed text for `media`: `talk.vtt` or `talk.cues.json` for `talk.mp3`, in the same folder (paths compare whole), the suffix in any case. |
| [`kind_of`](#annals.store.kind_of)(filename)                      | The rendering kind of a file, from its extension.                                                                                                            |
| [`mk_id`](#annals.store.mk_id)(title, \*[, when])               | `YYYYMMDD-HHMMSS-<slug>-<4 hex>`: sortable by time, readable in a URL.                                                                                       |
| [`mk_pending_id`](#annals.store.mk_pending_id)(doc_id, \*[, when])      | `<id>.r<YYYYMMDDHHMMSSffffff>-<hex>`: sorts in publication order.                                                                                            |
| [`now_iso`](#annals.store.now_iso)()                              | UTC timestamp with second precision, the format every meta.json uses.                                                                                        |
| [`room_meta`](#annals.store.room_meta)(meta, \*[, keys])            | Only the fields of `meta` a room shows ([`ROOM_META_KEYS`](#annals.store.ROOM_META_KEYS)).                                                    |
| [`slugify`](#annals.store.slugify)(text, \*[, max_len])           | Lowercase ascii words joined by hyphens; empty input becomes `doc`.                                                                                          |
| [`split_version`](#annals.store.split_version)(doc_id)                  | `("<id>", n)` from `<id>@<n>` (version `n`), `("<id>", None)` from an id.                                                                                    |
| [`title_and_excerpt`](#annals.store.title_and_excerpt)(head, kind)          | A title (markdown `# h1` or html `<title>`) and a plain-text excerpt of `head`.                                                                              |
| [`without_provenance`](#annals.store.without_provenance)(meta, \*[, keys])   | `meta` without the keys that say where it came from.                                                                                                         |

### Classes

| [`DocStore`](#annals.store.DocStore)(target, \*[, settle])   | Publish, list, read, trash, restore and group documents on a `Target`.              |
|-----------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`HidingStore`](#annals.store.HidingStore)(store, \*, hide)     | The documents of `store` without those `hide(meta)` is true of, on the same target. |
| [`RoomStore`](#annals.store.RoomStore)(store, \*[, keys])     | The documents of `store` as an outside audience reads them (a room).                |

### annals.store.ARTIFACT_HOSTS *= ('claude.ai',)*

the interactive
version of a page lives there, and the document’s page links out to it

* **Type:**
  hosts an artifact link (`publish(artifact=...)`) may point at

### annals.store.DFLT_EXCLUDE *= ('.\*', '_\_pycache_\_', '\*.pyc', '\*.pyo')*

hidden files, caches, compiled python

* **Type:**
  names never published from a directory

### *class* annals.store.DocStore(target, , settle=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Publish, list, read, trash, restore and group documents on a `Target`.

#### add_to_group(gid, doc_ids)

Append documents to an existing group, keeping order and skipping ones it has.

Each document must exist and not be in the bin; `KeyError` for a group that is not
there.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### doc_rel(doc_id)

The directory of a document (or of a version, `<id>@<n>`) under the data root.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### group(gid)

One group, by id.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### group_docs(gid)

A group and the meta of each of its documents, in its order (missing or binned ones left out).

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict), [`list`](#annals.store.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]

#### groups_of(doc_id)

The groups a document is in, newest first, each as `{"id", "title", "n"}`.

* **Return type:**
  [`list`](#annals.store.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### holds(ref_id)

Whether a document (or a version of one) or a group with this id is here, in the bin or not.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### list(, trash=False)

Every document’s meta, last changed first (`updated`, else `created`).

Pending replacements are applied first (when this store settles). One whose
document is not here is listed under its own id, so it is never out of sight.

* **Return type:**
  [`list`](#annals.store.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### list_groups()

Every group, newest first.

* **Return type:**
  [`list`](#annals.store.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### make_group(title, doc_ids, , gid=None, live_only=True)

Create (or overwrite) a group: a titled, ordered list of documents.

The title is cleaned (control characters dropped, whitespace collapsed, at most
`MAX_GROUP_TITLE` long, not blank); repeats are dropped, keeping the first; each
document must exist and not be in the bin unless `live_only=False` (a bundle that
keeps a document later binned). `ValueError` says which rule failed. An explicit
`gid` rewrites that group, under its lock.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### meta(doc_id, , settle=True)

One document’s meta; `in_trash` says which side of the bin it is on.

`<id>@<n>` is version `n`: its own meta, with `version_of` naming the document.
A pending replacement, read by its own id, says `pending`. `settle=False`
skips applying pending replacements (for a hot path such as a raw file).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### pending(doc_id=None, , names=None)

Pending replacements (directory names), oldest first; of one document if given.

`names`: the listing of `docs/` when the caller already has it.

* **Return type:**
  [`list`](#annals.store.DocStore.list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### publish(\*sources, title=None, tags=(), source=None, text=None, filename='document.md', exclude=('.\*', '_\_pycache_\_', '\*.pyc', '\*.pyo'), replace=None, artifact=None, pdf=True, pdf_renderer='default')

Publish files (or a directory, or `text`) as ONE document; return its meta.

One markdown or html file is the common case. A directory is published whole, with
`index.html` (or the first renderable file) as the page shown. `text` publishes a
string as `filename` instead of reading sources. `exclude` lists glob patterns
skipped inside a directory (hidden files and caches by default; `()` keeps all).

`replace` (a document id) publishes a new version of that document instead of a
new document: same id, same link, the current files kept as a version. It is
written as a pending replacement and applied at once when this store settles
(otherwise where the store is read). The returned meta says `pending` until then.

`artifact` (a claude.ai artifact link, see [`check_artifact_url()`](#annals.store.check_artifact_url)) is the
interactive version of the page: the document’s page links out to it. A
replacement that names none keeps the document’s current one.

An html page gets its own Download PDF button, and `<stem>.pdf` printed beside
it by `pdf_renderer` unless it has one ([`annals.pagepdf`](annals.pagepdf.html.md#module-annals.pagepdf), which says how a
page declares or opts out). `pdf=False` leaves the page as it is.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### purge(doc_id)

Delete a document that is in the bin. Refuses one that is not.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### read_text(doc_id, rel=None)

A document’s main file (or one of its files) as text.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### restore(doc_id)

Move a document out of the bin (idempotent).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### search(query, , trash=False)

Case-insensitive match of every query word against title, tags, excerpt, source.

* **Return type:**
  [`list`](#annals.store.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### settle(doc_id=None)

Apply pending replacements (of one document, or all); return the ids replaced.

A replacement whose document is not here yet (it is still on its way, or the
document was purged) stays pending and is listed under its own id.

* **Return type:**
  [`list`](#annals.store.DocStore.list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### trash(doc_id)

Move a document into the bin (idempotent).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### versions(doc_id)

Every version of a document, oldest first, the current one last.

* **Return type:**
  [`list`](#annals.store.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### annals.store.GROUP_LOCK_STALE_S *= 30*

a group lock is held for milliseconds, so one older than this is a dead holder’s (the
lock’s note carries it, so recovery on another machine knows)

### annals.store.GROUP_LOCK_WAIT_S *= 10*

how long a group write waits for another writer of the same group, and how often it looks

### annals.store.HEAD_CHARS *= 4000*

how much of a file is read to find its title and excerpt

### *class* annals.store.HidingStore(store, , hide)

Bases: [`DocStore`](#annals.store.DocStore)

The documents of `store` without those `hide(meta)` is true of, on the same target.

A hidden document is absent, not refused: it is not listed or found, [`meta()`](#annals.store.HidingStore.meta) raises
`KeyError` for it, its versions and its pending replacements (so whatever reads a
document through the store, its page, files, versions or a share, answers as for a
missing one), and groups read through this store leave it out. An API built over this
store therefore cannot show it anywhere, whichever route asks; [`hides()`](#annals.store.HidingStore.hides) lets what
keeps records of its own about documents (shares) hide those records too. Reads go
through `store`, so a subclass’s reading still applies; writes reach the same target,
and a group is always rewritten from its whole list, so hiding never deletes anything.

#### add_to_group(gid, doc_ids)

Append to the group’s whole list (the hidden ids stay in it); a hidden document
is refused as a missing one.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### group(gid)

One group, by id.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### hides(doc_id)

Whether `doc_id` is a document of the whole store that this one hides.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### list(, trash=False)

Every document’s meta, last changed first (`updated`, else `created`).

Pending replacements are applied first (when this store settles). One whose
document is not here is listed under its own id, so it is never out of sight.

* **Return type:**
  [`list`](#annals.store.HidingStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### list_groups()

Every group, newest first.

* **Return type:**
  [`list`](#annals.store.HidingStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### meta(doc_id, , settle=True)

One document’s meta; `in_trash` says which side of the bin it is on.

`<id>@<n>` is version `n`: its own meta, with `version_of` naming the document.
A pending replacement, read by its own id, says `pending`. `settle=False`
skips applying pending replacements (for a hot path such as a raw file).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.store.INCOMING_PREFIX *= '.incoming-'*

a replacement is written under this hidden name, then renamed into place whole

### annals.store.LOCK_PREFIX *= '.lock-'*

`<root>/.lock-<id>/` is held while a replacement of `<id>` is applied; it is also
the working directory, holding `next` (the replacement) and `old` (the version
being archived) between renames, and `lock.json` (what a recovery needs to know)

### annals.store.LOCK_STALE_S *= 600*

its work is finished or undone

* **Type:**
  a lock older than this was left by a crash

### annals.store.MAX_GROUP_TITLE *= 200*

the longest title a group may have (a longer one is refused, not cut)

### annals.store.PENDING_SEP *= '.r'*

`<id>.r<stamp>-<hex>` is a pending replacement of `<id>`

### annals.store.PROVENANCE_KEYS *= ('source', 'artifact')*

`source` (the publisher’s host,
cwd, session and `--meta` keys) and `artifact` (a claude.ai link only the owner can
open). `copy` to a room drops them from what it writes.

* **Type:**
  what a document’s meta says about where it came from

### annals.store.RESERVED *= ('.versions',)*

the store’s bookkeeping lives there

* **Type:**
  names a document’s own files may not use

### annals.store.ROOM_META_KEYS *= frozenset({'created', 'excerpt', 'files', 'id', 'in_trash', 'kind', 'main', 'size', 'sizes', 'tags', 'title', 'updated', 'version', 'version_of', 'versions'})*

everything a
reader’s page needs, and nothing else, so a field added later stays out until named here

* **Type:**
  the fields of a document’s meta an outside audience may see (a room)

### *class* annals.store.RoomStore(store, , keys=frozenset({'created', 'excerpt', 'files', 'id', 'in_trash', 'kind', 'main', 'size', 'sizes', 'tags', 'title', 'updated', 'version', 'version_of', 'versions'}))

Bases: [`HidingStore`](#annals.store.HidingStore)

The documents of `store` as an outside audience reads them (a room).

Nothing in the bin: a binned document is absent, as in [`HidingStore`](#annals.store.HidingStore), so the
owner withdraws a document from a room by binning it; a group left with no document
to show is absent too (its title included). And only the fields in
[`ROOM_META_KEYS`](#annals.store.ROOM_META_KEYS): every meta read through this store (one, a listing, a search,
a group’s) comes without the rest, so whatever an API builds from it cannot show or
match them. Writes go to `store` unchanged. Reading may still settle a pending
replacement the publisher left, as the owner’s store does.

#### group(gid)

One group, by id.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### list(, trash=False)

Every document’s meta, last changed first (`updated`, else `created`).

Pending replacements are applied first (when this store settles). One whose
document is not here is listed under its own id, so it is never out of sight.

* **Return type:**
  [`list`](#annals.store.RoomStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### list_groups()

Every group, newest first.

* **Return type:**
  [`list`](#annals.store.RoomStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### meta(doc_id, , settle=True)

One document’s meta; `in_trash` says which side of the bin it is on.

`<id>@<n>` is version `n`: its own meta, with `version_of` naming the document.
A pending replacement, read by its own id, says `pending`. `settle=False`
skips applying pending replacements (for a hot path such as a raw file).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.store.SIDECAR_SUFFIXES *= ('.cues.json', '.chapters.vtt', '.vtt', '.srt')*

timed text published beside an audio file, named `<stem><suffix>` in the same folder
(the suffix in any case): a transcript (`.cues.json`, `.vtt` or `.srt`) and chapters
(`.chapters.vtt`). The page plays the audio with them (`app.js`’s `SIDECARS`); a
document of one audio file and its sidecars is an audio document, not a folder. (Video
is left out until its page shows them.)

### annals.store.SWAP_STEP_S *= 0.02*

a reader that misses a document being swapped waits for it this long, in steps

### annals.store.SWAP_WAIT_S *= 2.0*

a reader that misses a document being swapped waits for it this long, in steps

### annals.store.THUMB_CACHE *= 'cache/thumbs'*

where the page’s thumbnails are cached, under the data root (beside the documents, never inside one)

### annals.store.VERSIONS *= '.versions'*

a published folder’s own content
skips hidden names, and a document that carries one anyway is refused)

* **Type:**
  where a document keeps its earlier versions (hidden

### annals.store.VERSION_SEP *= '@'*

`<id>@<n>` names version `n` of a document; `@` is not an id character

### annals.store.check_artifact_url(url, , hosts=('claude.ai',))

`url` if it is an `https` link to one of `hosts` (or a subdomain), else raise.

The link is shown on the document’s page as a button, so only a plain https URL to a
known artifact host is accepted: no other scheme, no credentials, no port, a host of
dns labels only, printable ascii without quotes, angle brackets or backslashes.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.store.check_id(doc_id)

Raise `ValueError` on an id that could not have come from [`mk_id()`](#annals.store.mk_id).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.store.clean_title(title)

A title as the page shows it: control and invisible format characters dropped,
whitespace collapsed. `ValueError` when blank or longer than `MAX_GROUP_TITLE`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.store.is_sidecar_of(path, media)

True when `path` is timed text for `media`: `talk.vtt` or `talk.cues.json` for
`talk.mp3`, in the same folder (paths compare whole), the suffix in any case.

```pycon
>>> is_sidecar_of("a/talk.CHAPTERS.vtt", "a/talk.mp3"), is_sidecar_of("b/talk.vtt", "a/talk.mp3")
(True, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.store.kind_of(filename)

The rendering kind of a file, from its extension.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.store.mk_id(title, , when=None)

`YYYYMMDD-HHMMSS-<slug>-<4 hex>`: sortable by time, readable in a URL.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.store.mk_pending_id(doc_id, , when=None)

`<id>.r<YYYYMMDDHHMMSSffffff>-<hex>`: sorts in publication order.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.store.now_iso()

UTC timestamp with second precision, the format every meta.json uses.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.store.room_meta(meta, , keys=frozenset({'created', 'excerpt', 'files', 'id', 'in_trash', 'kind', 'main', 'size', 'sizes', 'tags', 'title', 'updated', 'version', 'version_of', 'versions'}))

Only the fields of `meta` a room shows ([`ROOM_META_KEYS`](#annals.store.ROOM_META_KEYS)).

```pycon
>>> room_meta({"id": "a", "source": {"host": "h"}, "from_pending": "p", "versions": [{"n": 1, "from_pending": "p"}]})
{'id': 'a', 'versions': [{'n': 1}]}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.store.slugify(text, , max_len=48)

Lowercase ascii words joined by hyphens; empty input becomes `doc`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.store.split_version(doc_id)

`("<id>", n)` from `<id>@<n>` (version `n`), `("<id>", None)` from an id.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### annals.store.title_and_excerpt(head, kind)

A title (markdown `# h1` or html `<title>`) and a plain-text excerpt of `head`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.store.without_provenance(meta, , keys=('source', 'artifact'))

`meta` without the keys that say where it came from.

```pycon
>>> without_provenance({"id": "a", "source": {"host": "h"}, "artifact": "x"})
{'id': 'a'}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
