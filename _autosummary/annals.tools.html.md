# annals.tools

The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This module is the single source of truth for what a annals can do. The CLI
(`annals.__main__`, via `cw`), the MCP server (`py2mcp` over string refs to these
names) and the shipped skill all describe the same functions, so there is nothing to keep
in parity. Nothing here prints or exits; the surfaces do that.

### Module Attributes

| [`LINK_CHECKED_SUFFIXES`](#annals.tools.LINK_CHECKED_SUFFIXES)   | the suffixes whose text the link check reads (prose an author writes by hand)                                               |
|--------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| [`LINKS_READ_SUFFIXES`](#annals.tools.LINKS_READ_SUFFIXES)     | the suffixes whose text [`show()`](#annals.tools.show) reads for the annals links a document makes |
| [`LINKS_MAX_FILES`](#annals.tools.LINKS_MAX_FILES)         | [`show()`](#annals.tools.show) reads at most this many of a document's text files for links ...    |
| [`LINKS_MAX_FILE_BYTES`](#annals.tools.LINKS_MAX_FILE_BYTES)    |                                                                                                                             |
| [`EFFECTS`](#annals.tools.EFFECTS)                 | a surface serves the levels its caller allows.                                                                              |
| [`DFLT_EFFECTS`](#annals.tools.DFLT_EFFECTS)            | what an agent or a tool is offered unless its host asks for more (MCP reads this)                                           |

### Functions

| [`aggregate`](#annals.tools.aggregate)(group_id, \*[, format, output, ...])     | The files of a group (or one document) as ONE markdown, html or pdf file (nothing is stored).             |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| [`configure`](#annals.tools.configure)(\*[, target, base_url, to, outbox, ...]) | Write the publisher config (where to publish, what link to print) and show it.                            |
| [`copy`](#annals.tools.copy)(refs, \*, to[, source, target, base_url])     | Copy documents or groups to a named target, keeping their ids; print the new link.                        |
| [`export`](#annals.tools.export)(doc_id, \*[, format, file, output, ...])    | One markdown file of a document as a `.md` or a titled `.pdf`, as the page's Export gives it.             |
| [`group`](#annals.tools.group)(title, doc_ids, \*[, add_to, target, ...])   | Make a group (one URL for a set of documents) from existing document ids.                                 |
| [`groups`](#annals.tools.groups)(\*[, target, base_url, to])                 | List groups, newest first.                                                                                |
| [`listen`](#annals.tools.listen)(doc_id, \*[, minutes, force, also, ...])    | Ask for a spoken overview of a document, as its page's Listen button does.                                |
| [`listen_down`](#annals.tools.listen_down)([reason, link, clear, target, to])     | Say why spoken overviews cannot be made, and where that is being fixed; or clear it.                      |
| [`listen_work`](#annals.tools.listen_work)(\*[, command, target, to])             | Fulfil the queued overview requests, one at a time (a timer runs this on the server).                     |
| [`ls`](#annals.tools.ls)([q, trash, limit, target, base_url, to, ...])   | List documents (newest first), optionally filtered by words or showing the bin.                           |
| [`overview_state`](#annals.tools.overview_state)(doc_id, \*[, target, to])           | Where a document's spoken overview stands (not asked for, queued, made, failed), without asking for one.  |
| [`page_shell`](#annals.tools.page_shell)(\*[, api, base, title])                 | The page's html shell, for a host that serves the API under its own prefix.                               |
| [`publish`](#annals.tools.publish)(paths, \*[, title, tags, group, ...])      | Publish one document and print its link; several paths become several documents.                          |
| [`purge`](#annals.tools.purge)(doc_ids, \*[, target, to])                   | Delete documents that are in the bin for good (not restorable).                                           |
| [`references`](#annals.tools.references)(ref, \*[, form, also, target, to])      | The references of a document or a group, as its page's References action gives them.                      |
| [`restore`](#annals.tools.restore)(doc_ids, \*[, target, to])                 | Bring documents back from the recycle bin.                                                                |
| [`serve`](#annals.tools.serve)(\*[, host, port, data_dir, base_path, ...])  | Serve the annals page and API (needs `pip install 'annals[server]'`).                                     |
| [`share`](#annals.tools.share)(ref, \*[, password, expires, include, ...])  | Make a public link to ONE document (or group) and print it; nothing else is reachable.                    |
| [`shareable`](#annals.tools.shareable)(doc_id, \*[, target, to])                | What the Share dialog offers for a document: its files, and the other annals documents its text links to. |
| [`shares`](#annals.tools.shares)(\*[, all, target, base_url, to])            | List share links, newest first (`all`: revoked and expired ones too).                                     |
| [`show`](#annals.tools.show)(doc_id, \*[, target, base_url, to])           | A document's metadata, link, the groups it is in, and the annals links in its text.                       |
| [`tag`](#annals.tools.tag)(doc_id, tags, \*[, target, to])                | Set a document's tags (comma separated; "" clears them), as the page's tag editor does.                   |
| [`tools_with`](#annals.tools.tools_with)([effects])                              | The operations whose effect is in `effects`, in the CLI's order: the list a caller-facing surface serves. |
| [`trash`](#annals.tools.trash)(doc_ids, \*[, target, to])                   | Move documents to the recycle bin (restorable).                                                           |
| [`unshare`](#annals.tools.unshare)(links, \*[, target, to])                   | Revoke share links (their token or full link): they stop working at once.                                 |

### annals.tools.DFLT_EFFECTS *= frozenset({'read', 'write'})*

what an agent or a tool is offered unless its host asks for more (MCP reads this)

### annals.tools.EFFECTS *= {'aggregate': 'file', 'configure': 'write', 'copy': 'write', 'export': 'file', 'group': 'write', 'groups': 'read', 'listen': 'spend', 'listen_down': 'spend', 'listen_work': 'server', 'ls': 'read', 'overview_state': 'read', 'page_shell': 'server', 'publish': 'write', 'purge': 'destructive', 'references': 'read', 'restore': 'write', 'serve': 'server', 'share': 'write', 'shareable': 'read', 'shares': 'read', 'show': 'read', 'tag': 'write', 'trash': 'write', 'unshare': 'write'}*

a surface serves the levels its caller
allows. `read` changes nothing; `write` changes the store or a setting and can be undone
or repeated; `file` writes a path on the machine that runs it; `destructive` cannot be
undone; `spend` costs money or queues work that does; `server` is run by a server or a
timer, never by a caller.

* **Type:**
  what a function does to the world, least to most

### annals.tools.LINKS_MAX_FILES *= 20*

[`show()`](#annals.tools.show) reads at most this many of a document’s text files for links …

### annals.tools.LINKS_MAX_FILE_BYTES *= 1000000*

… and none larger than this (bytes, from the document’s meta)

### annals.tools.LINKS_READ_SUFFIXES *= frozenset({'.htm', '.html', '.markdown', '.md', '.txt'})*

the suffixes whose text [`show()`](#annals.tools.show) reads for the annals links a document makes

### annals.tools.LINK_CHECKED_SUFFIXES *= frozenset({'.markdown', '.md', '.txt'})*

the suffixes whose text the link check reads (prose an author writes by hand)

### annals.tools.aggregate(group_id, , format='md', output=None, demote=1, order='numbered', no_toc=False, keep_wraps=False, target=None, to=None)

The files of a group (or one document) as ONE markdown, html or pdf file (nothing is stored).

`group_id` is a group’s or a document’s id or link. `format`: `md` (printed, or
written to `output`), `html` (a web page, the same) or `pdf` (needs `output`).
Markdown, html, text, PDF and image files go in; what cannot (audio, video, other
files, a damaged PDF) is listed on stderr, with the reason, and left out. The markdown
has the group’s title, a table of contents, then one `##` section per file named after
its path (a folder document’s files under its title). `order`: `numbered` puts paths
that start with a number first, numerically, the rest in the group’s order; `given`
keeps the group’s order. `demote` pushes each file’s headings that many levels down
(`0`: as written). Hard-wrapped lines are joined unless `keep_wraps`; `no_toc`
leaves out the table of contents. Redirect to save text, or name the file:
`annals aggregate <id> --format pdf --output bundle.pdf`. A PDF or html needs
`pip install 'annals[pdf]'`; a missing library says so.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.configure(, target=None, base_url=None, to=None, outbox=False, share_base_url=None, room=False)

Write the publisher config (where to publish, what link to print) and show it.

### Example

`annals configure --target tw:/root/.local/share/annals --base-url https://apps.example.com/annals`.
`--to NAME` saves the target and base url as a named target (`annals publish --to NAME`)
and leaves the default alone. `--outbox` marks the target as an outbox: a directory
the server pulls and empties (it cannot be written to from here), so replacements are
left for the server to apply; it is kept by later changes (`ANNALS_OUTBOX=0` or an
edit of the file turns it off). `--share-base-url` is where share links point when
the share server is not at `<base-url>/shared` (a platform running it as its own
public app). `--room` marks a target an outside audience reads (a client’s room): what
is published or copied to it carries no provenance; kept by later changes, like
`--outbox`. With no arguments, shows the resolved settings without writing.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.copy(refs, , to, source=None, target=None, base_url=None)

Copy documents or groups to a named target, keeping their ids; print the new link.

`refs` are links (`https://.../annals/d/<id>`, `.../g/<group-id>`) or bare ids; only
the id is used, so the link may point at any instance. They are read from the default
target (or the named target `source`) and written to the named target `to`. A group
is copied with its documents and keeps its id and title. Copying again refreshes the
copy. The source must be readable from this machine (a directory, or `host:/path`).
`target`/`base_url` override the DESTINATION’s location, as in `publish`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.export(doc_id, , format='pdf', file=None, output=None, target=None, to=None)

One markdown file of a document as a `.md` or a titled `.pdf`, as the page’s Export gives it.

`file` names another markdown file of a folder document (default: the main one). A PDF
(images inside; needs the `annals[pdf]` extra) is a binary file, so name it with
`--output FILE`; `md` prints the text or writes it to `output`. For several documents
as one file, with a table of contents, use `annals aggregate`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.group(title, doc_ids, , add_to=None, target=None, base_url=None, to=None)

Make a group (one URL for a set of documents) from existing document ids.

With `add_to` (a group id) the documents are added to that group instead, and `title`
is ignored. The documents must exist and not be in the bin; the title is cleaned (see
[`annals.store.clean_title()`](annals.store.html.md#annals.store.clean_title)).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.groups(, target=None, base_url=None, to=None)

List groups, newest first.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.listen(doc_id, , minutes=5, force=False, also=None, target=None, to=None)

Ask for a spoken overview of a document, as its page’s Listen button does. Spends money.

`also` (more document ids) asks for ONE overview of all of them together, as the page
does for a pick: their text is put in one document (made when the worker starts the job),
and the same documents at the same versions reuse it. `force` then does not apply.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.listen_down(reason='', , link='', clear=False, target=None, to=None)

Say why spoken overviews cannot be made, and where that is being fixed; or clear it.

With nothing given, shows the current state. The Audio tab then shows the reason and the
link instead of a Try again that cannot work, e.g.
`annals listen-down "the server's login expired" --link <issue url>`. The worker finds
out by itself too, and clears it on the next success; `--clear` clears it now and
queues every request that waited.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.listen_work(, command='', target=None, to=None)

Fulfil the queued overview requests, one at a time (a timer runs this on the server).

`command` makes one overview, with {source}, {minutes}, {out} and {url} filled in; by default,
`$ANNALS_OVERVIEW_COMMAND`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.ls(q='', , trash=False, limit=50, target=None, base_url=None, to=None, since=None, session=None, tag=None, meta=None)

List documents (newest first), optionally filtered by words or showing the bin.

`to` lists a named target instead of the default one. The rest are exact filters,
all of which must hold, for tools that poll: `since` (an ISO date or time, or an age
like `6h` or `2d`: published or replaced at or after it), `session` (the publishing session’s
name, whole, case-sensitive), `tag` (one tag, whole: the owner’s own tags, set by `annals tag`, win over the publisher’s) and `meta` (`key=value`,
several allowed, against the document’s `source`: `corpus=annals`). A row is
`{id, title, kind, tags, created, updated, source, url}`; with `--json` that is the contract
(`misc/docs/design.md`), and `total` counts the matches before `limit`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.overview_state(doc_id, , target=None, to=None)

Where a document’s spoken overview stands (not asked for, queued, made, failed), without asking for one.

Poll this after `annals listen`. For a combined overview (`listen --also`) give the
combined document’s id once the worker has made it; until then `listen` returns the state.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.page_shell(, api='/api/annals', base='/annals', title='annals')

The page’s html shell, for a host that serves the API under its own prefix.

An enlace app writes it once as its frontend:
`annals page-shell --api /api/annals --base /annals > frontend/index.html`.
The shell only names the two paths; the page’s code loads from the API, so it upgrades
with the package.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.tools.publish(paths, , title=None, tags='', group=None, add_to=None, session=None, all_files=False, target=None, base_url=None, to=None, replace=None, artifact=None, no_link_check=False, no_pdf=False, meta=None)

Publish one document and print its link; several paths become several documents.

An audio or video file takes its timed text along as one document: `talk.mp3
talk.vtt talk.chapters.vtt` (or `talk.cues.json`) is one audio document whose page
shows the transcript and chapters (`annals.store.SIDECAR_SUFFIXES`).

`paths`: files of any kind (markdown, html, images, video, audio, pdf, text), a
directory (one document: an `index.html` or single page with its assets, else a
gallery of everything in it), or `-` for stdin (markdown). `tags` is comma separated. `group`
names a group to create from the published documents; the reply then carries
`group_url` too. `add_to` appends them to an existing group instead (its id, as
printed in a group link), so a second batch lands under the link the owner already has. `session` records who published (the source shown on the page). A directory skips
hidden files and caches (`.*`, `__pycache__`, `*.pyc`) unless `all_files`.
`to` publishes to a named target of the config file (`[targets.NAME]`, see
`annals configure --to`) instead of the default one. `replace` (a document’s link or
id) publishes ONE path as a new version of that document: the link stays the same, the
page shows the new version and offers the earlier ones. That is how a living page (a
guide, a status page) keeps one link. `artifact` (a claude.ai artifact link) is the
interactive version of the page: the document’s page shows an “Open the interactive
version” button. Publish the Artifact first, then the same page here with its link.
A markdown or text document that mentions an issue or a Slack/email/chat message
without linking to it gets a warning on stderr ([`annals.linkcheck`](annals.linkcheck.html.md#module-annals.linkcheck)); it is
published either way. `no_link_check` turns that check off.

An html page gets its own Download PDF button, inside the page, so it survives “open
full page”, raw links and shares, and `<stem>.pdf` printed beside it (headless
Chromium, the `pdf` extra; without it the button opens the print dialog). A page that
already has its PDF says so with `<link rel="alternate" type="application/pdf"
href="...">`; one with its own button marks it `data-annals-pdf`; `no_pdf` (or
`data-annals-pdf="off"` on `<html>`/`<body>`) leaves the page as it is
([`annals.pagepdf`](annals.pagepdf.html.md#module-annals.pagepdf)).

`meta` (`--meta key=value [key=value ...]`) records what the document belongs to, next
to `host`, `cwd` and `session` in its `source`: by convention `corpus` (the
repository or body of work), `repo`, `issue` (the issue it answers), `item` (a
desk item) and `kind` (report, brief, overview, render); other keys are kept as given.
`ls --session/--meta` finds them again. The CLI’s `--json` prints the result below
(`id`, `title`, `url`, and with a group `group_id` and `group_url`; several
paths give `docs`) as JSON and nothing else on stdout; that shape is a contract
(`misc/docs/design.md`).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.purge(doc_ids, , target=None, to=None)

Delete documents that are in the bin for good (not restorable). One that is not in the bin is refused.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.references(ref, , form='grouped', also=None, target=None, to=None)

The references of a document or a group, as its page’s References action gives them.

`ref` is a group’s or a document’s id or link. `form`: `grouped` (each document’s
references section as it is), `deduped` (every entry once, numbers removed) or `urls`
(one address per line, nothing else: what a notebook takes as pasted sources). Documents
with no references section are left out; none at all is an error. `also` (more document
ids) takes the references of those documents together, as a pick on the page does.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.tools.restore(doc_ids, , target=None, to=None)

Bring documents back from the recycle bin.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.serve(, host='127.0.0.1', port=8765, data_dir=None, base_path='/annals', allow_open=False, overviews=None)

Serve the annals page and API (needs `pip install 'annals[server]'`).

Auth comes from the environment: `ANNALS_WHOAMI_URL` + `ANNALS_ALLOWED_USERS` to sit
behind an existing login, `ANNALS_BASIC_USER` + `ANNALS_BASIC_PASSWORD` for HTTP Basic,
nothing for an open server on localhost. A host reachable beyond this machine with no auth
configured is refused unless `allow_open` (`--allow-open`) says something else gates it.
`overviews` (`--overviews '*'`, or reader names separated by commas) offers the Listen
button to those the login lets in (unset: `ANNALS_OVERVIEWS` decides, and unset it is
off; `--overviews ''` forces it off). It spends money, needs `ANNALS_OVERVIEW_COMMAND`
and a worker (`annals listen-work` on a timer), and a server with no login serves it
only on this machine.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.tools.share(ref, , password=None, expires='7d', include=None, exclude=None, title=None, target=None, base_url=None, to=None)

Make a public link to ONE document (or group) and print it; nothing else is reachable.

Returns three forms of the one link (the CLI prints the first on stdout, the others
on stderr): `url`, the page, whose text is in the html (a
person, NotebookLM or any fetcher reads it without running script); `markdown`, the
whole share as one text, for an agent; `pdf`, the same with its images. All three end
with the link’s expiry or revocation.

`ref` is a document or group id, or its link. The link opens without a login, shows
only that page and the files chosen, and can be revoked (`annals unshare`).
`include`: comma separated files of the document to share (the page itself always
is), or ids of other annals pages it links to; by default every file of the document
(for a group: every document; `include` then picks documents). `exclude` drops
files. `expires` (7 days unless told): `12h`, `30d`, `2w`, a date (`2026-11-01`,
through that day, UTC), an ISO time, or `never`. `password` gates the link (stored hashed; `-` reads it from
stdin, so it stays out of the shell history).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.shareable(doc_id, , target=None, to=None)

What the Share dialog offers for a document: its files, and the other annals documents its text links to.

`{main, files: [{rel, kind, size, referenced}], pages: [{id, title, kind}]}`: the
choices `annals share` takes for what a link may show.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.shares(, all=False, target=None, base_url=None, to=None)

List share links, newest first (`all`: revoked and expired ones too).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.show(doc_id, , target=None, base_url=None, to=None)

A document’s metadata, link, the groups it is in, and the annals links in its text.

`doc_id` may be the document’s link, on any annals this machine is configured for: the
link finds its own place (`to` names one explicitly). A group’s link gives the group
and its documents’ links. `links` are the links to other annals documents and groups
found in the document’s text files, on any annals this machine can read: follow them
with `annals show` or `annals aggregate`. To read the text, use `annals aggregate <link>`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.tag(doc_id, tags, , target=None, to=None)

Set a document’s tags (comma separated; “” clears them), as the page’s tag editor does.

The tags are the owner’s overlay, kept apart from the document and shown by `ls` and
`show` in place of the publisher’s. They live where the documents do, so this refuses an
outbox or a remote target. `doc_id` may be the document’s link. Returns `{id, tags}`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.tools_with(effects=frozenset({'read', 'write'}))

The operations whose effect is in `effects`, in the CLI’s order: the list a caller-facing surface serves.

```pycon
>>> [f.__name__ for f in tools_with({"read"})]
['ls', 'show', 'groups', 'references', 'shareable', 'shares', 'overview_state']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### annals.tools.trash(doc_ids, , target=None, to=None)

Move documents to the recycle bin (restorable).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.unshare(links, , target=None, to=None)

Revoke share links (their token or full link): they stop working at once.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
