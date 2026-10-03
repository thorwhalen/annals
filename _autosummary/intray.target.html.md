# intray.target

The transport seam: a document tree lands in a directory, here or on another machine.

A `Target` is the handful of filesystem verbs the store needs (put a directory, move,
remove, read and write a text file, list sub-directories, read every `meta.json` under a
directory). Two implementations:

* [`LocalTarget`](#intray.target.LocalTarget): a directory on this machine, plain `pathlib`/`shutil`.
* [`SshTarget`](#intray.target.SshTarget): `host:path` on another machine, through the system `ssh` and
  `rsync` in batch mode (no prompts, so an agent never hangs). The host is whatever the
  user’s `~/.ssh/config` resolves, so an alias such as `tw` works.

[`parse_target()`](#intray.target.parse_target) picks one from a string. An HTTP target (a bearer-token ingest
endpoint) is the declared replacement for the ssh one and is not built yet.

### Module Attributes

| [`RECORD_SEP`](#intray.target.RECORD_SEP)   | Separator between concatenated meta.json files when reading many at once over ssh.   |
|---------------------------------------------------------------|--------------------------------------------------------------------------------------|

### Functions

| [`parse_target`](#intray.target.parse_target)(spec)   | `host:/path` becomes an [`SshTarget`](#intray.target.SshTarget); anything else a [`LocalTarget`](#intray.target.LocalTarget).   |
|-----------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### Classes

| [`LocalTarget`](#intray.target.LocalTarget)(root)          | A directory on this machine.                                                |
|-----------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`SshTarget`](#intray.target.SshTarget)(host, root)      | `host:path` on another machine, via the system ssh and rsync in batch mode. |
| [`Target`](#intray.target.Target)(\*args, \*\*kwargs) | What the store needs from wherever the documents live.                      |

### *class* intray.target.LocalTarget(root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A directory on this machine.

### intray.target.RECORD_SEP *= '\\x1e'*

Separator between concatenated meta.json files when reading many at once over ssh.

### *class* intray.target.SshTarget(host, root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

`host:path` on another machine, via the system ssh and rsync in batch mode.

### *class* intray.target.Target(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

What the store needs from wherever the documents live.

### intray.target.parse_target(spec)

`host:/path` becomes an [`SshTarget`](#intray.target.SshTarget); anything else a [`LocalTarget`](#intray.target.LocalTarget).

* **Return type:**
  [`Target`](#intray.target.Target)
