# annals.titles

A title for a file whose name says nothing: `overview.mp3`, `output.html`, `index.md`.

A document is titled by what it says (a `# heading`, a `<title>`), else by its file
name. Tools that make media often name every output the same (podpatch and hailing both
write `<folder>/overview.mp3`), so seven audio overviews were all titled “overview”. When
the file name is one of [`GENERIC_STEMS`](#annals.titles.GENERIC_STEMS), the title comes from beside the file
instead: the `title` of a JSON manifest in its folder ([`TITLE_FILES`](#annals.titles.TITLE_FILES)), else the
folder’s own name without its date and hash, but only when the folder was made by a tool
(its name carries a date stamp or a short hash): a person’s folder (their home, a repo, a
client’s) never names a document, since a title shows wherever the document is shared.

```pycon
>>> is_generic("overview") and is_generic("Final_Output") and not is_generic("theremin")
True
>>> folder_title("20261119-223540-theremin-and-gesture-controlled-7d32")
'theremin and gesture controlled'
```

### Module Attributes

| [`GENERIC_STEMS`](#annals.titles.GENERIC_STEMS)         | file names (without extension) that never title a document on their own       |
|------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| [`TITLE_FILES`](#annals.titles.TITLE_FILES)           | files a maker writes beside its output whose `title` names it, tried in order |
| [`MAX_TITLE`](#annals.titles.MAX_TITLE)             | the longest title taken from a manifest (a rename allows as much)             |
| [`UNINFORMATIVE_FOLDERS`](#annals.titles.UNINFORMATIVE_FOLDERS) | folder names that say nothing either (a title from one would be noise)        |

### Functions

| [`folder_title`](#annals.titles.folder_title)(name)              | A tool's output folder's name as a title: date stamp and trailing hash dropped, separators spaced; `""` for a folder no tool made (no stamp and no hash), or one whose words are only digits and hex (a uuid, a temporary folder's name).   |
|----------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`is_generic`](#annals.titles.is_generic)(stem, \*[, generic]) | Whether a file name (without extension) says nothing about what it holds: one of `generic`, or two of them ("final output", "audio overview").                                                                                              |
| [`title_beside`](#annals.titles.title_beside)(path)              | A title for the file `path` from what is beside it (see the module doc), or `None` when its folder says nothing either.                                                                                                                     |

### annals.titles.GENERIC_STEMS *= frozenset({'audio', 'document', 'export', 'file', 'final', 'index', 'main', 'narration', 'out', 'output', 'overview', 'page', 'player', 'recording', 'render', 'report', 'result', 'speech', 'summary', 'take', 'track', 'untitled', 'video', 'voice'})*

file names (without extension) that never title a document on their own

### annals.titles.MAX_TITLE *= 200*

the longest title taken from a manifest (a rename allows as much)

### annals.titles.TITLE_FILES *= ('manifest.json', 'meta.json', 'script.json', 'info.json')*

files a maker writes beside its output whose `title` names it, tried in order

### annals.titles.UNINFORMATIVE_FOLDERS *= frozenset({'desktop', 'documents', 'downloads', 'home', 'overviews', 'root', 'scratchpad', 'temp', 'tmp', 'work'})*

folder names that say nothing either (a title from one would be noise)

### annals.titles.folder_title(name)

A tool’s output folder’s name as a title: date stamp and trailing hash dropped,
separators spaced; `""` for a folder no tool made (no stamp and no hash), or one whose
words are only digits and hex (a uuid, a temporary folder’s name).

```pycon
>>> folder_title("2026-11-22-tables-and-session-links"), folder_title("thorwhalen")
('tables and session links', '')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.titles.is_generic(stem, , generic=frozenset({'audio', 'desktop', 'document', 'documents', 'downloads', 'export', 'file', 'final', 'home', 'index', 'main', 'narration', 'out', 'output', 'overview', 'overviews', 'page', 'player', 'recording', 'render', 'report', 'result', 'root', 'scratchpad', 'speech', 'summary', 'take', 'temp', 'tmp', 'track', 'untitled', 'video', 'voice', 'work'}))

Whether a file name (without extension) says nothing about what it holds: one of
`generic`, or two of them (“final output”, “audio overview”).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.titles.title_beside(path)

A title for the file `path` from what is beside it (see the module doc), or `None`
when its folder says nothing either.

```pycon
>>> import tempfile, os
>>> d = Path(tempfile.mkdtemp()) / "20261119-223540-theremin-7d32"; d.mkdir()
>>> title_beside(d / "overview.mp3")
'theremin'
>>> _ = (d / "manifest.json").write_text('{"title": "The Theremin: Invention, Spies"}')
>>> title_beside(d / "overview.mp3")
'The Theremin: Invention, Spies'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
