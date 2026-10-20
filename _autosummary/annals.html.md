# annals

annals: an in-tray for AI agents. Publish documents and media to a private page; get a link.

Agents call [`annals.tools.publish()`](annals.tools.html.md#annals.tools.publish) (or `annals publish file.md` from a shell) and hand
the printed URL to their human, who opens it on a phone. The documents are plain files in a
directory, local or on another machine over ssh; `annals.api.mk_app()` serves that
directory as a private page with search, sort, groups and a recycle bin.

### Functions

| [`configure`](#annals.configure)(\*[, target, base_url, to, outbox])     | Write the publisher config (where to publish, what link to print) and show it.                                                                                    |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`group`](#annals.group)(title, doc_ids, \*[, target, base_url, to]) | Make a group (one URL for a set of documents) from existing document ids.                                                                                         |
| [`groups`](#annals.groups)(\*[, target, base_url, to])                | List groups, newest first.                                                                                                                                        |
| [`load_settings`](#annals.load_settings)(\*[, target, base_url, to, ...])    | Resolve settings: arguments, then `to`, env, the config file, then local defaults.                                                                                |
| [`ls`](#annals.ls)([q, trash, limit, target, base_url, to])       | List documents (newest first), optionally filtered by words or showing the bin.                                                                                   |
| [`parse_target`](#annals.parse_target)(spec)                                | `host:/path` becomes an [`SshTarget`](#annals.SshTarget); anything else a [`LocalTarget`](#annals.LocalTarget). |
| [`publish`](#annals.publish)(paths, \*[, title, tags, group, ...])     | Publish one document and print its link; several paths become several documents.                                                                                  |
| [`restore`](#annals.restore)(doc_ids, \*[, target, to])                | Bring documents back from the recycle bin.                                                                                                                        |
| [`show`](#annals.show)(doc_id, \*[, target, base_url, to])          | A document's metadata and link (`to`: on a named target).                                                                                                         |
| [`trash`](#annals.trash)(doc_ids, \*[, target, to])                  | Move documents to the recycle bin (restorable).                                                                                                                   |

### Classes

| [`DocStore`](#annals.DocStore)(target, \*[, settle])                   | Publish, list, read, trash, restore and group documents on a `Target`.      |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`LocalTarget`](#annals.LocalTarget)(root)                                | A directory on this machine.                                                |
| [`Settings`](#annals.Settings)(target, base_url[, configured, outbox]) | Where to publish and what link to print.                                    |
| [`SshTarget`](#annals.SshTarget)(host, root)                            | `host:path` on another machine, via the system ssh and rsync in batch mode. |

### *class* annals.DocStore(target, , settle=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Publish, list, read, trash, restore and group documents on a `Target`.

#### add_to_group(gid, doc_ids)

Append ids to an existing group, keeping order and skipping duplicates.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### doc_rel(doc_id)

The directory of a document (or of a version, `<id>@<n>`) under the data root.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### group(gid)

One group, by id.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### list(, trash=False)

Every document’s meta, last changed first (`updated`, else `created`).

Pending replacements are applied first (when this store settles). One whose
document is not here is listed under its own id, so it is never out of sight.

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

#### meta(doc_id, , settle=True)

One document’s meta; `in_trash` says which side of the bin it is on.

`<id>@<n>` is version `n`: its own meta, with `version_of` naming the document.
A pending replacement, read by its own id, says `pending`. `settle=False`
skips applying pending replacements (for a hot path such as a raw file).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### pending(doc_id=None, , names=None)

Pending replacements (directory names), oldest first; of one document if given.

`names`: the listing of `docs/` when the caller already has it.

* **Return type:**
  [`list`](#annals.DocStore.list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### publish(\*sources, title=None, tags=(), source=None, text=None, filename='document.md', exclude=('.\*', '_\_pycache_\_', '\*.pyc', '\*.pyo'), replace=None, artifact=None)

Publish files (or a directory, or `text`) as ONE document; return its meta.

One markdown or html file is the common case. A directory is published whole, with
`index.html` (or the first renderable file) as the page shown. `text` publishes a
string as `filename` instead of reading sources. `exclude` lists glob patterns
skipped inside a directory (hidden files and caches by default; `()` keeps all).

`replace` (a document id) publishes a new version of that document instead of a
new document: same id, same link, the current files kept as a version. It is
written as a pending replacement and applied at once when this store settles
(otherwise where the store is read). The returned meta says `pending` until then.

`artifact` (a claude.ai artifact link, see `check_artifact_url()`) is the
interactive version of the page: the document’s page links out to it. A
replacement that names none keeps the document’s current one.

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

#### settle(doc_id=None)

Apply pending replacements (of one document, or all); return the ids replaced.

A replacement whose document is not here yet (it is still on its way, or the
document was purged) stays pending and is listed under its own id.

* **Return type:**
  [`list`](#annals.DocStore.list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### trash(doc_id)

Move a document into the bin (idempotent).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### versions(doc_id)

Every version of a document, oldest first, the current one last.

* **Return type:**
  [`list`](#annals.DocStore.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### *class* annals.LocalTarget(root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A directory on this machine.

#### local_path(rel)

`rel` under the root, resolved; `None` if it escapes the root (a symlink).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* annals.Settings(target, base_url, configured=True, outbox=False)

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

#### outbox *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

the target is pulled and emptied by another machine; replacements apply there

### *class* annals.SshTarget(host, root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

`host:path` on another machine, via the system ssh and rsync in batch mode.

### annals.configure(, target=None, base_url=None, to=None, outbox=False)

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

### annals.group(title, doc_ids, , target=None, base_url=None, to=None)

Make a group (one URL for a set of documents) from existing document ids.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.groups(, target=None, base_url=None, to=None)

List groups, newest first.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.load_settings(, target=None, base_url=None, to=None, outbox=None, config_path=None)

Resolve settings: arguments, then `to`, env, the config file, then local defaults.

`to` names a `[targets.NAME]` table of the config file; it replaces the environment
and the file’s default target for this call (explicit arguments still win).

* **Return type:**
  [`Settings`](annals.config.html.md#annals.config.Settings)

### annals.ls(q='', , trash=False, limit=50, target=None, base_url=None, to=None)

List documents (newest first), optionally filtered by words or showing the bin.

`to` lists a named target instead of the default one.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.parse_target(spec)

`host:/path` becomes an [`SshTarget`](#annals.SshTarget); anything else a [`LocalTarget`](#annals.LocalTarget).

* **Return type:**
  [`Target`](annals.target.html.md#annals.target.Target)

### annals.publish(paths, , title=None, tags='', group=None, add_to=None, session=None, all_files=False, target=None, base_url=None, to=None, replace=None, artifact=None)

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

### annals.restore(doc_ids, , target=None, to=None)

Bring documents back from the recycle bin.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.show(doc_id, , target=None, base_url=None, to=None)

A document’s metadata and link (`to`: on a named target).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.trash(doc_ids, , target=None, to=None)

Move documents to the recycle bin (restorable).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### Modules

| [`auth`](annals.auth.html.md#module-annals.auth)       | The auth seam: who may read the annals.                                                                                                            |
|--------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| [`catalog`](annals.catalog.html.md#module-annals.catalog) | The catalog: every source's items as one list, with search and the owner's tags.                                                                   |
| [`config`](annals.config.html.md#module-annals.config)   | Settings: where documents are published and what link to print.                                                                                    |
| [`mcp`](annals.mcp.html.md#module-annals.mcp)         | MCP surface: the same operations as the CLI, from [`annals.tools`](annals.tools.html.md#module-annals.tools), via `py2mcp`. |
| [`sources`](annals.sources.html.md#module-annals.sources) | Item sources: everything the page lists, wherever it lives, as rows of one shape.                                                                  |
| [`store`](annals.store.html.md#module-annals.store)     | The document store: a flat set of documents, tags, groups and a recycle bin, as plain files.                                                       |
| [`tags`](annals.tags.html.md#module-annals.tags)       | The owner's tags: a `MutableMapping` from item key to tag list, kept apart from the items.                                                         |
| [`target`](annals.target.html.md#module-annals.target)   | The transport seam: a document tree lands in a directory, here or on another machine.                                                              |
| [`tools`](annals.tools.html.md#module-annals.tools)     | The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.                                                                   |
