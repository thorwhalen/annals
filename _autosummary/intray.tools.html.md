# intray.tools

The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This module is the single source of truth for what a tray can do. The CLI
(`intray.__main__`, via `cw`), the MCP server (`py2mcp` over string refs to these
names) and the shipped skill all describe the same functions, so there is nothing to keep
in parity. Nothing here prints or exits; the surfaces do that.

### Functions

| [`configure`](#intray.tools.configure)(\*[, target, base_url])             | Write the publisher config (where to publish, what link to print) and show it.   |
|------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`group`](#intray.tools.group)(title, doc_ids, \*[, target, base_url]) | Make a group (one URL for a set of documents) from existing document ids.        |
| [`groups`](#intray.tools.groups)(\*[, target, base_url])                | List groups, newest first.                                                       |
| [`ls`](#intray.tools.ls)([q, trash, limit, target, base_url])       | List documents (newest first), optionally filtered by words or showing the bin.  |
| [`publish`](#intray.tools.publish)(paths, \*[, title, tags, group, ...]) | Publish one document and print its link; several paths become several documents. |
| [`restore`](#intray.tools.restore)(doc_ids, \*[, target])                | Bring documents back from the recycle bin.                                       |
| [`serve`](#intray.tools.serve)(\*[, host, port, data_dir, base_path])  | Serve the tray page and API (needs `pip install 'intray[server]'`).              |
| [`show`](#intray.tools.show)(doc_id, \*[, target, base_url])          | A document's metadata and link.                                                  |
| [`trash`](#intray.tools.trash)(doc_ids, \*[, target])                  | Move documents to the recycle bin (restorable).                                  |

### intray.tools.configure(, target=None, base_url=None)

Write the publisher config (where to publish, what link to print) and show it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### Example

`tray configure --target tw:/root/.local/share/tray --base-url https://apps.example.com/tray`.
With no arguments, shows the resolved settings without writing.

### intray.tools.group(title, doc_ids, , target=None, base_url=None)

Make a group (one URL for a set of documents) from existing document ids.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### intray.tools.groups(, target=None, base_url=None)

List groups, newest first.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### intray.tools.ls(q='', , trash=False, limit=50, target=None, base_url=None)

List documents (newest first), optionally filtered by words or showing the bin.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### intray.tools.publish(paths, , title=None, tags='', group=None, session=None, target=None, base_url=None)

Publish one document and print its link; several paths become several documents.

`paths`: markdown or html files, a directory (an html artifact with `index.html`
and its assets), or `-` for stdin (markdown). `tags` is comma separated. `group`
names a group to create from the published documents; the reply then carries
`group_url` too. `session` records who published (the source shown on the page).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### intray.tools.restore(doc_ids, , target=None)

Bring documents back from the recycle bin.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### intray.tools.serve(, host='127.0.0.1', port=8765, data_dir=None, base_path='/tray')

Serve the tray page and API (needs `pip install 'intray[server]'`).

Auth comes from the environment: `TRAY_WHOAMI_URL` + `TRAY_ALLOWED_USERS` to sit
behind an existing login, `TRAY_BASIC_USER` + `TRAY_BASIC_PASSWORD` for HTTP Basic,
nothing for an open server on localhost.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### intray.tools.show(doc_id, , target=None, base_url=None)

A document’s metadata and link.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### intray.tools.trash(doc_ids, , target=None)

Move documents to the recycle bin (restorable).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
