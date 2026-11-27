# annals.catalog

The catalog: every source’s items as one list, with search and the owner’s tags.

[`Catalog`](#annals.catalog.Catalog) is the facade the HTTP API stands on. It combines named sources (see
[`annals.sources`](annals.sources.html.md#module-annals.sources)) and a tag store (see [`annals.tags`](annals.tags.html.md#module-annals.tags)):

* [`Catalog.rows()`](#annals.catalog.Catalog.rows) lists items newest first, across sources or within one, each row
  with the owner’s tags overlaid. With a query, the catalog’s search strategy (its
  `search` keyword; see [`annals.search`](annals.search.html.md#module-annals.search)) picks the matching rows, best first, each
  with a `snippet` of the text around the match and, when it ranks, a `score`.
* [`Catalog.item()`](#annals.catalog.Catalog.item) is one item, [`Catalog.set_tags()`](#annals.catalog.Catalog.set_tags) replaces its tags (in the tag
  store, never in the item), [`Catalog.tag_counts()`](#annals.catalog.Catalog.tag_counts) lists every tag in use.

Facets (kind, session, date, tag) are not computed here: the page counts them over the rows
it received, so every toggle is instant and the counts are always the ones the current
query would give.

### Functions

| [`default_tags`](#annals.catalog.default_tags)(store)                            | Where the owner's tags live by default: one JSON file under the data root (`tags/tags.json`), or a dict when the data root is not on this machine.   |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`mk_catalog`](#annals.catalog.mk_catalog)(store, \*[, sources, tags, search]) | The published documents first, then the extra sources; the owner's tags beside them.                                                                 |
| [`owner_tags`](#annals.catalog.owner_tags)(store)                              | The owner's tags (set by `annals tag` or the page), keyed by item key, as one snapshot.                                                              |
| [`purge_document`](#annals.catalog.purge_document)(store, catalog, doc_id)         | Delete a document that is in the bin for good: its files, its tags, its cached thumbnails.                                                           |
| [`with_owner_tags`](#annals.catalog.with_owner_tags)(metas, tags)                   | `metas` (documents' meta) with each one's tags replaced by the owner's, where the owner set them.                                                    |

### Classes

| [`Catalog`](#annals.catalog.Catalog)(sources, \*, tags[, search])   | Named sources plus the owner's tags, listed, searched and tagged as one collection.   |
|-----------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|

### *class* annals.catalog.Catalog(sources, \*, tags, search=<function scan_search>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Named sources plus the owner’s tags, listed, searched and tagged as one collection.

#### forget(key)

Drop an item’s tags, its search entry and any cached text (when the item itself
is gone for good).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### item(key)

One item, with what the page shows; `KeyError` if there is none.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### rows(q='', , source=None, trash=False)

Items from one source or all: newest first, or, with a query `q`, the ones
the search strategy matched, best first.

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

### annals.catalog.default_tags(store)

Where the owner’s tags live by default: one JSON file under the data root
(`tags/tags.json`), or a dict when the data root is not on this machine.

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### annals.catalog.mk_catalog(store, , sources=None, tags=None, search=None)

The published documents first, then the extra sources; the owner’s tags beside them.

`sources` maps a name to a folder path (read in place) or a `Source`; by
default the folders named in `ANNALS_SOURCES`. `tags` defaults to one JSON file
under the data root (`tags/tags.json`), or a dict when the data root is remote.
`search` answers queries (see [`annals.search`](annals.search.html.md#module-annals.search)); by default a full-text index
kept under the data root, or a plain scan when the data root is remote.
The API, and any CLI or agent tool that tags items, build their catalog here.

* **Return type:**
  [`Catalog`](#annals.catalog.Catalog)

### annals.catalog.owner_tags(store)

The owner’s tags (set by `annals tag` or the page), keyed by item key, as one snapshot.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### annals.catalog.purge_document(store, catalog, doc_id)

Delete a document that is in the bin for good: its files, its tags, its cached thumbnails.

`PermissionError` for one that is not in the bin. Every surface purges through here.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.catalog.with_owner_tags(metas, tags)

`metas` (documents’ meta) with each one’s tags replaced by the owner’s, where the owner set them.

```pycon
>>> with_owner_tags([{"id": "a", "tags": ["x"]}, {"id": "b", "tags": ["y"]}], {"published:a": ["z"]})
[{'id': 'a', 'tags': ['z']}, {'id': 'b', 'tags': ['y']}]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
