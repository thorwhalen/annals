# annals.notebook

A share’s documents as separate notebook sources: one plain web page per text file.

A notebook product (NotebookLM, and Gemini’s notebooks, which share its sources) takes a
web page by its link, one source per link, and several links pasted at once; it reads
the page’s text and keeps its own copy. It does not unpack a zip, and its upload picker
needs the files on the device first. So the fewest taps from an iPad is: tick the
documents, copy one list of links, paste it into the notebook (see
`misc/docs/notebook-sources.md` for the research behind this).

The links are a share’s ([`annals.share`](annals.share.html.md#module-annals.share)): unguessable, scoped to the documents
ticked, expiring, revocable, and filtered like every shared text. This module only
decides what becomes a source and how one looks:

```default
GET <share link>/source/<doc id>/<file>   a script-free html page: <title>, the text
```

- [`source_files()`](#annals.notebook.source_files): which files of a document are sources (markdown and html pages,
  numbered files first, as [`annals.aggregate.numbered_first()`](annals.aggregate.html.md#annals.aggregate.numbered_first) orders them).
- [`notebook_sources()`](#annals.notebook.notebook_sources): the `{doc, file, title, url}` rows of a share, in its order.
- [`source_scope()`](#annals.notebook.source_scope): what a notebook share includes of a document: its source pages
  and the files they show, never the rest of a folder.
- [`render_source()`](#annals.notebook.render_source): one markdown file as its source page, shared-text rules applied
  twice: to the text ([`annals.share.filter_refs()`](annals.share.html.md#annals.share.filter_refs)), then to every link and image of
  the rendered page ([`annals.share.ref_decider()`](annals.share.html.md#annals.share.ref_decider) over markdown-it’s tokens), and
  any annals id left in it removed. Cached, and rendered only up to
  [`RENDER_MAX_BYTES`](#annals.notebook.RENDER_MAX_BYTES) (a larger file is sent as escaped text): it is a public route.
- [`source_page()`](#annals.notebook.source_page): the page a notebook reads. Its `<title>` is the document’s title,
  which the notebook shows as the source’s name, so the sources can be told apart.
- [`markdown_html()`](#annals.notebook.markdown_html): markdown to html; `markdown-it-py` when installed (the
  `pdf` extra), else the text escaped in a `<pre>`, which a notebook reads as well.

### Module Attributes

| [`SOURCE_KINDS`](#annals.notebook.SOURCE_KINDS)      | the kinds of file a notebook can take from a link (images, audio, video and pdf it takes only as uploads)         |
|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| [`SOURCE_SEGMENT`](#annals.notebook.SOURCE_SEGMENT)    | the path segment of a source page under a share link                                                              |
| [`SOURCE_CSS`](#annals.notebook.SOURCE_CSS)        | plain, readable, light or dark, no script and nothing loaded from elsewhere                                       |
| [`SOURCE_CSP`](#annals.notebook.SOURCE_CSP)        | ones), nothing else; a sandbox (no origin, no script, no form) even so, since it is served beside the owner's app |
| [`HTML_SOURCE_CSP`](#annals.notebook.HTML_SOURCE_CSP)   | its own styles and images, no script, no request elsewhere                                                        |
| [`RENDER_MAX_BYTES`](#annals.notebook.RENDER_MAX_BYTES)  | rendering is superlinear on hostile input, and the route is public                                                |
| [`SOURCE_CACHE_SIZE`](#annals.notebook.SOURCE_CACHE_SIZE) | rendered source pages kept in memory (each at most a few times RENDER_MAX_BYTES)                                  |

### Functions

| [`markdown_html`](#annals.notebook.markdown_html)(text, \*[, rewrite_url, render])    | `text` (markdown) as html; every link and image through `rewrite_url`.                    |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| [`notebook_sources`](#annals.notebook.notebook_sources)(scope, \*, link)                 | One row per source file of `scope` (`(meta, files)` pairs, in the share's order).         |
| [`render_source`](#annals.notebook.render_source)(text, \*, title, link, doc_id, ...) | One markdown file of a share as its source page (see the module docstring).               |
| [`source_files`](#annals.notebook.source_files)(meta, files)                         | The files of a document (`files`: those a caller may serve) that are sources.             |
| [`source_link_rewriter`](#annals.notebook.source_link_rewriter)(decide, \*, link, ...)       | `url -> url | None` for a source page, which has no `<base>`.                             |
| [`source_page`](#annals.notebook.source_page)(title, body_html)                     | The page a notebook reads: a `<title>`, the body, plain style, no script.                 |
| [`source_scope`](#annals.notebook.source_scope)(read_text)                           | `meta -> files`: a document's source pages and the files they show, for a share.          |
| [`source_title`](#annals.notebook.source_title)(meta, rel, \*, several)              | The source's name in the notebook: the document's title, plus the file if it has several. |
| [`source_url`](#annals.notebook.source_url)(link, doc_id, rel)                     | `<link>/source/<doc id>/<file>` (`link`: the share's, with or without a slash).           |

### annals.notebook.HTML_SOURCE_CSP *= "sandbox; default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"*

its own styles and images, no script, no request elsewhere

* **Type:**
  an html source

### annals.notebook.RENDER_MAX_BYTES *= 300000*

rendering is
superlinear on hostile input, and the route is public

* **Type:**
  markdown past this size is sent as escaped text, not rendered

### annals.notebook.SOURCE_CACHE_SIZE *= 32*

rendered source pages kept in memory (each at most a few times RENDER_MAX_BYTES)

### annals.notebook.SOURCE_CSP *= "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"*

ones), nothing else; a
sandbox (no origin, no script, no form) even so, since it is served beside the owner’s app

* **Type:**
  what a source page may do
* **Type:**
  show its own images (and data

### annals.notebook.SOURCE_CSS *= ":root{color-scheme:light dark}body{font:17px/1.6 system-ui,-apple-system,'Segoe UI',sans-serif;max-width:46rem;margin:0 auto;padding:1.5rem 1rem 4rem}pre,code{font-family:ui-monospace,Menlo,monospace;font-size:.9em}pre{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse}th,td{border:1px solid #8884;padding:.3em .6em}img{max-width:100%;height:auto}"*

plain, readable,
light or dark, no script and nothing loaded from elsewhere

* **Type:**
  a source page is read by a fetcher and, now and then, by a person

### annals.notebook.SOURCE_KINDS *= ('md', 'html')*

the kinds of file a notebook can take from a link (images, audio, video and pdf it
takes only as uploads)

### annals.notebook.SOURCE_SEGMENT *= 'source'*

the path segment of a source page under a share link

### annals.notebook.markdown_html(text, , rewrite_url=None, render=None)

`text` (markdown) as html; every link and image through `rewrite_url`.

`render(text, rewrite_url)` overrides the default renderer. Without one (no
`markdown-it-py`) the text is escaped in a `<pre>`: no markup, so no link.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.notebook.notebook_sources(scope, , link)

One row per source file of `scope` (`(meta, files)` pairs, in the share’s order).

`{"sources": [{"doc", "file", "title", "url"}], "skipped": [{"doc", "title",
"kinds"}]}`; `skipped` names the documents with nothing a notebook can take from a
link (only images, audio, pdf…), so the page can say why they are missing.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.notebook.render_source(text, , title, link, doc_id, rel, files, sources, shared_ids, root_id='', private_hosts=())

One markdown file of a share as its source page (see the module docstring).

Every argument is hashable, so a page is rendered once per text and scope.
`shared_ids` are the annals ids the share includes (opened at `<link>/d/<id>`),
`root_id` the shared group’s (opened at `<link>/`).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.notebook.source_files(meta, files)

The files of a document (`files`: those a caller may serve) that are sources.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.notebook.source_link_rewriter(decide, , link, doc_id, from_dir, sources)

`url -> url | None` for a source page, which has no `<base>`.

`decide` ([`annals.share.ref_decider()`](annals.share.html.md#annals.share.ref_decider)) says what may stay; a relative file it
keeps becomes absolute here: another source page of the document links to that
page, any other file to the share’s raw file. Anchors and web links stay as they are.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### annals.notebook.source_page(title, body_html)

The page a notebook reads: a `<title>`, the body, plain style, no script.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.notebook.source_scope(read_text)

`meta -> files`: a document’s source pages and the files they show, for a share.

`read_text(doc_id, rel)` reads one file. A notebook share made with this (the
`files_of` of [`annals.share.Shares.create()`](annals.share.html.md#annals.share.Shares.create)) reaches nothing else of a folder.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)], [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### annals.notebook.source_title(meta, rel, , several)

The source’s name in the notebook: the document’s title, plus the file if it has several.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.notebook.source_url(link, doc_id, rel)

`<link>/source/<doc id>/<file>` (`link`: the share’s, with or without a slash).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
