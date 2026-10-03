# intray.store

The document store: a flat set of documents, tags, groups and a recycle bin, as plain files.

Layout under the data root (local or remote, see [`intray.target`](intray.target.html.md#module-intray.target)):

```default
docs/<id>/meta.json         one document: metadata
docs/<id>/<main file>       its content (index.html, report.md, ...), plus any assets
trash/<id>/...              the same shape; the recycle bin is a move
groups/<gid>.json           a named, ordered list of document ids with its own URL
```

Flat on purpose: agents from many corpora do not share a hierarchy, and every placement
decision costs tokens. Tags and groups carry the structure. Ids are time-sortable and
readable (`20261003-203301-starwars-theme-report-3f9a`), so a listing is already in
publication order and a URL says what it points to.

Plain files, written whole, because the same tree is written by rsync from another machine
and read by the server; there is no index to keep consistent.

### Module Attributes

| [`KINDS`](#intray.store.KINDS)   | extension -> kind.   |
|----------------------------------------------------------|----------------------|

### Functions

| [`check_id`](#intray.store.check_id)(doc_id)             | Raise `ValueError` on an id that could not have come from [`mk_id()`](#intray.store.mk_id).   |
|-------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`kind_of`](#intray.store.kind_of)(filename)            | The rendering kind of a file, from its extension.                                                                     |
| [`mk_id`](#intray.store.mk_id)(title, \*[, when])     | `YYYYMMDD-HHMMSS-<slug>-<4 hex>`: sortable by time, readable in a URL.                                                |
| [`now_iso`](#intray.store.now_iso)()                    | UTC timestamp with second precision, the format every meta.json uses.                                                 |
| [`slugify`](#intray.store.slugify)(text, \*[, max_len]) | Lowercase ascii words joined by hyphens; empty input becomes `doc`.                                                   |

### Classes

| [`DocStore`](#intray.store.DocStore)(target)   | Publish, list, read, trash, restore and group documents on a `Target`.   |
|---------------------------------------------------------------------|--------------------------------------------------------------------------|

### *class* intray.store.DocStore(target)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Publish, list, read, trash, restore and group documents on a `Target`.

#### add_to_group(gid, doc_ids)

Append ids to an existing group, keeping order and skipping duplicates.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### group(gid)

One group, by id.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### list(, trash=False)

Every document’s meta, newest first (ids sort by time; `created` breaks ties).

* **Return type:**
  [`list`](#intray.store.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### list_groups()

Every group, newest first.

* **Return type:**
  [`list`](#intray.store.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### make_group(title, doc_ids, , gid=None)

Create (or overwrite) a group: a titled, ordered list of document ids.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### meta(doc_id)

One document’s meta; `in_trash` says which side of the bin it is on.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### publish(\*sources, title=None, tags=(), source=None, text=None, filename='document.md')

Publish files (or a directory, or `text`) as ONE document; return its meta.

One markdown or html file is the common case. A directory is published whole, with
`index.html` (or the first renderable file) as the page shown. `text` publishes a
string as `filename` instead of reading sources.

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
  [`list`](#intray.store.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### trash(doc_id)

Move a document into the bin (idempotent).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### intray.store.KINDS *= {'.csv': 'text', '.htm': 'html', '.html': 'html', '.json': 'text', '.log': 'text', '.markdown': 'md', '.md': 'md', '.py': 'text', '.toml': 'text', '.txt': 'text', '.yaml': 'text', '.yml': 'text'}*

extension -> kind. `html` renders in a frame, `md` renders as markdown, `text` as
preformatted text, anything else is a download.

### intray.store.check_id(doc_id)

Raise `ValueError` on an id that could not have come from [`mk_id()`](#intray.store.mk_id).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### intray.store.kind_of(filename)

The rendering kind of a file, from its extension.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### intray.store.mk_id(title, , when=None)

`YYYYMMDD-HHMMSS-<slug>-<4 hex>`: sortable by time, readable in a URL.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### intray.store.now_iso()

UTC timestamp with second precision, the format every meta.json uses.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### intray.store.slugify(text, , max_len=48)

Lowercase ascii words joined by hyphens; empty input becomes `doc`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
