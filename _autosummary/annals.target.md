# annals.target

The transport seam: a document tree lands in a directory, here or on another machine.

A `Target` is the handful of filesystem verbs the store needs (put a directory, move,
remove, read and write a text file, list sub-directories, read every `meta.json` under a
directory). Two implementations:

* [`LocalTarget`](#annals.target.LocalTarget): a directory on this machine, plain `pathlib`/`shutil`.
* [`SshTarget`](#annals.target.SshTarget): `host:path` on another machine, through the system `ssh` and
  `rsync` in batch mode (no prompts, so an agent never hangs). The host is whatever the
  user’s `~/.ssh/config` resolves, so an alias such as `tw` works.

[`parse_target()`](#annals.target.parse_target) picks one from a string. An HTTP target (a bearer-token ingest
endpoint) is the declared replacement for the ssh one and is not built yet.

### Module Attributes

| [`RECORD_SEP`](#annals.target.RECORD_SEP)   | Separator between concatenated meta.json files when reading many at once over ssh.   |
|---------------------------------------------------------------|--------------------------------------------------------------------------------------|

### Functions

| [`check_rel`](#annals.target.check_rel)(rel)     | Refuse anything that could escape the root; the store only ever passes safe paths.                                                                                |
|---------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`parse_target`](#annals.target.parse_target)(spec) | `host:/path` becomes an [`SshTarget`](#annals.target.SshTarget); anything else a [`LocalTarget`](#annals.target.LocalTarget). |

### Classes

| [`LocalTarget`](#annals.target.LocalTarget)(root)          | A directory on this machine.                                                |
|-----------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`SshTarget`](#annals.target.SshTarget)(host, root)      | `host:path` on another machine, via the system ssh and rsync in batch mode. |
| [`Target`](#annals.target.Target)(\*args, \*\*kwargs) | What the store needs from wherever the documents live.                      |

### *class* annals.target.LocalTarget(root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A directory on this machine.

#### local_path(rel)

`rel` under the root, resolved; `None` if it escapes the root (a symlink).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.target.RECORD_SEP *= '\\x1e'*

Separator between concatenated meta.json files when reading many at once over ssh.

### *class* annals.target.SshTarget(host, root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

`host:path` on another machine, via the system ssh and rsync in batch mode.

### *class* annals.target.Target(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

What the store needs from wherever the documents live.

#### local_path(rel)

The file on this machine’s disk, when the documents are local (to stream it).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.target.check_rel(rel)

Refuse anything that could escape the root; the store only ever passes safe paths.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.target.parse_target(spec)

`host:/path` becomes an [`SshTarget`](#annals.target.SshTarget); anything else a [`LocalTarget`](#annals.target.LocalTarget).

* **Return type:**
  [`Target`](#annals.target.Target)
