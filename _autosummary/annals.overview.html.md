# annals.overview

Spoken overviews of a document: the request a page makes, and the worker that fulfils it.

A reader asks for an overview from a document’s page. That writes one small JSON file under
the data root (`overviews/<doc id>.json`). A worker on the same machine reads the document
from the store, runs a command that makes the overview, and publishes the result as a
document of its own. The page polls the request’s state.

annals does not know how an overview is made. The command is the seam: any program that
takes a text file and writes one HTML page, named in `ANNALS_OVERVIEW_COMMAND` or passed to
[`work()`](#annals.overview.work), with `{source}`, `{minutes}` and `{out}` filled in, and `{url}`, the source document’s
page, so the overview can link to what it was based on:

```default
my-overview {source} --minutes {minutes} --player-to {out} --source-url {url}
```

The feature is off unless the host turns it on (`mk_api(overviews=True)`), because making
an overview spends money. For the same reason, a current overview is not made again unless
forced, a crash after publishing does not pay twice, `work` stops at a daily limit, and a
request nobody fulfilled expires rather than spending money whenever a worker next wakes.

Run the worker on a timer. Finished request files stay in the folder and the worker writes
there, so a watcher on the folder would keep waking it.

```pycon
>>> html_to_text("<title>x</title><p>One &amp; two</p><script>no()</script><p>Three</p>")
'One & two\n\nThree'
>>> [c["characters"] for c in choices()]
[2700, 4500, 6300]
```

### Module Attributes

| [`DFLT_DAILY_LIMIT`](#annals.overview.DFLT_DAILY_LIMIT)   | at most this many overviews are started in any 24 hours, whoever asks                        |
|---------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| [`QUEUED_EXPIRY_S`](#annals.overview.QUEUED_EXPIRY_S)    | nobody is waiting for it now                                                                 |
| [`RUNNING_MARGIN_S`](#annals.overview.RUNNING_MARGIN_S)   | a request still running after this long has lost its worker                                  |
| [`MINUTES`](#annals.overview.MINUTES)            | the lengths a reader can pick, in minutes; each costs voice characters, so the set is closed |
| [`CHARS_PER_MINUTE`](#annals.overview.CHARS_PER_MINUTE)   | spoken English at about 150 words a minute and 6 characters a word; shown as an estimate     |
| [`TAG`](#annals.overview.TAG)                | marks a document that is itself an overview, so nobody makes an overview of an overview      |

### Functions

| [`choices`](#annals.overview.choices)()                                          | Each length on offer and what it would cost in voice characters.                      |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| [`eligible`](#annals.overview.eligible)(meta)                                     | Whether a document can be spoken: readable text, current, and not itself an overview. |
| [`html_to_text`](#annals.overview.html_to_text)(html)                                 | The readable text of a page: no markup, scripts or styles.                            |
| [`request`](#annals.overview.request)(store, requests, doc_id, \*[, ...])        | Ask for an overview of a document.                                                    |
| [`state_of`](#annals.overview.state_of)(store, requests, meta)                    | What a page shows for a document: its request's state and what it can start.          |
| [`valid_minutes`](#annals.overview.valid_minutes)(minutes)                             | Whether this is a length on offer.                                                    |
| [`work`](#annals.overview.work)(store, requests, \*[, command, timeout, ...]) | Fulfil every queued request, one at a time, until none is left; return what happened. |

### Classes

| [`Requests`](#annals.overview.Requests)(data_dir)   | The request files: one per document, each replaced whole so a reader never sees half.   |
|-----------------------------------------------------------------------|-----------------------------------------------------------------------------------------|

### annals.overview.CHARS_PER_MINUTE *= 900*

spoken English at about 150 words a minute and 6 characters a word; shown as an estimate

### annals.overview.DFLT_DAILY_LIMIT *= 20*

at most this many overviews are started in any 24 hours, whoever asks

### annals.overview.MINUTES *= (3, 5, 7)*

the lengths a reader can pick, in minutes; each costs voice characters, so the set is closed

### annals.overview.QUEUED_EXPIRY_S *= 3600*

nobody is waiting for it now

* **Type:**
  a request still queued after this long is dropped

### annals.overview.RUNNING_MARGIN_S *= 600*

a request still running after this long has lost its worker

### *class* annals.overview.Requests(data_dir)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The request files: one per document, each replaced whole so a reader never sees half.

#### ids()

Documents with a request, oldest request first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### note_start(doc_id)

Logged before the money is spent, so a crash still counts against the limit.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### started_today()

How many overviews were started in the last 24 hours.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### annals.overview.TAG *= 'overview'*

marks a document that is itself an overview, so nobody makes an overview of an overview

### annals.overview.choices()

Each length on offer and what it would cost in voice characters.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### annals.overview.eligible(meta)

Whether a document can be spoken: readable text, current, and not itself an overview.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.overview.html_to_text(html)

The readable text of a page: no markup, scripts or styles.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.overview.request(store, requests, doc_id, , minutes=5, force=False)

Ask for an overview of a document. Raises `ValueError` if it cannot be asked for.

Asking again while one is being made changes nothing, and neither does asking for one
that exists and is current unless `force`, so a repeat costs nothing.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.overview.state_of(store, requests, meta)

What a page shows for a document: its request’s state and what it can start.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.overview.valid_minutes(minutes)

Whether this is a length on offer. Exactly an int: not `True`, and not `3.0`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.overview.work(store, requests, \*, command=None, timeout=1800, daily_limit=None, doc_url=<class 'str'>)

Fulfil every queued request, one at a time, until none is left; return what happened.

A failure is recorded on its request, for the page to show, and the next one still runs.
A request made while this runs is picked up before it exits. `doc_url` turns a document
id into its page, for `{url}`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
