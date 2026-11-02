# annals.references

The references of documents, extracted and combined, in three forms.

A document’s references are the body of its references section: a markdown heading named
“References”, “Sources”, “Bibliography”, “Works cited” or “Citations” (any level, any case),
down to the next heading of the same or a higher level. Three forms, each text in, text out:

- `grouped` (the default): one `###` section per document holding its references as
  they are, under `## References for <title>`;
- `deduped`: every entry once, its citation number removed, as one bulleted list;
- `urls`: every web address once, one per line and nothing else, the form a notebook
  (Gemini Notebook, formerly NotebookLM) accepts as pasted website sources.

```pycon
>>> doc = '''# Bees
... Text [1].
... ## REFERENCES
... 1. [Hive life](https://bees.org/hive). 2024.
... [2] Smith J. Pollen, <https://pollen.net/a>
... ## Appendix
... not a reference https://no.org
... '''
>>> reference_sections(doc)
['1. [Hive life](https://bees.org/hive). 2024.\n[2] Smith J. Pollen, <https://pollen.net/a>']
>>> [strip_citation_number(e) for e in reference_entries(reference_sections(doc)[0])]
['[Hive life](https://bees.org/hive). 2024.', 'Smith J. Pollen, <https://pollen.net/a>']
>>> print(combine_references([("Bees", [doc]), ("Wasps", ["no references here"])],
...                          title="Insects", form="urls"), end="")
https://bees.org/hive
https://pollen.net/a
```

The mechanism knows nothing of the store: [`doc_reference_texts()`](#annals.references.doc_reference_texts) is the bridge that
reads a set of documents through a `read(doc_id, rel)` callable, so the owner’s API and,
later, a share can use it alike.

### Module Attributes

| [`REFERENCE_HEADINGS`](#annals.references.REFERENCE_HEADINGS)   | section names that hold references (a heading's text starts with one of them)   |
|-----------------------------------------------------------------------|---------------------------------------------------------------------------------|

### Functions

| [`combine_references`](#annals.references.combine_references)(items, \*, title[, form])   | `items` (a title and the texts of its pages) as their references in `form`.                  |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| [`doc_reference_texts`](#annals.references.doc_reference_texts)(docs, \*, read[, skip])    | `(title, texts)` for each of `docs` (`(meta, files)` pairs): its markdown pages' text.       |
| [`reference_entries`](#annals.references.reference_entries)(section)                     | The entries of a references section: each numbered or bulleted item, with its wrapped lines. |
| [`reference_sections`](#annals.references.reference_sections)(text)                       | The body of each references section of a markdown text, as written (blank edges trimmed).    |
| [`strip_citation_number`](#annals.references.strip_citation_number)(entry)                   | `entry` without its leading number or bullet (`1.`, `[1]`, `-`).                             |
| [`url_key`](#annals.references.url_key)(url)                                   | What makes two addresses the same page: no fragment, no trailing slash, host in lowercase.   |
| [`urls_of`](#annals.references.urls_of)(text)                                  | The web addresses in `text`, in order of appearance, each once as written.                   |

### annals.references.REFERENCE_HEADINGS *= ('references', 'sources', 'bibliography', 'works cited', 'citations')*

section names that hold references (a heading’s text starts with one of them)

### annals.references.combine_references(items, , title, form='grouped')

`items` (a title and the texts of its pages) as their references in `form`.

Items with no references section are left out. An empty string means none had any.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.references.doc_reference_texts(docs, \*, read, skip=(<class 'KeyError'>, <class 'OSError'>, <class 'ValueError'>))

`(title, texts)` for each of `docs` (`(meta, files)` pairs): its markdown pages’ text.

Pages come in [`numbered_first()`](annals.aggregate.html.md#annals.aggregate.numbered_first) order; a page `read` cannot read
(one of `skip`) is left out.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]

### annals.references.reference_entries(section)

The entries of a references section: each numbered or bulleted item, with its wrapped lines.

Prose that is not an item (an “Accessed on …” note) is not an entry. A section with no
list markers at all is one entry per non-blank line.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.references.reference_sections(text)

The body of each references section of a markdown text, as written (blank edges trimmed).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.references.strip_citation_number(entry)

`entry` without its leading number or bullet (`1.`, `[1]`, `-`).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.references.url_key(url)

What makes two addresses the same page: no fragment, no trailing slash, host in lowercase.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.references.urls_of(text)

The web addresses in `text`, in order of appearance, each once as written.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
