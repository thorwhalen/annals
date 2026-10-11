# annals.sources

Item sources: everything the page lists, wherever it lives, as rows of one shape.

A *source* is a named, read-mostly collection of items. Two kinds exist:

* [`PublishedSource`](#annals.sources.PublishedSource): the documents agents published (a [`annals.store.DocStore`](annals.store.md#annals.store.DocStore)).
* [`FolderSource`](#annals.sources.FolderSource): a folder of files owned by someone else, read in place and never
  written (the crowsnest ledgers, and any other personal folder later). Its items are the
  folder’s files, keyed by their path relative to the folder.

Every source yields the same row shape, which the page lists, searches and filters:

`key`      `<source>:<id>`, unique across sources (the API’s item id)
`source`   the source’s name; `id` the item’s id within it
`title`, `kind` (see [`annals.store.kind_of()`](annals.store.md#annals.store.kind_of)), `session` (who wrote it)
`time`     ISO 8601, UTC: publication time, or a file’s last modification
`size`, `tags` (the item’s own; the catalog overlays the owner’s), `excerpt`

Sources are plain objects with a few methods (the [`Source`](#annals.sources.Source) protocol), so a new kind
of folder is a new class or a new keyword argument, never a change to the API.

### Module Attributes

| [`SOURCE_NAME_RE`](#annals.sources.SOURCE_NAME_RE)        | a source name is a url segment and part of every item key                            |
|------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`RESERVED_SOURCE_NAMES`](#annals.sources.RESERVED_SOURCE_NAMES) | names the page uses for its own routes (`/all`, `/trash`) or the published documents |

### Functions

| [`as_source`](#annals.sources.as_source)(name, spec)    | A source from a source, or from a folder path (read in place as a [`FolderSource`](#annals.sources.FolderSource)).   |
|---------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| [`check_source_name`](#annals.sources.check_source_name)(name)  | `name` if it can name an extra source; `ValueError` saying why not otherwise.                                                       |
| `iso_utc`(ts)                                                             |                                                                                                                                     |
| [`list_meta`](#annals.sources.list_meta)(meta)          | A listing row: the meta without its per-file tables (a folder can hold thousands).                                                  |
| `mk_key`(source, item_id)                                                 |                                                                                                                                     |
| [`parse_sources_spec`](#annals.sources.parse_sources_spec)(spec) | `"ledgers=~/x, notes=/y"` -> `{"ledgers": "~/x", "notes": "/y"}` (the env form).                                                    |
| [`split_key`](#annals.sources.split_key)(key)           | `"ledgers:a/b.md"` -> `("ledgers", "a/b.md")`; `KeyError` when malformed.                                                           |
| [`top_level_name`](#annals.sources.top_level_name)(rel)      | Who wrote a file in a folder of per-session files: `a.md` -> `a`, `b/c.md` -> `b`.                                                  |
| [`with_thumb`](#annals.sources.with_thumb)(meta)         | Add `thumb` (the first image, main file first) and fix pre-media kinds.                                                             |

### Classes

| [`FolderSource`](#annals.sources.FolderSource)(root, \*, name[, title, ...])   | A folder of files, read in place and never written, as a `Mapping` of rows.   |
|-----------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| [`PublishedSource`](#annals.sources.PublishedSource)(store, \*[, title])          | The documents agents published, as rows (a view over a `DocStore`).           |
| [`Source`](#annals.sources.Source)(\*args, \*\*kwargs)                   | What the catalog needs from a source of items.                                |

### *class* annals.sources.FolderSource(root, \*, name, title=None, exclude=('.\*', '_\_pycache_\_', '\*.pyc', '\*.pyo'), session_of=<function top_level_name>)

Bases: [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)

A folder of files, read in place and never written, as a `Mapping` of rows.

Keys are paths relative to `root` (`"annals.md"`, `"cw-liaise/design.md"`), values
listing rows. The folder is walked on every listing (a stat per file, cheap for
hundreds), and a file is re-read only when its size or mtime changed. Hidden files and
caches are skipped (`exclude`, the same patterns a directory publish skips), and so
is anything that resolves outside `root`.

`session_of(rel)` names who wrote a file; the default suits a folder of per-session
files and sub-folders ([`top_level_name()`](#annals.sources.top_level_name)).

#### file_path(rel)

The file on disk; `KeyError` if it is absent, hidden, or escapes the root.

Only the canonical spelling of a path is accepted (`a/b.md`, not `./a/b.md`,
`a//b.md` or `a/b.md/`), so one file has one key.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

#### text(rel)

The file’s text (cached until it changes); `""` for binaries and huge files.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* annals.sources.PublishedSource(store, , title='Published')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The documents agents published, as rows (a view over a `DocStore`).

Always named `published`: the page links its items to `/d/<id>`.

### annals.sources.RESERVED_SOURCE_NAMES *= frozenset({'all', 'published', 'trash'})*

names the page uses for its own routes (`/all`, `/trash`) or the published documents

### annals.sources.SOURCE_NAME_RE *= re.compile('^[a-z0-9][a-z0-9_-]{0,63}$')*

a source name is a url segment and part of every item key

### *class* annals.sources.Source(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

What the catalog needs from a source of items.

#### item(item_id)

One row plus what the page shows (`text` for text kinds). `KeyError` if absent.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### rows(, trash=False)

Listing rows, newest first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### text(item_id)

The item’s full text for search (`""` when it has none).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.sources.as_source(name, spec)

A source from a source, or from a folder path (read in place as a [`FolderSource`](#annals.sources.FolderSource)).

* **Return type:**
  [`Source`](#annals.sources.Source)

### annals.sources.check_source_name(name)

`name` if it can name an extra source; `ValueError` saying why not otherwise.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.sources.list_meta(meta)

A listing row: the meta without its per-file tables (a folder can hold thousands).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.sources.parse_sources_spec(spec)

`"ledgers=~/x, notes=/y"` -> `{"ledgers": "~/x", "notes": "/y"}` (the env form).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.sources.split_key(key)

`"ledgers:a/b.md"` -> `("ledgers", "a/b.md")`; `KeyError` when malformed.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.sources.top_level_name(rel)

Who wrote a file in a folder of per-session files: `a.md` -> `a`, `b/c.md` -> `b`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.sources.with_thumb(meta)

Add `thumb` (the first image, main file first) and fix pre-media kinds.

Documents published before media kinds existed say `file` for an image or a video;
their kind is recomputed from the main file so they show inline too.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
