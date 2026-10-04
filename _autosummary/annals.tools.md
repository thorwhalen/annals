# annals.tools

The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This module is the single source of truth for what a annals can do. The CLI
(`annals.__main__`, via `cw`), the MCP server (`py2mcp` over string refs to these
names) and the shipped skill all describe the same functions, so there is nothing to keep
in parity. Nothing here prints or exits; the surfaces do that.

### Functions

| [`configure`](#annals.tools.configure)(\*[, target, base_url])             | Write the publisher config (where to publish, what link to print) and show it.   |
|------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`group`](#annals.tools.group)(title, doc_ids, \*[, target, base_url]) | Make a group (one URL for a set of documents) from existing document ids.        |
| [`groups`](#annals.tools.groups)(\*[, target, base_url])                | List groups, newest first.                                                       |
| [`ls`](#annals.tools.ls)([q, trash, limit, target, base_url])       | List documents (newest first), optionally filtered by words or showing the bin.  |
| [`page_shell`](#annals.tools.page_shell)(\*[, api, base, title])            | The page's html shell, for a host that serves the API under its own prefix.      |
| [`publish`](#annals.tools.publish)(paths, \*[, title, tags, group, ...]) | Publish one document and print its link; several paths become several documents. |
| [`restore`](#annals.tools.restore)(doc_ids, \*[, target])                | Bring documents back from the recycle bin.                                       |
| [`serve`](#annals.tools.serve)(\*[, host, port, data_dir, base_path])  | Serve the annals page and API (needs `pip install 'annals[server]'`).            |
| [`show`](#annals.tools.show)(doc_id, \*[, target, base_url])          | A document's metadata and link.                                                  |
| [`trash`](#annals.tools.trash)(doc_ids, \*[, target])                  | Move documents to the recycle bin (restorable).                                  |

### annals.tools.configure(, target=None, base_url=None)

Write the publisher config (where to publish, what link to print) and show it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### Example

`annals configure --target tw:/root/.local/share/annals --base-url https://apps.example.com/annals`.
With no arguments, shows the resolved settings without writing.

### annals.tools.group(title, doc_ids, , target=None, base_url=None)

Make a group (one URL for a set of documents) from existing document ids.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.groups(, target=None, base_url=None)

List groups, newest first.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.ls(q='', , trash=False, limit=50, target=None, base_url=None)

List documents (newest first), optionally filtered by words or showing the bin.

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

### annals.tools.publish(paths, , title=None, tags='', group=None, session=None, all_files=False, target=None, base_url=None)

Publish one document and print its link; several paths become several documents.

`paths`: files of any kind (markdown, html, images, video, audio, pdf, text), a
directory (one document: an `index.html` or single page with its assets, else a
gallery of everything in it), or `-` for stdin (markdown). `tags` is comma separated. `group`
names a group to create from the published documents; the reply then carries
`group_url` too. `session` records who published (the source shown on the page). A directory skips
hidden files and caches (`.*`, `__pycache__`, `*.pyc`) unless `all_files`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.restore(doc_ids, , target=None)

Bring documents back from the recycle bin.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.serve(, host='127.0.0.1', port=8765, data_dir=None, base_path='/annals')

Serve the annals page and API (needs `pip install 'annals[server]'`).

Auth comes from the environment: `ANNALS_WHOAMI_URL` + `ANNALS_ALLOWED_USERS` to sit
behind an existing login, `ANNALS_BASIC_USER` + `ANNALS_BASIC_PASSWORD` for HTTP Basic,
nothing for an open server on localhost.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.tools.show(doc_id, , target=None, base_url=None)

A document’s metadata and link.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.tools.trash(doc_ids, , target=None)

Move documents to the recycle bin (restorable).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
