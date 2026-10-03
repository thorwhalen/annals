# tray

tray: an in-tray for AI agents. Publish markdown and html to a private page; get a link.

Agents call [`tray.tools.publish()`](tray.tools.md#tray.tools.publish) (or `tray publish file.md` from a shell) and hand
the printed URL to their human, who opens it on a phone. The documents are plain files in a
directory, local or on another machine over ssh; `tray.api.mk_app()` serves that
directory as a private page with search, sort, groups and a recycle bin.

### Functions

| [`configure`](#tray.configure)(\*[, target, base_url])                  | Write the publisher config (where to publish, what link to print) and show it.                                                                                    |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`group`](#tray.group)(title, doc_ids, \*[, target, base_url])      | Make a group (one URL for a set of documents) from existing document ids.                                                                                         |
| [`groups`](#tray.groups)(\*[, target, base_url])                     | List groups, newest first.                                                                                                                                        |
| [`load_settings`](#tray.load_settings)(\*[, target, base_url, config_path]) | Resolve settings: arguments, then env, then the config file, then local defaults.                                                                                 |
| [`ls`](#tray.ls)([q, trash, limit, target, base_url])            | List documents (newest first), optionally filtered by words or showing the bin.                                                                                   |
| [`parse_target`](#tray.parse_target)(spec)                                 | `host:/path` becomes an [`SshTarget`](#tray.SshTarget); anything else a [`LocalTarget`](#tray.LocalTarget). |
| [`publish`](#tray.publish)(paths, \*[, title, tags, group, ...])      | Publish one document and print its link; several paths become several documents.                                                                                  |
| [`restore`](#tray.restore)(doc_ids, \*[, target])                     | Bring documents back from the recycle bin.                                                                                                                        |
| [`show`](#tray.show)(doc_id, \*[, target, base_url])               | A document's metadata and link.                                                                                                                                   |
| [`trash`](#tray.trash)(doc_ids, \*[, target])                       | Move documents to the recycle bin (restorable).                                                                                                                   |

### Classes

| [`DocStore`](#tray.DocStore)(target)           | Publish, list, read, trash, restore and group documents on a `Target`.      |
|-----------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`LocalTarget`](#tray.LocalTarget)(root)          | A directory on this machine.                                                |
| [`Settings`](#tray.Settings)(target, base_url) | Where to publish and what link to print.                                    |
| [`SshTarget`](#tray.SshTarget)(host, root)      | `host:path` on another machine, via the system ssh and rsync in batch mode. |

### *class* tray.DocStore(target)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Publish, list, read, trash, restore and group documents on a `Target`.

#### add_to_group(gid, doc_ids)

Append ids to an existing group, keeping order and skipping duplicates.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### group(gid)

One group, by id.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### list(, trash=False)

Every document’s meta, newest first (ids sort by time; `created` breaks ties).

* **Return type:**
  [`list`](#tray.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### list_groups()

Every group, newest first.

* **Return type:**
  [`list`](#tray.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### make_group(title, doc_ids, , gid=None)

Create (or overwrite) a group: a titled, ordered list of document ids.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### meta(doc_id)

One document’s meta; `in_trash` says which side of the bin it is on.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### publish(\*sources, title=None, tags=(), source=None, text=None, filename='document.md')

Publish files (or a directory, or `text`) as ONE document; return its meta.

One markdown or html file is the common case. A directory is published whole, with
`index.html` (or the first renderable file) as the page shown. `text` publishes a
string as `filename` instead of reading sources.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### purge(doc_id)

Delete a document that is in the bin. Refuses one that is not.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### read_text(doc_id, rel=None)

A document’s main file (or one of its files) as text.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### restore(doc_id)

Move a document out of the bin (idempotent).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### search(query, , trash=False)

Case-insensitive match of every query word against title, tags, excerpt, source.

* **Return type:**
  [`list`](#tray.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### trash(doc_id)

Move a document into the bin (idempotent).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* tray.LocalTarget(root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A directory on this machine.

### *class* tray.Settings(target, base_url)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Where to publish and what link to print. See the module docstring for precedence.

#### as_dict()

Plain dict, for the CLI and MCP surfaces.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* tray.SshTarget(host, root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

`host:path` on another machine, via the system ssh and rsync in batch mode.

### tray.configure(, target=None, base_url=None)

Write the publisher config (where to publish, what link to print) and show it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### Example

`tray configure --target tw:/root/.local/share/tray --base-url https://apps.example.com/tray`.
With no arguments, shows the resolved settings without writing.

### tray.group(title, doc_ids, , target=None, base_url=None)

Make a group (one URL for a set of documents) from existing document ids.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### tray.groups(, target=None, base_url=None)

List groups, newest first.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### tray.load_settings(, target=None, base_url=None, config_path=None)

Resolve settings: arguments, then env, then the config file, then local defaults.

* **Return type:**
  [`Settings`](tray.config.md#tray.config.Settings)

### tray.ls(q='', , trash=False, limit=50, target=None, base_url=None)

List documents (newest first), optionally filtered by words or showing the bin.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### tray.parse_target(spec)

`host:/path` becomes an [`SshTarget`](#tray.SshTarget); anything else a [`LocalTarget`](#tray.LocalTarget).

* **Return type:**
  [`Target`](tray.target.md#tray.target.Target)

### tray.publish(paths, , title=None, tags='', group=None, session=None, target=None, base_url=None)

Publish one document and print its link; several paths become several documents.

`paths`: markdown or html files, a directory (an html artifact with `index.html`
and its assets), or `-` for stdin (markdown). `tags` is comma separated. `group`
names a group to create from the published documents; the reply then carries
`group_url` too. `session` records who published (the source shown on the page).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### tray.restore(doc_ids, , target=None)

Bring documents back from the recycle bin.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### tray.show(doc_id, , target=None, base_url=None)

A document’s metadata and link.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### tray.trash(doc_ids, , target=None)

Move documents to the recycle bin (restorable).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### Modules

| [`auth`](tray.auth.md#module-tray.auth)     | The auth seam: who may read the tray.                                                                                                          |
|----------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| [`config`](tray.config.md#module-tray.config) | Settings: where documents are published and what link to print.                                                                                |
| [`mcp`](tray.mcp.md#module-tray.mcp)       | MCP surface: the same operations as the CLI, from [`tray.tools`](tray.tools.md#module-tray.tools), via `py2mcp`. |
| [`store`](tray.store.md#module-tray.store)   | The document store: a flat set of documents, tags, groups and a recycle bin, as plain files.                                                   |
| [`target`](tray.target.md#module-tray.target) | The transport seam: a document tree lands in a directory, here or on another machine.                                                          |
| [`tools`](tray.tools.md#module-tray.tools)   | The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.                                                               |
