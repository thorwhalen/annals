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

| [`RECORD_SEP`](#annals.target.RECORD_SEP)   | Separator between concatenated meta.json files when reading many at once over ssh.                                                  |
|---------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| [`META_GLOB`](#annals.target.META_GLOB)    | each document's meta.json                                                                                                           |
| [`LOCK_NOTE`](#annals.target.LOCK_NOTE)    | the note a lock directory is created with (see [`Target.make_lock()`](#annals.target.Target.make_lock))                 |
| [`SSH_SHARE_S`](#annals.target.SSH_SHARE_S)  | the several calls of one command (and the next command soon after) reuse it instead of paying a handshake each (~3 s to a far host) |

### Functions

| [`check_glob`](#annals.target.check_glob)(pattern)       | A glob safe to hand a remote shell unquoted: names, `*` and `/` only, no hidden part.                                                                             |
|----------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`check_rel`](#annals.target.check_rel)(rel)            | Refuse anything that could escape the root; the store only ever passes safe paths.                                                                                |
| [`parse_target`](#annals.target.parse_target)(spec)        | `host:/path` becomes an [`SshTarget`](#annals.target.SshTarget); anything else a [`LocalTarget`](#annals.target.LocalTarget). |
| [`ssh_opts`](#annals.target.ssh_opts)(\*[, share_dir]) | The ssh options: batch mode, and one connection shared by consecutive calls.                                                                                      |

### Classes

| [`LocalTarget`](#annals.target.LocalTarget)(root)          | A directory on this machine.                                                |
|-----------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`SshTarget`](#annals.target.SshTarget)(host, root)      | `host:path` on another machine, via the system ssh and rsync in batch mode. |
| [`Target`](#annals.target.Target)(\*args, \*\*kwargs) | What the store needs from wherever the documents live.                      |

### annals.target.LOCK_NOTE *= 'lock.json'*

the note a lock directory is created with (see [`Target.make_lock()`](#annals.target.Target.make_lock))

### *class* annals.target.LocalTarget(root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A directory on this machine.

#### local_path(rel)

`rel` under the root, resolved; `None` if it escapes the root (a symlink).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.target.META_GLOB *= '\*/meta.json'*

each document’s meta.json

* **Type:**
  what [`Target.read_metas()`](#annals.target.Target.read_metas) reads by default

### annals.target.RECORD_SEP *= '\\x1e'*

Separator between concatenated meta.json files when reading many at once over ssh.

### annals.target.SSH_SHARE_S *= 60*

the several calls of one command
(and the next command soon after) reuse it instead of paying a handshake each (~3 s to a far host)

* **Type:**
  how long the shared ssh connection outlives its last use

### *class* annals.target.SshTarget(host, root)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

`host:path` on another machine, via the system ssh and rsync in batch mode.

### *class* annals.target.Target(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

What the store needs from wherever the documents live.

#### file_sizes(rel, files)

The byte size of each of `files` under `rel` that is a regular file.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

#### local_path(rel)

The file on this machine’s disk, when the documents are local (to stream it).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### make_lock(rel, note)

Create directory `rel` holding `lock.json` (`note`) as one step; fail if
it exists. An atomic test-and-set: a lock that is never seen without its note.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### move(rel_src, rel_dst)

Rename; fails when the source is gone or the destination already exists.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### read_metas(rel, , pattern='\*/meta.json')

Every JSON file under `rel` matching `pattern`, read in one go (hidden ones skipped).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### annals.target.check_glob(pattern)

A glob safe to hand a remote shell unquoted: names, `*` and `/` only, no hidden part.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.target.check_rel(rel)

Refuse anything that could escape the root; the store only ever passes safe paths.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.target.parse_target(spec)

`host:/path` becomes an [`SshTarget`](#annals.target.SshTarget); anything else a [`LocalTarget`](#annals.target.LocalTarget).

* **Return type:**
  [`Target`](#annals.target.Target)

### annals.target.ssh_opts(, share_dir=None)

The ssh options: batch mode, and one connection shared by consecutive calls.

The shared connection’s socket lives in `share_dir` (default `~/.ssh`); without that
directory every call opens its own connection, as plain `ssh` would.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]
