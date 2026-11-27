# annals.highlights

Each reader’s highlights: passages of documents kept with a name, tags and a note.

A reader selects text on a document’s page and keeps it. The page side is the
[manicules](https://github.com/thorwhalen/manicules) widget (vendored under
`ui/vendor/manicules/`); this module is the server side it talks to: what a highlight is
allowed to be, where each reader’s are kept, and how they are searched. A highlight of a
document’s whole title keeps the document itself, which is how a reader marks a favourite.

A highlight, as stored (the shape of manicules’ `highlight.schema.json`):

```default
{"id": "hmf3k2x9a1b2c3", "name": "Bread notes-highlight-1",
 "target": {"source": {"id": "<doc id>", "title": "Bread notes", "url": "d/<doc id>"},
            "part": "body",
            "quote": {"exact": "85 percent water", "prefix": "A rye loaf takes ", "suffix": ", and"},
            "position": {"start": 310, "end": 327}},
 "comment": "the number I keep forgetting", "tags": ["rye"], "color": "green",
 "created": "2026-11-27T10:00:00+00:00"}
```

The target is two W3C Web Annotation selectors (the quote with its context, and where it
was): the page finds the passage again from them after the document changed. `whole` in a
target means the entire part, whatever it says now. The server never interprets a target;
it bounds its size and keeps it.

Records live under the data root, one JSON file per reader
(`highlights/<reader>.json`, `{id: highlight}`, the layout manicules’ own file store and
CLI use), through [`annals.jsonstore.JsonFileStore`](annals.jsonstore.html.md#annals.jsonstore.JsonFileStore); each reader’s two settings (the
default colour, and whether a page shows all its highlights when it opens) are beside them
(`highlight-settings/<reader>.json`). [`for_reader()`](#annals.highlights.for_reader) is the seam: any
`(reader) -> ReaderHighlights` callable can replace it (`mk_api(highlights=...)`), its
records being anything with the three calls of [`Records`](#annals.highlights.Records). The routes the widget
talks to are `annals.highlights_api.mk_router()`.

```pycon
>>> rec = clean({"target": {"source": {"id": "d1", "title": "Notes"}, "quote": {"exact": "three sites"}}},
...             names=["Notes-highlight-1"], now="2026-11-27T10:00:00+00:00", new_id=lambda: "h1")
>>> rec["name"], rec["target"]["part"], rec["tags"], rec["comment"]
('Notes-highlight-2', 'body', [], '')
>>> [h["id"] for h in search({"h1": rec}, "SITES notes")]
['h1']
>>> search({"h1": rec}, "sites absent")
[]
>>> clean_patch({"comment": "why", "color": None, "tags": ["b", "A", "a"]})
{'comment': 'why', 'color': None, 'tags': ['A', 'b']}
```

### Module Attributes

| [`ENV_READER`](#annals.highlights.ENV_READER)       | the reader an agent surface (the CLI, the MCP server) answers for when none is named     |
|-------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| [`PALETTE`](#annals.highlights.PALETTE)          | the colours a highlight may have (manicules' palette; each is legible in light and dark) |
| [`DEFAULT_SETTINGS`](#annals.highlights.DEFAULT_SETTINGS) | what a reader gets before choosing anything                                              |
| [`MAX_HIGHLIGHTS`](#annals.highlights.MAX_HIGHLIGHTS)   | the file is read whole on every page                                                     |
| [`MAX_STORE_BYTES`](#annals.highlights.MAX_STORE_BYTES)  | every list, search and page view reads it whole                                          |
| [`RESERVED_IDS`](#annals.highlights.RESERVED_IDS)     | ids the API's own routes use (`/highlights/settings`)                                    |
| [`PATCHABLE`](#annals.highlights.PATCHABLE)        | the fields a reader may change afterwards; the target never changes                      |

### Functions

| [`add`](#annals.highlights.add)(records, data)                    | Keep a new highlight.                                                                                                       |
|----------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| [`apply_patch`](#annals.highlights.apply_patch)(record, patch, \*[, now]) | `record` with a cleaned patch applied; a `None` colour goes back to the default.                                            |
| [`clean`](#annals.highlights.clean)(data, \*[, names, now, new_id]) | A complete highlight from what a caller sent, validated and bounded.                                                        |
| [`clean_patch`](#annals.highlights.clean_patch)(patch)                    | What a reader may change ([`PATCHABLE`](#annals.highlights.PATCHABLE)), validated; anything else is refused. |
| [`clean_settings`](#annals.highlights.clean_settings)(patch)                 | The settings a reader may set, validated: `color` and `showOthers`.                                                         |
| [`clean_target`](#annals.highlights.clean_target)(target)                  | A target as stored: its source, its part, and the selectors, each bounded.                                                  |
| [`default_name`](#annals.highlights.default_name)(title[, names])          | `<title>-highlight-<n>`, `n` the first number no highlight of that page uses.                                               |
| [`edit`](#annals.highlights.edit)(records, hid, patch)             | Change a highlight's name, note, tags or colour.                                                                            |
| [`for_reader`](#annals.highlights.for_reader)(root)                      | The default seam: `<root>/highlights/<reader>.json` and `highlight-settings/`.                                              |
| [`href`](#annals.highlights.href)(record)                          | A highlight's page, opened on it, relative to the page's base (`""` when it names none).                                    |
| [`new_id`](#annals.highlights.new_id)()                              | A new id: sortable by creation time, unique enough for one reader's collection.                                             |
| [`read_records`](#annals.highlights.read_records)(target, reader)          | One reader's highlights by id, read through a `Target` (a local folder, or over ssh): for a caller that only reads.         |
| [`readers`](#annals.highlights.readers)(target)                       | Who has highlights under a data root, read through its `Target` (so over ssh too).                                          |
| [`remove`](#annals.highlights.remove)(records, hid)                  | Delete a highlight and return it.                                                                                           |
| [`search`](#annals.highlights.search)(records[, q, source, tag])     | The highlights matching every word of `q` (case ignored), newest first.                                                     |
| [`search_text`](#annals.highlights.search_text)(record)                   | What a highlight is found by: its name, passage, note, tags and its page's title.                                           |
| [`settings_of`](#annals.highlights.settings_of)(store)                    | A reader's settings over the defaults (a stored value of the wrong kind is ignored).                                        |

### Classes

| [`HighlightStore`](#annals.highlights.HighlightStore)(path)                | One reader's highlights: `{id: highlight}` in one JSON file.                                                                                                                                        |
|--------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`ReaderHighlights`](#annals.highlights.ReaderHighlights)(records, settings) | What the API keeps for one reader: the highlights ([`Records`](#annals.highlights.Records)), and the settings beside them (a mapping of setting name to value, with `snapshot()`). |
| [`Records`](#annals.highlights.Records)(\*args, \*\*kwargs)         | One reader's highlights, as this module and the API use them: any store with these three calls can stand behind the seam (a table in a database as well as a file).                                 |
| [`SettingsStore`](#annals.highlights.SettingsStore)(path)                 | One reader's settings: `{setting: value}` in one JSON file.                                                                                                                                         |

### annals.highlights.DEFAULT_SETTINGS *= {'color': 'yellow', 'showOthers': True}*

what a reader gets before choosing anything

### annals.highlights.ENV_READER *= 'ANNALS_HIGHLIGHTS_READER'*

the reader an agent surface (the CLI, the MCP server) answers for when none is named

### *class* annals.highlights.HighlightStore(path)

Bases: [`JsonFileStore`](annals.jsonstore.html.md#annals.jsonstore.JsonFileStore)

One reader’s highlights: `{id: highlight}` in one JSON file.

#### has_room()

Whether another highlight may be added: the file is read whole on every page,
so it is bounded in bytes ([`MAX_STORE_BYTES`](#annals.highlights.MAX_STORE_BYTES)) as well as in number.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### valid(value)

Whether a value read from the file is kept (an invalid one is logged and skipped).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.highlights.MAX_HIGHLIGHTS *= 5000*

the file is read whole on every page

* **Type:**
  at most this many highlights per reader

### annals.highlights.MAX_STORE_BYTES *= 20000000*

every list, search and page view reads it whole

* **Type:**
  and their file at most this big

### annals.highlights.PALETTE *= ('yellow', 'green', 'blue', 'pink', 'orange', 'purple')*

the colours a highlight may have (manicules’ palette; each is legible in light and dark)

### annals.highlights.PATCHABLE *= ('name', 'comment', 'tags', 'color')*

the fields a reader may change afterwards; the target never changes

### annals.highlights.RESERVED_IDS *= frozenset({'settings'})*

ids the API’s own routes use (`/highlights/settings`)

### *class* annals.highlights.ReaderHighlights(records, settings)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What the API keeps for one reader: the highlights ([`Records`](#annals.highlights.Records)), and the
settings beside them (a mapping of setting name to value, with `snapshot()`).

### *class* annals.highlights.Records(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

One reader’s highlights, as this module and the API use them: any store with these
three calls can stand behind the seam (a table in a database as well as a file).

#### modify(key, change)

Set `key` to `change(current or None)` atomically (`None` deletes it).

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

### *class* annals.highlights.SettingsStore(path)

Bases: [`JsonFileStore`](annals.jsonstore.html.md#annals.jsonstore.JsonFileStore)

One reader’s settings: `{setting: value}` in one JSON file.

#### valid(value)

Whether a value read from the file is kept (an invalid one is logged and skipped).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.highlights.add(records, data)

Keep a new highlight. Raises `ValueError` when it is invalid, when its id is taken,
or when the reader already has [`MAX_HIGHLIGHTS`](#annals.highlights.MAX_HIGHLIGHTS).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.highlights.apply_patch(record, patch, , now=None)

`record` with a cleaned patch applied; a `None` colour goes back to the default.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.highlights.clean(data, \*, names=(), now=None, new_id=<function new_id>)

A complete highlight from what a caller sent, validated and bounded.

`names` are the names of the page’s other highlights, for the default name. An `id`
or `created` the caller sent is kept when well formed (the page makes the id, so an
undo puts back the very same highlight); unknown fields are dropped.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.highlights.clean_patch(patch)

What a reader may change ([`PATCHABLE`](#annals.highlights.PATCHABLE)), validated; anything else is refused.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.highlights.clean_settings(patch)

The settings a reader may set, validated: `color` and `showOthers`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.highlights.clean_target(target)

A target as stored: its source, its part, and the selectors, each bounded.

Raises `ValueError` for a target with no source id, with neither a quote nor
`whole`, or with a field of the wrong kind or size.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.highlights.default_name(title, names=())

`<title>-highlight-<n>`, `n` the first number no highlight of that page uses.

```pycon
>>> default_name("Notes", ["a", "Notes-highlight-3"])
'Notes-highlight-4'
>>> default_name("  ")
'page-highlight-1'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.highlights.edit(records, hid, patch)

Change a highlight’s name, note, tags or colour. `KeyError` when there is none.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.highlights.for_reader(root)

The default seam: `<root>/highlights/<reader>.json` and `highlight-settings/`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ReaderHighlights`](#annals.highlights.ReaderHighlights)]

### annals.highlights.href(record)

A highlight’s page, opened on it, relative to the page’s base (`""` when it names none).

The one place that address is built: the API’s `href`, the CLI’s `url` and the page
all come from here.

```pycon
>>> href({"id": "h1", "target": {"source": {"id": "d1", "url": "d/d1?f=a.md"}}})
'd/d1?f=a.md&h=h1'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.highlights.new_id()

A new id: sortable by creation time, unique enough for one reader’s collection.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.highlights.read_records(target, reader)

One reader’s highlights by id, read through a `Target` (a local folder, or over
ssh): for a caller that only reads. The one other place that knows the file layout is
[`for_reader()`](#annals.highlights.for_reader).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### annals.highlights.readers(target)

Who has highlights under a data root, read through its `Target` (so over ssh too).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.highlights.remove(records, hid)

Delete a highlight and return it. `KeyError` when there is none.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.highlights.search(records, q='', , source=None, tag=None)

The highlights matching every word of `q` (case ignored), newest first.

`source` keeps one page’s (its source id), `tag` the ones carrying a tag. This is
the function a wider search calls to list a reader’s highlights beside documents.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### annals.highlights.search_text(record)

What a highlight is found by: its name, passage, note, tags and its page’s title.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.highlights.settings_of(store)

A reader’s settings over the defaults (a stored value of the wrong kind is ignored).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
