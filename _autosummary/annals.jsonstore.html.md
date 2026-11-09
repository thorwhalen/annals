# annals.jsonstore

A `MutableMapping` kept in one JSON file, safe with several server processes.

The owner’s tags ([`annals.tags`](annals.tags.html.md#module-annals.tags)) and each reader’s listening progress
([`annals.listening`](annals.listening.html.md#module-annals.listening)) are small, server-side records that the page changes one entry at
a time. [`JsonFileStore`](#annals.jsonstore.JsonFileStore) is that one mechanism: a JSON object in a file, written
atomically under an exclusive `flock`, re-read whenever another process changed it, and
never broken by a damaged file (it reads as empty and is kept aside at the next write).

A subclass says what a valid value is ([`JsonFileStore.valid()`](#annals.jsonstore.JsonFileStore.valid)) and how a value is
cleaned before it is stored ([`JsonFileStore.clean()`](#annals.jsonstore.JsonFileStore.clean)). [`JsonFileStore.modify()`](#annals.jsonstore.JsonFileStore.modify)
changes one entry from its current value under the lock, so two devices reporting at once
never lose each other’s change.

```pycon
>>> import tempfile, pathlib
>>> s = JsonFileStore(pathlib.Path(tempfile.mkdtemp()) / "x.json")
>>> s["a"] = {"n": 1}
>>> s.modify("a", lambda v: {"n": (v or {}).get("n", 0) + 1})
{'n': 2}
>>> dict(s)
{'a': {'n': 2}}
```

### Module Attributes

| [`DAMAGED_SUFFIX`](#annals.jsonstore.DAMAGED_SUFFIX)   | the suffix a damaged file is kept under, so a hand edit gone wrong can be recovered   |
|-------------------------------------------------------------------|---------------------------------------------------------------------------------------|

### Classes

| [`JsonFileStore`](#annals.jsonstore.JsonFileStore)(path)   | `{key: value}` in one JSON file, re-read when another process changed it.   |
|------------------------------------------------------------------------|-----------------------------------------------------------------------------|

### annals.jsonstore.DAMAGED_SUFFIX *= '.damaged'*

the suffix a damaged file is kept under, so a hand edit gone wrong can be recovered

### *class* annals.jsonstore.JsonFileStore(path)

Bases: [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

`{key: value}` in one JSON file, re-read when another process changed it.

A write takes an exclusive `flock` on `<file>.lock`, re-reads the file, changes it
and replaces it atomically. A read re-reads the file whenever its inode, size or mtime
changed (every write makes a new inode). `label` names the store in log messages.

#### clean(value)

The value as stored; raise `ValueError` to refuse it.

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

#### modify(key, change)

Set `key` to `change(current value or None)`, atomically; returns the stored value.

`change` returning `None` deletes the entry (and returns `None`).

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

#### snapshot()

Every entry at once, under one read (what a listing overlays).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

#### valid(value)

Whether a value read from the file is kept (an invalid one is logged and skipped).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
