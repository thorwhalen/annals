# annals.tags

The owner’s tags: a `MutableMapping` from item key to tag list, kept apart from the items.

Tags the owner adds on the page are stored here, never in the items themselves: a folder
source belongs to whoever writes it (a crowsnest ledger belongs to its session), so annals
must not edit it, and a published document’s `meta.json` is the publisher’s record.
An entry, once present, is the item’s whole tag list (it replaces the item’s own tags, so
removing a tag the publisher set works too); deleting the entry falls back to them.

[`JsonTagStore`](#annals.tags.JsonTagStore), the default, is one JSON file under the data root
(`<data root>/tags/tags.json`), written atomically. Any `MutableMapping[str, list[str]]`
can replace it (`mk_api(tags=...)`), e.g. a table in a database.

### Functions

| [`normalize_tags`](#annals.tags.normalize_tags)(tags)   | Trimmed, single-spaced, de-duplicated (ignoring case), sorted; refuses junk.   |
|-------------------------------------------------------------------------|--------------------------------------------------------------------------------|

### Classes

| [`JsonTagStore`](#annals.tags.JsonTagStore)(path)   | `{item key: [tags]}` in one JSON file (see [`annals.jsonstore.JsonFileStore`](annals.jsonstore.html.md#annals.jsonstore.JsonFileStore)).   |
|-----------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|

### *class* annals.tags.JsonTagStore(path)

Bases: [`JsonFileStore`](annals.jsonstore.html.md#annals.jsonstore.JsonFileStore)

`{item key: [tags]}` in one JSON file (see [`annals.jsonstore.JsonFileStore`](annals.jsonstore.html.md#annals.jsonstore.JsonFileStore)).

Safe with several server processes on one machine; a damaged file reads as empty and is
kept aside (`tags.json.damaged`) at the next write.

#### clean(value)

The value as stored; raise `ValueError` to refuse it.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### valid(value)

Whether a value read from the file is kept (an invalid one is logged and skipped).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.tags.normalize_tags(tags)

Trimmed, single-spaced, de-duplicated (ignoring case), sorted; refuses junk.

Raises `ValueError` for a tag that is not a string, is longer than `MAX_TAG_LEN`,
holds control characters, or for more than `MAX_TAGS_PER_ITEM` tags.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
