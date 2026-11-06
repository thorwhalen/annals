# annals.combine

Many files of many kinds as ONE document: a Markdown, html or PDF file.

The mechanism is a registry. A *converter* turns one file of one kind into a *part* of the
output format (markdown text, an html fragment, a PDF); a *joiner* puts the parts of a
format together (a table of contents and a section each; bookmarks and pages). Which pairs
exist is the table [`REGISTRY`](#annals.combine.REGISTRY), filled by [`register()`](#annals.combine.register):

```default
@register("pdf", "md", requires=("pdfdol",))
def pdf_to_md(item, ctx): ...
```

so a new pair (docx to pdf, say) is one decorated function, and the web page, the API and
the CLI all learn it from [`supported()`](#annals.combine.supported) without a change.

What goes in:

```default
=========  ===========  =======================================================
input      to md        to html / to pdf
=========  ===========  =======================================================
md         as it is     rendered (images of the document inside)
html       converted    its text and structure (scripts and styles dropped)
text       a code block a preformatted block
pdf        its text     html: its text; pdf: its pages, joined as they are
image      -            a figure (html) / a page of its own (pdf)
=========  ===========  =======================================================
```

Audio, video and other files have no place in a document: they are reported as left out,
each with the reason, never silently dropped. A file that cannot be read (a damaged or
password-protected PDF) is left out the same way, and the others still go in.

An image or a text file that sits in a document with pages (markdown, html, a PDF) is part
of that document, not a section of its own: a report and its figures combine as the report.

Heavy libraries load only when a pair needs them (WeasyPrint for PDF pages, pypdf and pdfdol
to join and read PDFs, markdownify for html to markdown); a missing one is a
[`annals.requirements.MissingDependency`](annals.requirements.html.md#annals.requirements.MissingDependency) that says what to install, raised before any
work starts. Nothing is stored: the document is made per call.

```pycon
>>> combined = combine([_demo_source({"b.md": "# B\ntext", "a.md": "hello"})], "md", title="T")
>>> combined.sections, combined.ext
(2, 'md')
>>> print(combined.data.decode().splitlines()[0])
# T
```

### Module Attributes

| [`PAGE_KINDS`](#annals.combine.PAGE_KINDS)          | kinds whose file is a document in itself                                                                                                             |
|----------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`COMPANION_KINDS`](#annals.combine.COMPANION_KINDS)     | kinds that illustrate or accompany a document with pages, so are not sections of its own                                                             |
| [`MAX_SKIPPED_LISTED`](#annals.combine.MAX_SKIPPED_LISTED)  | skipped files listed in a result (and its headers); the rest are counted                                                                             |
| [`MAX_TEXT_PAGES`](#annals.combine.MAX_TEXT_PAGES)      | a PDF with more pages than this is not read for its text (about 0.2 s a page)                                                                        |
| [`MAX_RENDERED_FILES`](#annals.combine.MAX_RENDERED_FILES)  | files made into PDF pages by rendering (about 0.4 s each) in one output                                                                              |
| [`MAX_TEXT_FILE_BYTES`](#annals.combine.MAX_TEXT_FILE_BYTES) | a text or html file larger than this is left out, and the others still go in                                                                         |
| [`MAX_HTML_DEPTH`](#annals.combine.MAX_HTML_DEPTH)      | html nested deeper than this is flattened (very deep trees overflow the converters)                                                                  |
| [`MAX_SPAN`](#annals.combine.MAX_SPAN)            | a table cell may span this many columns or rows (a bigger number is a layout attack)                                                                 |
| [`HTML_DEMOTE`](#annals.combine.HTML_DEMOTE)         | headings of an embedded markdown or html file go this far down, under the section's own                                                              |
| [`REGISTRY`](#annals.combine.REGISTRY)            | (kind, format) -> [`Pair`](#annals.combine.Pair); add a pair with [`register()`](#annals.combine.register) |
| [`HTML_CSP`](#annals.combine.HTML_CSP)            | show itself, with its own styles and embedded images                                                                                                 |

### Functions

| [`combine`](#annals.combine.combine)(sources[, fmt, title, demote, toc, ...])   | Every usable file of `sources` as one `fmt` ("md", "html" or "pdf") file.              |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|
| [`explain`](#annals.combine.explain)(fmt)                                       | One sentence on what a `fmt` output is made of (the 'supported' part of a message).    |
| [`html_body`](#annals.combine.html_body)(text, \*[, rewrite_src, demote])         | The content of an html page as a safe fragment: its structure and words, nothing live. |
| [`items_of`](#annals.combine.items_of)(sources, fmt)                             | The files to try for a `fmt` output, in the documents' order.                          |
| [`kinds_for`](#annals.combine.kinds_for)(fmt)                                     | The kinds of file that can be put in a `fmt` output, in a stable order.                |
| [`register`](#annals.combine.register)(kind, fmt, \*[, requires])                | Decorator: the function turns a file of `kind` into a part of the `fmt` output.        |
| [`skipped_header`](#annals.combine.skipped_header)(skipped)                            | The skipped files as compact JSON for a response header: few, short, ascii.            |
| [`supported`](#annals.combine.supported)()                                        | What can be made: `{format: {"label", "ext", "kinds"}}`, for a page or a message.      |

### Classes

| [`Combined`](#annals.combine.Combined)(data, fmt, media_type, ext, sections)    | The result: the file's bytes, what it is, how many files went in and which did not.     |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| [`Context`](#annals.combine.Context)(fmt[, embedder])                          | What a converter may use besides the item: where images go, and the output's own needs. |
| [`Format`](#annals.combine.Format)(name, label, ext, media_type, join[, ...]) | An output format: how it is named, joined, and whether each file gets its own context.  |
| [`Item`](#annals.combine.Item)(source, rel, kind, label, title)             | One file to put in the output: a section, or a run of pages.                            |
| [`Job`](#annals.combine.Job)(title, demote, embedder[, toc, unwrap])       | What a joiner needs besides the parts.                                                  |
| [`Pair`](#annals.combine.Pair)(kind, fmt, fn[, requires])                   | One (kind, format) cell of the registry.                                                |
| [`Skipped`](#annals.combine.Skipped)(label, reason)                            | A file left out, and why.                                                               |
| [`Source`](#annals.combine.Source)(meta, files, read_text, open_path[, ...])  | One document, as a caller lets it be read: its files and how to get at them.            |

### Exceptions

| [`ConversionError`](#annals.combine.ConversionError)   | One file could not be converted (damaged, protected, too large); the rest go on.   |
|--------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`NothingToCombine`](#annals.combine.NothingToCombine)  | No file could be put in the output (the message says which kinds could).           |

### annals.combine.COMPANION_KINDS *= frozenset({'image', 'text'})*

kinds that illustrate or accompany a document with pages, so are not sections of its own

### *class* annals.combine.Combined(data, fmt, media_type, ext, sections, skipped=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The result: the file’s bytes, what it is, how many files went in and which did not.

### *class* annals.combine.Context(fmt, embedder=Embedder())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a converter may use besides the item: where images go, and the output’s own needs.

### *exception* annals.combine.ConversionError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

One file could not be converted (damaged, protected, too large); the rest go on.

### *class* annals.combine.Format(name, label, ext, media_type, join, requires=(), context_per_item=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

An output format: how it is named, joined, and whether each file gets its own context.

#### context_per_item *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

one context (images, budget) per file rather than one for the whole output

### annals.combine.HTML_CSP *= "default-src 'none'; img-src data:; style-src 'unsafe-inline'"*

show itself, with its own styles and embedded images

* **Type:**
  what a combined html page may do

### annals.combine.HTML_DEMOTE *= 2*

headings of an embedded markdown or html file go this far down, under the section’s own

### *class* annals.combine.Item(source, rel, kind, label, title)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One file to put in the output: a section, or a run of pages.

### *class* annals.combine.Job(title, demote, embedder, toc=True, unwrap=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a joiner needs besides the parts.

### annals.combine.MAX_HTML_DEPTH *= 100*

html nested deeper than this is flattened (very deep trees overflow the converters)

### annals.combine.MAX_RENDERED_FILES *= 60*

files made into PDF pages by rendering (about 0.4 s each) in one output

### annals.combine.MAX_SKIPPED_LISTED *= 4*

skipped files listed in a result (and its headers); the rest are counted

### annals.combine.MAX_SPAN *= 100*

a table cell may span this many columns or rows (a bigger number is a layout attack)

### annals.combine.MAX_TEXT_FILE_BYTES *= 2000000*

a text or html file larger than this is left out, and the others still go in

### annals.combine.MAX_TEXT_PAGES *= 300*

a PDF with more pages than this is not read for its text (about 0.2 s a page)

### *exception* annals.combine.NothingToCombine

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

No file could be put in the output (the message says which kinds could).

### annals.combine.PAGE_KINDS *= frozenset({'html', 'md', 'pdf'})*

kinds whose file is a document in itself

### *class* annals.combine.Pair(kind, fmt, fn, requires=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One (kind, format) cell of the registry.

### annals.combine.REGISTRY *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)], [Pair](#annals.combine.Pair)]* *= {('html', 'html'): Pair(kind='html', fmt='html', fn=<function \_html_body_of>, requires=()), ('html', 'md'): Pair(kind='html', fmt='md', fn=<function \_html_to_md>, requires=('markdownify',)), ('html', 'pdf'): Pair(kind='html', fmt='pdf', fn=<function \_page_to_pdf.<locals>.convert>, requires=('weasyprint',)), ('image', 'html'): Pair(kind='image', fmt='html', fn=<function \_image_body>, requires=()), ('image', 'pdf'): Pair(kind='image', fmt='pdf', fn=<function \_page_to_pdf.<locals>.convert>, requires=('weasyprint',)), ('md', 'html'): Pair(kind='md', fmt='html', fn=<function \_md_body>, requires=('markdown_it',)), ('md', 'md'): Pair(kind='md', fmt='md', fn=<function \_md_to_md>, requires=()), ('md', 'pdf'): Pair(kind='md', fmt='pdf', fn=<function \_page_to_pdf.<locals>.convert>, requires=('markdown_it', 'weasyprint')), ('pdf', 'html'): Pair(kind='pdf', fmt='html', fn=<function \_pdf_body>, requires=('pdfdol', 'pypdf')), ('pdf', 'md'): Pair(kind='pdf', fmt='md', fn=<function \_pdf_to_md>, requires=('pdfdol', 'pypdf')), ('pdf', 'pdf'): Pair(kind='pdf', fmt='pdf', fn=<function \_pdf_to_pdf>, requires=('pypdf', 'pdfdol')), ('text', 'html'): Pair(kind='text', fmt='html', fn=<function \_text_body>, requires=()), ('text', 'md'): Pair(kind='text', fmt='md', fn=<function \_text_to_md>, requires=()), ('text', 'pdf'): Pair(kind='text', fmt='pdf', fn=<function \_page_to_pdf.<locals>.convert>, requires=('weasyprint',))}*

(kind, format) -> [`Pair`](#annals.combine.Pair); add a pair with [`register()`](#annals.combine.register)

### *class* annals.combine.Skipped(label, reason)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A file left out, and why.

### *class* annals.combine.Source(meta, files, read_text, open_path, file_url=<function Source.<lambda>>, read_bytes=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One document, as a caller lets it be read: its files and how to get at them.

`read_text(rel)` is the file’s text (a share gives the *filtered* text);
`open_path(rel)` its path on disk, for bytes. Either may raise `OSError` or
`KeyError` for a file that is gone, which leaves that file out.

#### read_bytes *: [Callable](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[str](https://docs.python.org/3/builtins/stdtypes.html#str)], [bytes](https://docs.python.org/3/builtins/stdtypes.html#bytes)] | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

how bytes are read when not straight from `open_path` (a share filters svg text)

### annals.combine.combine(sources, fmt='md', \*, title='', demote=1, toc=True, unwrap=True, order=<function numbered_first>, max_text_bytes=8000000, max_input_bytes=120000000, registry=None)

Every usable file of `sources` as one `fmt` (“md”, “html” or “pdf”) file.

`sources` are the documents ([`Source`](#annals.combine.Source)), in their order; files are arranged by
`order` ([`annals.aggregate.numbered_first()`](annals.aggregate.html.md#annals.aggregate.numbered_first): numbered names first, numerically;
`None` keeps the documents’ order). `demote` is how far an embedded markdown file’s
headings go down in a markdown output, which also takes `toc` (a table of contents)
and `unwrap` (join hard-wrapped lines). `max_text_bytes` caps all the text read
([`annals.aggregate.TooLarge`](annals.aggregate.html.md#annals.aggregate.TooLarge)), `max_input_bytes` all the files together.

A file with no converter, or that cannot be read, is left out and listed in
`Combined.skipped` with the reason. Raises [`NothingToCombine`](#annals.combine.NothingToCombine) when nothing is
left, [`annals.requirements.MissingDependency`](annals.requirements.html.md#annals.requirements.MissingDependency) when a library the conversions need
is not installed (before any work), and `ValueError` for an unknown `fmt`.

* **Return type:**
  [`Combined`](#annals.combine.Combined)

### annals.combine.explain(fmt)

One sentence on what a `fmt` output is made of (the ‘supported’ part of a message).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.combine.html_body(text, \*, rewrite_src=<function <lambda>>, demote=0)

The content of an html page as a safe fragment: its structure and words, nothing live.

Only a fixed set of tags survives, with a few plain attributes: no script, style, frame,
form, event handler, `class` or `id`; a link keeps only an `http(s)` or `mailto`
address. `rewrite_src(src)` decides each image: the url to show it from, or `None`
for its alt text instead (an image is never loaded from where the page says). `demote`
pushes headings that many levels down. Unbalanced tags are closed, so a fragment can
never swallow what is joined after it.

```pycon
>>> html_body('<body><script>x()</script><h1 onclick="x()">Hi</h1><a href="javascript:x()">y</a></body>')
'<h1>Hi</h1><a>y</a>'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.combine.items_of(sources, fmt)

The files to try for a `fmt` output, in the documents’ order.

A document with pages (markdown, html, PDF) contributes those; its images and text
files are its own parts. A document with none contributes whatever it holds, so what
cannot be used (a video) is reported and not silently missing. A folder, or a document
with several such files, names each by its title then the file (`Report/01-intro.md`).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`Item`](#annals.combine.Item)]

### annals.combine.kinds_for(fmt)

The kinds of file that can be put in a `fmt` output, in a stable order.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### annals.combine.register(kind, fmt, , requires=())

Decorator: the function turns a file of `kind` into a part of the `fmt` output.

`requires` are the (importable) modules it needs, checked before any work starts.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Item`](#annals.combine.Item), [`Context`](#annals.combine.Context)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]], [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Item`](#annals.combine.Item), [`Context`](#annals.combine.Context)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]]

### annals.combine.skipped_header(skipped)

The skipped files as compact JSON for a response header: few, short, ascii.

At most [`MAX_SKIPPED_LISTED`](#annals.combine.MAX_SKIPPED_LISTED) are listed (the count says how many there were) and
names and reasons are cut, so the header stays far under what a proxy accepts.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.combine.supported()

What can be made: `{format: {"label", "ext", "kinds"}}`, for a page or a message.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
