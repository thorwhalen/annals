# annals.aggregate

Many markdown files as ONE markdown document: a title, a table of contents, a section per file.

The mechanism is text in, text out. [`aggregate_markdown()`](#annals.aggregate.aggregate_markdown) takes `(path, text)` pairs
and knows nothing of documents, groups or shares; its choices are keyword arguments with
working defaults:

```default
>>> print(aggregate_markdown(
...     {"notes.md": "# Notes\nOne line\nwrapped.", "01-intro.md": "Hello."},
...     title="Bundle"), end="")
# Bundle

**Contents**

- [01-intro.md](#01-intromd)
- [notes.md](#notesmd)

## 01-intro.md

Hello.

## notes.md

## Notes
One line wrapped.
```

- `order`: how the files are arranged; [`numbered_first()`](#annals.aggregate.numbered_first) by default (paths whose
  parts start with a number first, numerically, the rest in the order given), `None`
  keeps the order given, or any `paths -> paths` callable.
- `demote`: how many levels each file’s own headings go down (`1`: a file’s `#`
  becomes `##`); `0` leaves them.
- `unwrap`: join hard-wrapped lines of a paragraph or list item into one line
  ([`unwrap_lines()`](#annals.aggregate.unwrap_lines)); code, tables, quotes and html are left as they are.
- `toc`: the table of contents, as links to the sections’ GitHub-style anchors.

[`doc_markdown_files()`](#annals.aggregate.doc_markdown_files) is the bridge from annals documents: it yields the pairs for a
set of documents and the files of each a caller may read, through a `read` callable, so
the owner’s API, the share server (which reads filtered text) and the CLI share it.
Nothing is stored: the document is made per request.

### Functions

| [`aggregate_markdown`](#annals.aggregate.aggregate_markdown)(files, \*[, title, order, ...])   | One markdown document of `files` (`{path: text}` or `(path, text)` pairs).              |
|-------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| [`demote_headings`](#annals.aggregate.demote_headings)(text[, levels, max_level])           | `text` with every heading `levels` deeper (at most `max_level`); code untouched.        |
| [`doc_markdown_files`](#annals.aggregate.doc_markdown_files)(docs, \*, read[, ...])            | `(path, text)` for every markdown file of `docs` (`(meta, files)` pairs).               |
| [`heading_anchor`](#annals.aggregate.heading_anchor)(text[, seen])                         | The id GitHub (and most renderers) give a heading; `seen` numbers repeats.              |
| [`numbered_first`](#annals.aggregate.numbered_first)(paths)                                | `paths` with numbered ones first, compared part by part, the rest in their given order. |
| [`strip_front_matter`](#annals.aggregate.strip_front_matter)(text)                             | `text` without a leading YAML front-matter block (`---` .                               |
| [`unwrap_lines`](#annals.aggregate.unwrap_lines)(text)                                   | `text` with hard-wrapped paragraphs and list items joined into one line each.           |

### Exceptions

| [`TooLarge`](#annals.aggregate.TooLarge)   | The markdown to aggregate is over the size a caller allows.   |
|-------------------------------------------------------------|---------------------------------------------------------------|

### *exception* annals.aggregate.TooLarge

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

The markdown to aggregate is over the size a caller allows.

### annals.aggregate.aggregate_markdown(files, \*, title='', order=<function numbered_first>, demote=1, unwrap=True, toc=True, section_level=2)

One markdown document of `files` (`{path: text}` or `(path, text)` pairs).

A `# title`, a table of contents, then one section per file, headed by its path,
with the file’s text below (front matter dropped, headings `demote`-d, lines
unwrapped); see the module docstring for each choice.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.aggregate.demote_headings(text, levels=1, , max_level=6)

`text` with every heading `levels` deeper (at most `max_level`); code untouched.

Setext headings (a line underlined with `===` or `---`) become `#` headings.

```pycon
>>> print(demote_headings("# A\nB\n---\n```\n# code\n```"))
## A
### B
```

```text
# code
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.aggregate.doc_markdown_files(docs, \*, read, max_bytes=None, skip=(<class 'KeyError'>, <class 'OSError'>, <class 'ValueError'>))

`(path, text)` for every markdown file of `docs` (`(meta, files)` pairs).

`files` are the files of that document the caller may read, and `read(doc_id,
rel)` reads one (the share server passes its filtered reader). A document whose one
markdown file is its page is named by that file; a folder, or a document with several
markdown files, by its title then the file (`Report/01-intro.md`). A file `read`
cannot read (one of `skip`) is left out; past `max_bytes` in all, [`TooLarge`](#annals.aggregate.TooLarge).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### annals.aggregate.heading_anchor(text, seen=None)

The id GitHub (and most renderers) give a heading; `seen` numbers repeats.

```pycon
>>> seen = {}
>>> heading_anchor("01-intro.md", seen), heading_anchor("01-intro.md", seen)
('01-intromd', '01-intromd-1')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.aggregate.numbered_first(paths)

`paths` with numbered ones first, compared part by part, the rest in their given order.

A part (a folder or file name) that starts with digits sorts by that number, before any
part that does not; parts without a number keep the order they first appeared in, so a
folder’s files stay together.

```pycon
>>> numbered_first(["b.md", "10-z.md", "a.md", "2-y.md", "r/02.md", "r/01.md"])
['2-y.md', '10-z.md', 'b.md', 'a.md', 'r/01.md', 'r/02.md']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.aggregate.strip_front_matter(text)

`text` without a leading YAML front-matter block (`---` … `---`).

It must start with a `key:` line, so a page that opens with a horizontal rule
keeps it.

```pycon
>>> strip_front_matter("---\ntitle: x\n---\n# Body")
'# Body'
>>> strip_front_matter("---\nIntro\n---\nbody")
'---\nIntro\n---\nbody'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.aggregate.unwrap_lines(text)

`text` with hard-wrapped paragraphs and list items joined into one line each.

Only ordinary text lines are joined: headings, list markers, quotes, tables, html,
fenced or indented code, and a line ending in a hard break (two spaces or `\`)
keep their line breaks.

```pycon
>>> print(unwrap_lines("A long\nsentence.\n\n- item\n  goes on\n- next\n\n    code\n    more"))
A long sentence.

- item goes on
- next

    code
    more
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
