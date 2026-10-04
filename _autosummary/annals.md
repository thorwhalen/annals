# annals

annals: an in-tray for AI agents. Publish documents and media to a private page; get a link.

Agents call [`annals.tools.publish()`](annals.tools.md#annals.tools.publish) (or `annals publish file.md` from a shell) and hand
the printed URL to their human, who opens it on a phone. The documents are plain files in a
directory, local or on another machine over ssh; `annals.api.mk_app()` serves that
directory as a private page with search, sort, groups and a recycle bin.

### Functions

| [`configure`](#annals.configure)(\*[, target, base_url])                  | Write the publisher config (where to publish, what link to print) and show it.                                                                                    |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`group`](#annals.group)(title, doc_ids, \*[, target, base_url])      | Make a group (one URL for a set of documents) from existing document ids.                                                                                         |
| [`groups`](#annals.groups)(\*[, target, base_url])                     | List groups, newest first.                                                                                                                                        |
| [`load_settings`](#annals.load_settings)(\*[, target, base_url, config_path]) | Resolve settings: arguments, then env, then the config file, then local defaults.                                                                                 |
| [`ls`](#annals.ls)([q, trash, limit, target, base_url])            | List documents (newest first), optionally filtered by words or showing the bin.                                                                                   |
| [`parse_target`](#annals.parse_target)(spec)                                 | `host:/path` becomes an [`SshTarget`](#annals.SshTarget); anything else a [`LocalTarget`](#annals.LocalTarget). |
| [`publish`](#annals.publish)(paths, \*[, title, tags, group, ...])      | Publish one document and print its link; several paths become several documents.                                                                                  |
| [`restore`](#annals.restore)(doc_ids, \*[, target])                     | Bring documents back from the recycle bin.                                                                                                                        |
| [`show`](#annals.show)(doc_id, \*[, target, base_url])               | A document's metadata and link.                                                                                                                                   |
| [`trash`](#annals.trash)(doc_ids, \*[, target])                       | Move documents to the recycle bin (restorable).                                                                                                                   |

### Classes

| [`DocStore`](#annals.DocStore)(target)                         | Publish, list, read, trash, restore and group documents on a `Target`.      |
|-------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`LocalTarget`](#annals.LocalTarget)(root)                        | A directory on this machine.                                                |
| [`Settings`](#annals.Settings)(target, base_url[, configured]) | Where to publish and what link to print.                                    |
| [`SshTarget`](#annals.SshTarget)(host, root)                    | `host:path` on another machine, via the system ssh and rsync in batch mode. |

### *class* annals.DocStore(target)

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
  [`list`](#annals.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### list_groups()

Every group, newest first.

* **Return type:**
  [`list`](#annals.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### make_group(title, doc_ids, , gid=None)

Create (or overwrite) a group: a titled, ordered list of document ids.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### meta(doc_id)

One document’s meta; `in_trash` says which side of the bin it is on.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### publish(\*sources, title=None, tags=(), source=None, text=None, filename='document.md', exclude=('.\*', '_\_pycache_\_', '\*.pyc', '\*.pyo'))

Publish files (or a directory, or `text`) as ONE document; return its meta.

One markdown or html file is the common case. A directory is published whole, with
`index.html` (or the first renderable file) as the page shown. `text` publishes a
string as `filename` instead of reading sources. `exclude` lists glob patterns
skipped inside a directory (hidden files and caches by default; `()` keeps all).

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
  [`list`](#annals.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### trash(doc_id)

Move a document into the bin (idempotent).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* annals.LocalTarget(root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A directory on this machine.

#### local_path(rel)

`rel` under the root, resolved; `None` if it escapes the root (a symlink).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* annals.Settings(target, base_url, configured=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Where to publish and what link to print. See the module docstring for precedence.

#### as_dict()

Plain dict, for the CLI and MCP surfaces.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### configured *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= True*

publishing then lands
in the local data dir and the link points at a local server, which is rarely meant

* **Type:**
  False when nothing (argument, env, config file) named a target

### *class* annals.SshTarget(host, root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

`host:path` on another machine, via the system ssh and rsync in batch mode.

### annals.configure(, target=None, base_url=None)

Write the publisher config (where to publish, what link to print) and show it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### Example

`annals configure --target tw:/root/.local/share/annals --base-url https://apps.example.com/annals`.
With no arguments, shows the resolved settings without writing.

### annals.group(title, doc_ids, , target=None, base_url=None)

Make a group (one URL for a set of documents) from existing document ids.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.groups(, target=None, base_url=None)

List groups, newest first.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.load_settings(, target=None, base_url=None, config_path=None)

Resolve settings: arguments, then env, then the config file, then local defaults.

* **Return type:**
  [`Settings`](annals.config.md#annals.config.Settings)

### annals.ls(q='', , trash=False, limit=50, target=None, base_url=None)

List documents (newest first), optionally filtered by words or showing the bin.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.parse_target(spec)

`host:/path` becomes an [`SshTarget`](#annals.SshTarget); anything else a [`LocalTarget`](#annals.LocalTarget).

* **Return type:**
  [`Target`](annals.target.md#annals.target.Target)

### annals.publish(paths, , title=None, tags='', group=None, add_to=None, session=None, all_files=False, target=None, base_url=None)

Publish one document and print its link; several paths become several documents.

`paths`: files of any kind (markdown, html, images, video, audio, pdf, text), a
directory (one document: an `index.html` or single page with its assets, else a
gallery of everything in it), or `-` for stdin (markdown). `tags` is comma separated. `group`
names a group to create from the published documents; the reply then carries
`group_url` too. `add_to` appends them to an existing group instead (its id, as
printed in a group link), so a second batch lands under the link the owner already has. `session` records who published (the source shown on the page). A directory skips
hidden files and caches (`.*`, `__pycache__`, `*.pyc`) unless `all_files`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.restore(doc_ids, , target=None)

Bring documents back from the recycle bin.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.show(doc_id, , target=None, base_url=None)

A document’s metadata and link.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.trash(doc_ids, , target=None)

Move documents to the recycle bin (restorable).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### Modules

| [`auth`](annals.auth.md#module-annals.auth)     | The auth seam: who may read the annals.                                                                                                            |
|------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| [`config`](annals.config.md#module-annals.config) | Settings: where documents are published and what link to print.                                                                                    |
| [`mcp`](annals.mcp.md#module-annals.mcp)       | MCP surface: the same operations as the CLI, from [`annals.tools`](annals.tools.md#module-annals.tools), via `py2mcp`. |
| [`store`](annals.store.md#module-annals.store)   | The document store: a flat set of documents, tags, groups and a recycle bin, as plain files.                                                       |
| [`target`](annals.target.md#module-annals.target) | The transport seam: a document tree lands in a directory, here or on another machine.                                                              |
| [`tools`](annals.tools.md#module-annals.tools)   | The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.                                                                   |
