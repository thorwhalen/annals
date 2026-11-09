# annals.listening

What each reader has heard of each audio document: percent heard, listens, where they stopped.

The page reports what was played, a few seconds at a time, as spans of the audio’s own
timeline (`[[start, end], ...]` in seconds). The server keeps the **union** of those spans
per reader and document, so the percent heard counts each second once, however often it was
replayed or skipped back to, and two devices reporting the same minute add nothing twice.
A listen is counted when playback reaches the end of audio that has been heard almost
whole ([`DONE_SHARE`](#annals.listening.DONE_SHARE)), so dragging to the end is not a listen; a report carries the
id of the play it belongs to, so a report sent twice (a retry, a page closing) counts one.

A record, per reader and document:

```default
{"heard": [[0.0, 61.5], [90.0, 120.0]], "duration": 300.0, "position": 120.0,
 "listens": 1, "done": true, "updated": "2026-11-09T10:00:00+00:00"}
```

`done` is the reader’s own mark (“I have heard this”), set or cleared from the page; it
is absent until they set it. [`status()`](#annals.listening.status) reads a record as one of [`STATUSES`](#annals.listening.STATUSES).

Records live under the data root, one JSON file per reader (`listening/<reader>.json`),
through [`annals.jsonstore.JsonFileStore`](annals.jsonstore.html.md#annals.jsonstore.JsonFileStore). [`for_reader()`](#annals.listening.for_reader) is the seam: any
`(reader) -> store` callable whose stores are [`Records`](#annals.listening.Records) can replace it
(`mk_api(listening=...)`).

```pycon
>>> merge_spans([[5, 10], [0, 3], [2, 6], [20, 20]])
[[0.0, 10.0]]
>>> rec = apply_report(None, {"spans": [[0, 30]], "duration": 100, "position": 30})
>>> percent(rec), status(rec)
(30, 'started')
>>> apply_report(None, {"spans": [[95, 100]], "duration": 100, "ended": "p0"})["listens"]  # dragged to the end
0
>>> rec = apply_report(rec, {"spans": [[30, 100]], "duration": 100, "position": 100, "ended": "p1"})
>>> rec = apply_report(rec, {"spans": [], "duration": 100, "position": 100, "ended": "p1"})
>>> percent(rec), rec["listens"], status(rec)
(100, 1, 'done')
```

### Module Attributes

| [`STATUSES`](#annals.listening.STATUSES)         | what a record reads as, in the order the page offers them as filters               |
|-------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`DONE_SHARE`](#annals.listening.DONE_SHARE)       | heard at least this share of the audio counts as done, without a listen to the end |
| [`MIN_STARTED_S`](#annals.listening.MIN_STARTED_S)    | heard less than this many seconds is not started (a stray tap on play)             |
| [`MAX_SPANS`](#annals.listening.MAX_SPANS)        | at most this many separate spans are kept; past it the closest ones are joined     |
| [`MAX_REPORT_SPANS`](#annals.listening.MAX_REPORT_SPANS) | a report holds at most this many spans                                             |
| [`MAX_DURATION_S`](#annals.listening.MAX_DURATION_S)   | longest audio a report may claim, in seconds (a sanity bound, not a feature limit) |
| [`RECENT_PLAYS`](#annals.listening.RECENT_PLAYS)     | the plays that reached the end, remembered so a retried report counts none twice   |

### Functions

| [`apply_mark`](#annals.listening.apply_mark)(record, done)            | `record` with the reader's own mark set (`True`/`False`) or cleared (`None`).       |
|--------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`apply_report`](#annals.listening.apply_report)(record, report)        | `record` with a report from the page folded in.                                     |
| [`for_reader`](#annals.listening.for_reader)(root)                    | The default seam: each reader's records in `<root>/listening/<reader>.json`.        |
| [`heard_seconds`](#annals.listening.heard_seconds)(record)               | How many distinct seconds of the audio were heard.                                  |
| [`merge_spans`](#annals.listening.merge_spans)(spans, \*[, max_spans]) | The union of `spans` as sorted, disjoint `[start, end]` pairs; empty spans dropped. |
| [`percent`](#annals.listening.percent)(record)                     | The share of the audio heard, 0 to 100 (0 while the duration is unknown).           |
| [`reader_file`](#annals.listening.reader_file)(reader)                 | The file name a reader's records are kept under: their identity, percent-encoded.   |
| [`status`](#annals.listening.status)(record)                      | `done`, `started` or `not_started`; the reader's own mark wins when set.            |
| [`summary`](#annals.listening.summary)(record)                     | A record as the page shows it: the record plus `percent` and `status`.              |

### Classes

| [`ListeningStore`](#annals.listening.ListeningStore)(path)        | One reader's records: `{doc id: record}` in one JSON file.   |
|------------------------------------------------------------------------------|--------------------------------------------------------------|
| [`Records`](#annals.listening.Records)(\*args, \*\*kwargs) | One reader's records, as the API uses them.                  |

### annals.listening.DONE_SHARE *= 0.95*

heard at least this share of the audio counts as done, without a listen to the end

### *class* annals.listening.ListeningStore(path)

Bases: [`JsonFileStore`](annals.jsonstore.html.md#annals.jsonstore.JsonFileStore)

One reader’s records: `{doc id: record}` in one JSON file.

#### valid(value)

Whether a value read from the file is kept (an invalid one is logged and skipped).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.listening.MAX_DURATION_S *= 86400*

longest audio a report may claim, in seconds (a sanity bound, not a feature limit)

### annals.listening.MAX_REPORT_SPANS *= 500*

a report holds at most this many spans

### annals.listening.MAX_SPANS *= 200*

at most this many separate spans are kept; past it the closest ones are joined

### annals.listening.MIN_STARTED_S *= 3.0*

heard less than this many seconds is not started (a stray tap on play)

### annals.listening.RECENT_PLAYS *= 20*

the plays that reached the end, remembered so a retried report counts none twice

### *class* annals.listening.Records(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

One reader’s records, as the API uses them.

#### modify(key, change)

Set `key` to `change(current or None)` atomically (`None` deletes it).

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

### annals.listening.STATUSES *= ('not_started', 'started', 'done')*

what a record reads as, in the order the page offers them as filters

### annals.listening.apply_mark(record, done)

`record` with the reader’s own mark set (`True`/`False`) or cleared (`None`).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.listening.apply_report(record, report)

`record` with a report from the page folded in. Raises `ValueError` on a bad report.

A report: `{"spans": [[a, b], ...], "duration": s, "position": s, "ended"?: play_id}`.
`ended` names the play that reached the end; each play id counts one listen.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.listening.for_reader(root)

The default seam: each reader’s records in `<root>/listening/<reader>.json`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Records`](#annals.listening.Records)]

### annals.listening.heard_seconds(record)

How many distinct seconds of the audio were heard.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### annals.listening.merge_spans(spans, , max_spans=200)

The union of `spans` as sorted, disjoint `[start, end]` pairs; empty spans dropped.

Past `max_spans` pairs, the ones with the smallest gap between them are joined, so a
record stays small whatever a reader does (the percent heard can only grow by that).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### annals.listening.percent(record)

The share of the audio heard, 0 to 100 (0 while the duration is unknown).

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### annals.listening.reader_file(reader)

The file name a reader’s records are kept under: their identity, percent-encoded.

The encoding is one-to-one, so two readers never share a file, and never a path.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.listening.status(record)

`done`, `started` or `not_started`; the reader’s own mark wins when set.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.listening.summary(record)

A record as the page shows it: the record plus `percent` and `status`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
