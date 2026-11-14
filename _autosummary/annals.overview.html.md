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
an overview spends money. A host can also offer it to some readers only
(`mk_api(overviews={"me@example.com"})`, or `ANNALS_OVERVIEWS` for `annals.api.mk_app()`;
see [`readers_offered()`](#annals.overview.readers_offered)): the others get no Listen button, and the documents the feature
makes ([`made_here()`](#annals.overview.made_here)) are hidden from them. For the same reason, a current overview is not made again unless
forced, a crash after publishing does not pay twice, `work` stops at a daily limit, and a
request nobody fulfilled expires rather than spending money whenever a worker next wakes.

Run the worker on a timer. Finished request files stay in the folder and the worker writes
there, so a watcher on the folder would keep waking it.

When the command cannot work until someone acts (an expired login, a voice account out of
credit), pressing again only spends the daily limit. So the worker notices it: the same
failure, fast, from two documents in a row, marks the maker *down* with that reason (a
document failing twice is that document). An agent can mark it too, with a link to where it
is being fixed (`annals listen-down "why" --link URL`). While it is down, nothing fails or
is dropped: requests *wait* (past the daily limit too), the page says why and what to do
instead of offering a Try again, and the worker tries one of them again every few hours. The
first success, or `annals listen-down --clear`, clears the mark and queues everything that
waited.

```pycon
>>> html_to_text("<title>x</title><p>One &amp; two</p><script>no()</script><p>Three</p>")
'One & two\n\nThree'
>>> [c["characters"] for c in choices()]
[2700, 4500, 6300]
```

### Module Attributes

| [`ENV_OVERVIEWS`](#annals.overview.ENV_OVERVIEWS)     | see [`readers_offered()`](#annals.overview.readers_offered)                                                                                            |
|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`READERS_SEP`](#annals.overview.READERS_SEP)       | in `ANNALS_OVERVIEWS`, the readers are separated by this; `*` alone means every reader                                                                            |
| [`EVERY_READER`](#annals.overview.EVERY_READER)      | in `ANNALS_OVERVIEWS`, the readers are separated by this; `*` alone means every reader                                                                            |
| [`REQUEST_FILE_MODE`](#annals.overview.REQUEST_FILE_MODE) | read by the server and the worker, which may be different users                                                                                                   |
| [`DFLT_DAILY_LIMIT`](#annals.overview.DFLT_DAILY_LIMIT)  | at most this many overviews are started in any 24 hours, whoever asks                                                                                             |
| [`QUEUED_EXPIRY_S`](#annals.overview.QUEUED_EXPIRY_S)   | nobody is waiting for it now                                                                                                                                      |
| [`RUNNING_MARGIN_S`](#annals.overview.RUNNING_MARGIN_S)  | a request still running after this long has lost its worker                                                                                                       |
| [`DOWN_FILE`](#annals.overview.DOWN_FILE)         | the file marking the maker down; not `.json`, because every `.json` here is a request                                                                             |
| [`DOWN_AFTER`](#annals.overview.DOWN_AFTER)        | the same fast failure from this many documents in a row means the maker is down                                                                                   |
| [`FAST_FAILURE_S`](#annals.overview.FAST_FAILURE_S)    | the maker could not start                                                                                                                                         |
| [`PROBE_EVERY_S`](#annals.overview.PROBE_EVERY_S)     | while the maker is down, one waiting request is tried this often, to notice it works again                                                                        |
| [`MINUTES`](#annals.overview.MINUTES)           | the lengths a reader can pick, in minutes; each costs voice characters, so the set is closed                                                                      |
| [`CHARS_PER_MINUTE`](#annals.overview.CHARS_PER_MINUTE)  | spoken English at about 150 words a minute and 6 characters a word; shown as an estimate                                                                          |
| [`TAG`](#annals.overview.TAG)               | marks a document that is itself an overview, so nobody makes an overview of an overview                                                                           |
| [`WAITING`](#annals.overview.WAITING)           | made once it works again, never spent on before                                                                                                                   |
| [`FAILED_SHOWN_S`](#annals.overview.FAILED_SHOWN_S)    | a failed request is still listed as unmade for this long, so a retry is offered where the reader looks for the overview (the Audio tab), not only on the document |
| [`COMBINED_TAG`](#annals.overview.COMBINED_TAG)      | marks a document made by putting several documents' text in one, for one review of them all                                                                       |

### Functions

| [`choices`](#annals.overview.choices)()                                          | Each length on offer and what it would cost in voice characters.                                                               |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| [`combined_document`](#annals.overview.combined_document)(store, docs, \*, title[, ...])   | One document holding the text of `docs`, so a review of it covers them all.                                                    |
| [`combined_key`](#annals.overview.combined_key)(docs)                                 | Names a set of documents at their current versions, in any order.                                                              |
| [`eligible`](#annals.overview.eligible)(meta)                                     | Whether a document can be spoken: readable text, current, and not itself an overview.                                          |
| [`html_to_text`](#annals.overview.html_to_text)(html)                                 | The readable text of a page: no markup, scripts or styles.                                                                     |
| [`made_here`](#annals.overview.made_here)(meta)                                    | Whether the overview feature made this document: a spoken overview, or the text it combined to speak several documents as one. |
| [`maker_down`](#annals.overview.maker_down)(requests)                               | Why no overview can be made until someone acts, or `None` while the maker works.                                               |
| [`mark_down`](#annals.overview.mark_down)(requests[, reason, link])                | Say the maker is down, why, and where it is being fixed; keep what is not given.                                               |
| [`mark_up`](#annals.overview.mark_up)(requests)                                  | The maker works (again): clear the mark and queue what waited; return those ids.                                               |
| [`readers_offered`](#annals.overview.readers_offered)(spec)                              | Who may ask for and hear overviews: `False` (nobody), `True` (every reader), or a test.                                        |
| [`request`](#annals.overview.request)(store, requests, doc_id, \*[, ...])        | Ask for an overview of a document.                                                                                             |
| [`request_combined`](#annals.overview.request_combined)(store, requests, docs, \*, title) | Ask for ONE overview of several documents: of the document combining their text.                                               |
| [`state_of`](#annals.overview.state_of)(store, requests, meta)                    | What a page shows for a document: its request's state and what it can start.                                                   |
| [`unmade`](#annals.overview.unmade)(store, requests)                            | The overviews asked for and not (yet) made: being made, waiting, or failed recently.                                           |
| [`valid_minutes`](#annals.overview.valid_minutes)(minutes)                             | Whether this is a length on offer.                                                                                             |
| [`work`](#annals.overview.work)(store, requests, \*[, command, timeout, ...]) | Fulfil every queued request, one at a time, until none is left; return what happened.                                          |

### Classes

| [`Requests`](#annals.overview.Requests)(data_dir)   | The request files: one per document, each replaced whole so a reader never sees half.   |
|-----------------------------------------------------------------------|-----------------------------------------------------------------------------------------|

### Exceptions

| [`MakerFailed`](#annals.overview.MakerFailed)   | The overview command ran and failed: the maker's fault, not the document's.   |
|----------------------------------------------------------------|-------------------------------------------------------------------------------|

### annals.overview.CHARS_PER_MINUTE *= 900*

spoken English at about 150 words a minute and 6 characters a word; shown as an estimate

### annals.overview.COMBINED_TAG *= 'combined'*

marks a document made by putting several documents’ text in one, for one review of them all

### annals.overview.DFLT_DAILY_LIMIT *= 20*

at most this many overviews are started in any 24 hours, whoever asks

### annals.overview.DOWN_AFTER *= 2*

the same fast failure from this many documents in a row means the maker is down

### annals.overview.DOWN_FILE *= 'maker-down'*

the file marking the maker down; not `.json`, because every `.json` here is a request

### annals.overview.ENV_OVERVIEWS *= 'ANNALS_OVERVIEWS'*

see [`readers_offered()`](#annals.overview.readers_offered)

* **Type:**
  who is offered overviews, for a host built from the environment

### annals.overview.EVERY_READER *= '\*'*

in `ANNALS_OVERVIEWS`, the readers are separated by this; `*` alone means every reader

### annals.overview.FAILED_SHOWN_S *= 604800*

a failed request is still listed as unmade for this long, so a retry is offered where
the reader looks for the overview (the Audio tab), not only on the document

### annals.overview.FAST_FAILURE_S *= 120*

the maker could not start

* **Type:**
  a failure this quick never reached the work

### annals.overview.MINUTES *= (3, 5, 7)*

the lengths a reader can pick, in minutes; each costs voice characters, so the set is closed

### *exception* annals.overview.MakerFailed

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

The overview command ran and failed: the maker’s fault, not the document’s.

### annals.overview.PROBE_EVERY_S *= 10800*

while the maker is down, one waiting request is tried this often, to notice it works again

### annals.overview.QUEUED_EXPIRY_S *= 3600*

nobody is waiting for it now

* **Type:**
  a request still queued after this long is dropped

### annals.overview.READERS_SEP *= ','*

in `ANNALS_OVERVIEWS`, the readers are separated by this; `*` alone means every reader

### annals.overview.REQUEST_FILE_MODE *= 420*

read by the server and the worker, which may be different users

* **Type:**
  request files and the down mark

### annals.overview.RUNNING_MARGIN_S *= 600*

a request still running after this long has lost its worker

### *class* annals.overview.Requests(data_dir)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The request files: one per document, each replaced whole so a reader never sees half.

#### ids()

Documents with a request, oldest request first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### mark()

What the worker knows of the maker’s recent failures (see [`maker_down()`](#annals.overview.maker_down)).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### note_start(doc_id)

Logged before the money is spent, so a crash still counts against the limit.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### put_mark(mark)

Replace the mark, or remove it (`None`).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### started_today()

How many overviews were started in the last 24 hours.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### annals.overview.TAG *= 'overview'*

marks a document that is itself an overview, so nobody makes an overview of an overview

### annals.overview.WAITING *= 'waiting'*

made once it works again, never spent on before

* **Type:**
  asked for while the maker is down

### annals.overview.choices()

Each length on offer and what it would cost in voice characters.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### annals.overview.combined_document(store, docs, , title, group=None, max_bytes=None)

One document holding the text of `docs`, so a review of it covers them all.

A combined document among `docs` counts as the documents it combines. The same
documents at the same versions give the same document back, so asking twice makes one.
A new one is added to `group` when given. Raises `ValueError` when none of `docs`
has text to speak, or past `max_bytes` of text.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.overview.combined_key(docs)

Names a set of documents at their current versions, in any order.

```pycon
>>> combined_key([{"id": "b", "version": 2}, {"id": "a"}]) == combined_key([{"id": "a"}, {"id": "b", "version": 2}])
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.overview.eligible(meta)

Whether a document can be spoken: readable text, current, and not itself an overview.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.overview.html_to_text(html)

The readable text of a page: no markup, scripts or styles.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.overview.made_here(meta)

Whether the overview feature made this document: a spoken overview, or the text it
combined to speak several documents as one. These are what a reader who is not offered
overviews never sees.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.overview.maker_down(requests)

Why no overview can be made until someone acts, or `None` while the maker works.

`{"reason", "since", "link"}`: in words, from when, and where it is being fixed (or
`None`). Set by the worker once the same fast failure came from [`DOWN_AFTER`](#annals.overview.DOWN_AFTER)
documents in a row, or by hand with [`mark_down()`](#annals.overview.mark_down); cleared by the next success or
[`mark_up()`](#annals.overview.mark_up).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.overview.mark_down(requests, reason='', , link=None)

Say the maker is down, why, and where it is being fixed; keep what is not given.

For an agent that filed the task that would fix it: the page then links to it. A link
alone only adds to a mark that is already there. Raises `ValueError` otherwise, or for a
link that is not a web address.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.overview.mark_up(requests)

The maker works (again): clear the mark and queue what waited; return those ids.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.overview.readers_offered(spec)

Who may ask for and hear overviews: `False` (nobody), `True` (every reader), or a test.

`spec` is what a host passes as `overviews`: a bool, a predicate on the reader’s name
(an email, as `annals.api.reader_of()` gives it), a collection of names, or a string as
`ANNALS_OVERVIEWS` holds it (names separated by commas, `*` for every reader, empty for
nobody; `true`/`1`/`yes` and `false`/`0`/`no` mean the same as `*` and empty,
never a reader so named). Names are compared without case.

```pycon
>>> readers_offered("*"), readers_offered(""), readers_offered(None)
(True, False, False)
>>> readers_offered("true"), readers_offered(" No "), readers_offered(["*"])
(True, False, True)
>>> may = readers_offered(" Me@Example.com, ")
>>> may("me@example.com"), may("someone@example.com")
(True, False)
```

* **Return type:**
  [`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

### annals.overview.request(store, requests, doc_id, , minutes=5, force=False)

Ask for an overview of a document. Raises `ValueError` if it cannot be asked for.

Asking again while one is being made changes nothing, and neither does asking for one
that exists and is current unless `force`, so a repeat costs nothing. While the maker
is down ([`maker_down()`](#annals.overview.maker_down)), the request waits for it rather than failing.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.overview.request_combined(store, requests, docs, , title, group=None, minutes=5, max_bytes=None)

Ask for ONE overview of several documents: of the document combining their text.

Returns `{"doc": <combined document id>, "listen": <its overview state>}`. Raises
`ValueError` as [`request()`](#annals.overview.request) does, or when there is nothing to speak.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.overview.state_of(store, requests, meta)

What a page shows for a document: its request’s state and what it can start.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.overview.unmade(store, requests)

The overviews asked for and not (yet) made: being made, waiting, or failed recently.

Each is `state_of` its document plus `doc`, `title`, `created` (the document’s),
`requested` and `finished` (the last try’s). A request whose document is gone, binned
or no longer speakable is left out: nothing can be retried. Newest first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### annals.overview.valid_minutes(minutes)

Whether this is a length on offer. Exactly an int: not `True`, and not `3.0`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.overview.work(store, requests, \*, command=None, timeout=1800, daily_limit=None, doc_url=<class 'str'>)

Fulfil every queued request, one at a time, until none is left; return what happened.

A failure is recorded on its request, for the page to show, and the next one still runs.
A request made while this runs is picked up before it exits. `doc_url` turns a document
id into its page, for `{url}`. While the maker is down, requests wait, and one of them
is tried every [`PROBE_EVERY_S`](#annals.overview.PROBE_EVERY_S); once one works, those waiting run too.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
