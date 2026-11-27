# annals.search

How the catalog answers a query: the search strategies.

A strategy is a callable `(query, rows, text_of) -> rows`: given every listed row (the
catalog has already listed them and overlaid the owner’s tags) and a way to get an item’s
full text, it returns the rows that match, best first, each with a `snippet` of the
text around the match and, when it ranks, a `score` (higher is better). The catalog
takes one as its `search` keyword ([`annals.catalog.Catalog`](annals.catalog.html.md#annals.catalog.Catalog)), so a smarter one
(semantic, hybrid, an agent that rewrites the query) plugs in at the same place.

Two ship here:

* [`IndexedSearch`](#annals.search.IndexedSearch), the default when the data root is on this machine: a SQLite
  FTS5 index kept on disk (`cache/search/index.sqlite` under the data root). Each query
  brings it up to date first, re-reading only items whose stamp changed (their listed
  fields, and the `stamp` a source gives, else their time and size),
  so the first query after a restart costs one pass over the texts and every later one a
  few milliseconds. Matching is by word prefix with English stemming (`rate` finds
  “rates” and “rated”, not “separate”), every word required, ranked by BM25 with the
  title weighted most.
* [`scan_search()`](#annals.search.scan_search), the index-free fallback (a remote data root, tests): every word
  must appear as a substring of the title, tags, session, excerpt, id or full text;
  newest first, as listed.

### Module Attributes

| [`SNIPPET_CHARS`](#annals.search.SNIPPET_CHARS)   | characters of context on each side of the first match, in a snippet                  |
|------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`SNIPPET_TOKENS`](#annals.search.SNIPPET_TOKENS)  | tokens in an index snippet (FTS5's own window)                                       |
| [`SNIPPET_ROWS`](#annals.search.SNIPPET_ROWS)    | the best rows that get a snippet (each costs ~5 ms); the rest show their excerpt.    |
| [`MAX_RESULTS`](#annals.search.MAX_RESULTS)     | the most rows a ranked query returns; the page shows a few dozen at a time           |
| [`DFLT_WEIGHTS`](#annals.search.DFLT_WEIGHTS)    | column weights for BM25, in the order of `_COLUMNS` (the title matters most)         |
| [`INDEX_DIR`](#annals.search.INDEX_DIR)       | where index files live, under the data root (`<name>.sqlite`)                        |
| [`SCHEMA_VERSION`](#annals.search.SCHEMA_VERSION)  | an old index is rebuilt                                                              |
| [`WINDOW_CHARS`](#annals.search.WINDOW_CHARS)    | characters of the body kept around the match for rows past `snippet_rows`            |
| [`SYNC_BATCH`](#annals.search.SYNC_BATCH)      | rows indexed per write transaction, so a first build never holds the lock for long   |
| [`SQL_VARS`](#annals.search.SQL_VARS)        | bound variables per statement (SQLite's default limit is far above; this stays safe) |

### Functions

| [`default_search`](#annals.search.default_search)(data_root, \*[, name])    | The index `<data root>/cache/search/<name>.sqlite` when the data root is on this machine, else the scan.   |
|-------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|
| [`fts_query`](#annals.search.fts_query)(q)                             | A user's words as an FTS5 query: every word required, each a prefix.                                       |
| [`query_words`](#annals.search.query_words)(q)                           | The words of a query, lowercased: `"Data  Rates"` -> `["data", "rates"]`.                                  |
| [`scan_search`](#annals.search.scan_search)(query, rows, text_of)        | Every word a substring of the row's fields or full text; rows kept in their order.                         |
| [`snippet_around`](#annals.search.snippet_around)(text, words, \*[, width]) | The text around the first occurrence of any of `words`, on one line.                                       |

### Classes

| [`IndexedSearch`](#annals.search.IndexedSearch)([path, weights, max_results, ...])   | A SQLite FTS5 index of every row's fields and text, synced per query by stamp.   |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`SearchStrategy`](#annals.search.SearchStrategy)(\*args, \*\*kwargs)                 | `(query, rows, text_of) -> matching rows, best first`.                           |

### annals.search.DFLT_WEIGHTS *= (10.0, 5.0, 2.0, 1.0, 1.0)*

column weights for BM25, in the order of `_COLUMNS` (the title matters most)

### annals.search.INDEX_DIR *= 'cache/search'*

where index files live, under the data root (`<name>.sqlite`)

### *class* annals.search.IndexedSearch(path=':memory:', , weights=(10.0, 5.0, 2.0, 1.0, 1.0), max_results=500, snippet_tokens=24, snippet_rows=60)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A SQLite FTS5 index of every row’s fields and text, synced per query by stamp.

`path` is the index file (made on first use; `":memory:"` keeps it in memory).
`weights` are BM25’s per-column weights (title, tags, session/id/source, excerpt,
text). `max_results` caps a ranked answer; the best `snippet_rows` carry FTS5’s
snippet, the rest a cheaper window of text around the query’s longest word. Safe
across threads (one sync at a time: queries that arrive during a sync wait for it
rather than redo it) and across processes sharing the file (two web workers): every
write is one short `BEGIN IMMEDIATE` transaction. If the index fails (a locked or
damaged file), a query falls back to [`scan_search()`](#annals.search.scan_search) rather than fail.

#### forget(key)

Drop an item from the index (it is gone for good).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### sync(rows, text_of)

(Re)index the rows whose stamp changed; returns how many.

Nothing is dropped here: a query only ever answers with the rows it was given, so
an item listed elsewhere (in the bin, behind a hiding store, or gone) simply does
not come back. [`forget()`](#annals.search.IndexedSearch.forget) drops an item for good.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### annals.search.MAX_RESULTS *= 500*

the most rows a ranked query returns; the page shows a few dozen at a time

### annals.search.SCHEMA_VERSION *= '3'*

an old index is rebuilt

* **Type:**
  bumped when the schema or what is indexed changes

### annals.search.SNIPPET_CHARS *= 90*

characters of context on each side of the first match, in a snippet

### annals.search.SNIPPET_ROWS *= 60*

the best rows that get a snippet (each costs ~5 ms); the rest show their excerpt.
One page of the list (the page’s `LIST_PAGE`).

### annals.search.SNIPPET_TOKENS *= 24*

tokens in an index snippet (FTS5’s own window)

### annals.search.SQL_VARS *= 500*

bound variables per statement (SQLite’s default limit is far above; this stays safe)

### annals.search.SYNC_BATCH *= 200*

rows indexed per write transaction, so a first build never holds the lock for long

### *class* annals.search.SearchStrategy(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

`(query, rows, text_of) -> matching rows, best first`.

`rows` are what the reader may see (a strategy never answers with anything else);
`text_of(row)` reads an item’s full text. A strategy that keeps state about items
may also have `forget(key)`, which the catalog calls when an item is gone for good.

### annals.search.WINDOW_CHARS *= 90*

characters of the body kept around the match for rows past `snippet_rows`

### annals.search.default_search(data_root, , name='index')

The index `<data root>/cache/search/<name>.sqlite` when the data root is on this
machine, else the scan.

* **Return type:**
  [`SearchStrategy`](#annals.search.SearchStrategy)

### annals.search.fts_query(q)

A user’s words as an FTS5 query: every word required, each a prefix.

Each word is quoted, so FTS5 syntax typed by the user (`AND`, `-`, `:`, quotes)
is searched for as text, never run as an operator. Control characters are dropped,
and so is a word with no letter or digit (the tokenizer would drop it anyway, and an
empty phrase matches nothing), so a query of only punctuation is no query.

```pycon
>>> fts_query('data rates')
'"data"* "rates"*'
>>> fts_query('a"b NOT')
'"a""b"* "not"*'
>>> fts_query('  ... - *')
''
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.search.query_words(q)

The words of a query, lowercased: `"Data  Rates"` -> `["data", "rates"]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.search.scan_search(query, rows, text_of)

Every word a substring of the row’s fields or full text; rows kept in their order.

The full text is read only for rows whose fields lack a word.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### annals.search.snippet_around(text, words, , width=90)

The text around the first occurrence of any of `words`, on one line.

```pycon
>>> snippet_around("alpha beta gamma", ["beta"], width=6)
'alpha beta g…'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
