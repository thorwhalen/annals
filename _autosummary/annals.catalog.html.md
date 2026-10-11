# annals.catalog

The catalog: every source’s items as one list, with search and the owner’s tags.

[`Catalog`](#annals.catalog.Catalog) is the facade the HTTP API stands on. It combines named sources (see
[`annals.sources`](annals.sources.html.md#module-annals.sources)) and a tag store (see [`annals.tags`](annals.tags.html.md#module-annals.tags)):

* [`Catalog.rows()`](#annals.catalog.Catalog.rows) lists items newest first, across sources or within one, filtered by
  a full-text query (every word must appear in the title, tags, session, excerpt or full
  text; case-insensitive), each row with the owner’s tags overlaid and, when there is a
  query, a `snippet` of the text around the first match.
* [`Catalog.item()`](#annals.catalog.Catalog.item) is one item, [`Catalog.set_tags()`](#annals.catalog.Catalog.set_tags) replaces its tags (in the tag
  store, never in the item), [`Catalog.tag_counts()`](#annals.catalog.Catalog.tag_counts) lists every tag in use.

Facets (kind, session, date, tag) are not computed here: the page counts them over the rows
it received, so every toggle is instant and the counts are always the ones the current
query would give.

### Functions

| [`mk_catalog`](#annals.catalog.mk_catalog)(store, \*[, sources, tags])   | The published documents first, then the extra sources; the owner's tags beside them.   |
|-------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|

### Classes

| [`Catalog`](#annals.catalog.Catalog)(sources, \*, tags)   | Named sources plus the owner's tags, listed, searched and tagged as one collection.   |
|-------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|

### *class* annals.catalog.Catalog(sources, , tags)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Named sources plus the owner’s tags, listed, searched and tagged as one collection.

#### forget(key)

Drop an item’s tags (when the item itself is gone for good).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### item(key)

One item, with what the page shows; `KeyError` if there is none.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### rows(q='', , source=None, trash=False)

Items newest first, from one source or all, matching every word of `q`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### set_tags(key, tags)

Replace an item’s tags (in the tag store); the item’s row, with them.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### sources_info()

Each source’s name and title, in the order given.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### tag_counts()

Every tag in use on a listed item, with how many items carry it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

### annals.catalog.mk_catalog(store, , sources=None, tags=None)

The published documents first, then the extra sources; the owner’s tags beside them.

`sources` maps a name to a folder path (read in place) or a `Source`; by
default the folders named in `ANNALS_SOURCES`. `tags` defaults to one JSON file
under the data root (`tags/tags.json`), or a dict when the data root is remote.
The API, and any CLI or agent tool that tags items, build their catalog here.

* **Return type:**
  [`Catalog`](#annals.catalog.Catalog)
