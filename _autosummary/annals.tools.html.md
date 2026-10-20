# annals.tools

The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This module is the single source of truth for what a annals can do. The CLI
(`annals.__main__`, via `cw`), the MCP server (`py2mcp` over string refs to these
names) and the shipped skill all describe the same functions, so there is nothing to keep
in parity. Nothing here prints or exits; the surfaces do that.

### Functions

| [`configure`](#annals.tools.configure)(\*[, target, base_url, to, outbox])     | Write the publisher config (where to publish, what link to print) and show it.     |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`copy`](#annals.tools.copy)(refs, \*, to[, source, target, base_url])    | Copy documents or groups to a named target, keeping their ids; print the new link. |
| [`group`](#annals.tools.group)(title, doc_ids, \*[, target, base_url, to]) | Make a group (one URL for a set of documents) from existing document ids.          |
| [`groups`](#annals.tools.groups)(\*[, target, base_url, to])                | List groups, newest first.                                                         |
| [`ls`](#annals.tools.ls)([q, trash, limit, target, base_url, to])       | List documents (newest first), optionally filtered by words or showing the bin.    |
| [`page_shell`](#annals.tools.page_shell)(\*[, api, base, title])                | The page's html shell, for a host that serves the API under its own prefix.        |
| [`publish`](#annals.tools.publish)(paths, \*[, title, tags, group, ...])     | Publish one document and print its link; several paths become several documents.   |
| [`restore`](#annals.tools.restore)(doc_ids, \*[, target, to])                | Bring documents back from the recycle bin.                                         |
| [`serve`](#annals.tools.serve)(\*[, host, port, data_dir, base_path, ...]) | Serve the annals page and API (needs `pip install 'annals[server]'`).              |
| [`show`](#annals.tools.show)(doc_id, \*[, target, base_url, to])          | A document's metadata and link (`to`: on a named target).                          |
| [`trash`](#annals.tools.trash)(doc_ids, \*[, target, to])                  | Move documents to the recycle bin (restorable).                                    |

### annals.tools.configure(, target=None, base_url=None, to=None, outbox=False)

Write the publisher config (where to publish, what link to print) and show it.

### Example

`annals configure --target tw:/root/.local/share/annals --base-url https://apps.example.com/annals`.
`--to NAME` saves the target and base url as a named target (`annals publish --to NAME`)
and leaves the default alone. `--outbox` marks the target as an outbox: a directory
the server pulls and empties (it cannot be written to from here), so replacements are
left for the server to apply; it is kept by later changes (`ANNALS_OUTBOX=0` or an
edit of the file turns it off). With no arguments, shows the resolved settings without writing.

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

### annals.tools.group(title, doc_ids, , target=None, base_url=None, to=None)

Make a group (one URL for a set of documents) from existing document ids.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.groups(, target=None, base_url=None, to=None)

List groups, newest first.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.ls(q='', , trash=False, limit=50, target=None, base_url=None, to=None)

List documents (newest first), optionally filtered by words or showing the bin.

`to` lists a named target instead of the default one.

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

### annals.tools.publish(paths, , title=None, tags='', group=None, add_to=None, session=None, all_files=False, target=None, base_url=None, to=None, replace=None, artifact=None)

Publish one document and print its link; several paths become several documents.

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

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.restore(doc_ids, , target=None, to=None)

Bring documents back from the recycle bin.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.serve(, host='127.0.0.1', port=8765, data_dir=None, base_path='/annals', allow_open=False)

Serve the annals page and API (needs `pip install 'annals[server]'`).

Auth comes from the environment: `ANNALS_WHOAMI_URL` + `ANNALS_ALLOWED_USERS` to sit
behind an existing login, `ANNALS_BASIC_USER` + `ANNALS_BASIC_PASSWORD` for HTTP Basic,
nothing for an open server on localhost. A host reachable beyond this machine with no auth
configured is refused unless `allow_open` (`--allow-open`) says something else gates it.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.tools.show(doc_id, , target=None, base_url=None, to=None)

A document’s metadata and link (`to`: on a named target).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.trash(doc_ids, , target=None, to=None)

Move documents to the recycle bin (restorable).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
