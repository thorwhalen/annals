# annals.docfilter

Exact filters over a document’s meta, for a caller that polls: since, session, tag, source.

One place for the rules, so the CLI (`annals ls`), MCP and the HTTP `/docs` route cannot
drift: `since` is an ISO date or time (local time unless it has an offset) or an age
(`6h`, `2d`); `session`, `tag` and each `source` key match whole values, never
substrings; all given filters must hold. They are pure: the caller lists the documents (and
puts the owner’s tags in, [`annals.catalog.with_owner_tags()`](annals.catalog.html.md#annals.catalog.with_owner_tags)) and this narrows them.

```pycon
>>> docs = [{"id": "a", "tags": ["x"], "created": "2026-11-12T10:00:00+00:00", "source": {"session": "s1"}},
...         {"id": "b", "tags": ["y"], "created": "2026-11-10T10:00:00+00:00", "source": {"session": "s2"}}]
>>> [d["id"] for d in DocFilter.of(since="2026-11-11T00:00:00+00:00").apply(docs)]
['a']
>>> [d["id"] for d in DocFilter.of(session="s2", tag="y").apply(docs)]
['b']
```

### Module Attributes

| [`RESERVED_META`](#annals.docfilter.RESERVED_META)   | provenance annals fills in itself; `--meta` cannot overwrite it   |
|------------------------------------------------------------------|-------------------------------------------------------------------|

### Functions

| [`changed_at`](#annals.docfilter.changed_at)(meta)                 | When a document last changed: a replaced one counts from its newest version.                       |
|-----------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| [`parse_iso`](#annals.docfilter.parse_iso)(text)                  | An ISO date or time as an aware datetime; one with no offset is local time.                        |
| [`parse_meta`](#annals.docfilter.parse_meta)(meta, \*[, reserved]) | `["corpus=x", "issue=12"]` (or one such string) as `{"corpus": "x", "issue": "12"}`.               |
| [`parse_since`](#annals.docfilter.parse_since)(since, \*[, now])    | A moment, as an aware datetime: an ISO date or time (local time when it has no offset), or an age. |

### Classes

| [`DocFilter`](#annals.docfilter.DocFilter)([since, session, tag, source])   | What a caller wants of a listing: any of since, session, tag and source keys; empty means all.   |
|---------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|

### *class* annals.docfilter.DocFilter(since=None, session=None, tag=None, source=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a caller wants of a listing: any of since, session, tag and source keys; empty means all.

#### apply(docs)

The documents that pass, in their order.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### matches(doc)

Whether `doc` (a meta) passes every filter that was given.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### *classmethod* of(, since=None, session=None, tag=None, meta=None)

From the CLI’s spelling: `since` text, `meta` as `key=value` strings.

* **Return type:**
  [`DocFilter`](#annals.docfilter.DocFilter)

### annals.docfilter.RESERVED_META *= frozenset({'cwd', 'host', 'session', 'session_url'})*

provenance annals fills in itself; `--meta` cannot overwrite it

### annals.docfilter.changed_at(meta)

When a document last changed: a replaced one counts from its newest version.

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.docfilter.parse_iso(text)

An ISO date or time as an aware datetime; one with no offset is local time.

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)

### annals.docfilter.parse_meta(meta, , reserved=frozenset({'cwd', 'host', 'session', 'session_url'}))

`["corpus=x", "issue=12"]` (or one such string) as `{"corpus": "x", "issue": "12"}`.

A key in `reserved` (what annals records itself) is refused: writing it would forge
provenance. A filter reads any key, so it passes `reserved=frozenset()`.

```pycon
>>> parse_meta(["corpus=annals", "issue=64"])
{'corpus': 'annals', 'issue': '64'}
>>> parse_meta(None)
{}
>>> parse_meta("oops")
Traceback (most recent call last):
...
ValueError: --meta takes key=value (for example corpus=annals), got 'oops'
>>> parse_meta(["host=h"])
Traceback (most recent call last):
...
ValueError: --meta cannot set 'host': annals records it (use --session for the session)
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.docfilter.parse_since(since, , now=None)

A moment, as an aware datetime: an ISO date or time (local time when it has no offset), or an age.

```pycon
>>> parse_since("2026-11-12T09:00+00:00").isoformat()
'2026-11-12T09:00:00+00:00'
>>> parse_since("2d", now=datetime(2026, 11, 14, tzinfo=timezone.utc)).date().isoformat()
'2026-11-12'
```

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)
