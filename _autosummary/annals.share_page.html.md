# annals.share_page

A share link’s page with its text in it, and no script, so every reader can read it.

A share link used to answer with a shell: a `<title>` and an empty `<div>` that the
viewer’s script filled, with an html document inside a frame. NotebookLM made a
twenty-minute audio overview of such a link’s title. Its fetcher does run script, so it saw
the viewer’s buttons, but a group shows only titles there and a frame is not read. So the
page a link opens is now the shared text itself, rendered on the server under the rules
every shared text already follows, and nothing on it runs. The owner asked for exactly that:
a person only needs the document. The script viewer (galleries, players, downloads) is one
link away, `<link>/?viewer`.

The same share also answers as one Markdown file and one PDF, with the same token, expiry
and revocation (the routes are `annals.share_api`’s); the page names them in
`<link rel="alternate">` and in a line at its top:

```default
<link>/                 the page: every shared document's text (a group's, in order)
<link>/d/<id>           the page of one document of the share
<link>/share.md         the whole share as one Markdown file
<link>/share.pdf        the whole share as one PDF (images included)
<link>/d/<id>.md|.pdf   one document of it
<link>/?viewer          the script viewer, as before
```

What goes in the page, per document: its markdown and html files (the notebook sources of
[`annals.notebook`](annals.notebook.html.md#module-annals.notebook), numbered files first), markdown rendered with links and images
made safe by [`annals.notebook.render_source_body()`](annals.notebook.html.md#annals.notebook.render_source_body), html reduced to its structure and
words by [`annals.combine.html_body()`](annals.combine.html.md#annals.combine.html_body) with a link to the page as designed; for a
document with no text, its images; its audio and video with the browser’s own players;
then links to its other files. Past [`STATIC_MAX_BYTES`](#annals.share_page.STATIC_MAX_BYTES) of text or
[`STATIC_MAX_FILES`](#annals.share_page.STATIC_MAX_FILES) files, the remaining files and documents are links to their own pages, so a large group still answers quickly and every
document stays reachable. A document that *is* an html page ([`designed_page()`](#annals.share_page.designed_page)) is
served as itself at its own link, filtered and sandboxed as `/raw` serves it, with a
`<base>` ([`with_base()`](#annals.share_page.with_base)) so its images and styles load.

### Module Attributes

| [`STATIC_MAX_BYTES`](#annals.share_page.STATIC_MAX_BYTES)      | the page's text stops growing past this many bytes of html; later documents are links                                                         |
|------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| [`STATIC_MAX_FILES`](#annals.share_page.STATIC_MAX_FILES)      | the text files rendered into one page at most; the rest are links (a page is made on every request, and anyone holding the link may make one) |
| [`STATIC_FILE_MAX_BYTES`](#annals.share_page.STATIC_FILE_MAX_BYTES) | a document's file larger than this is linked, not put in the page                                                                             |
| [`STATIC_MAX_IMAGES`](#annals.share_page.STATIC_MAX_IMAGES)     | images shown for a document without text (a gallery folder); the rest are listed                                                              |
| [`STATIC_MAX_PLAYERS`](#annals.share_page.STATIC_MAX_PLAYERS)    | audio and video players in one document's page; the rest are listed                                                                           |
| [`DESCRIPTION_CHARS`](#annals.share_page.DESCRIPTION_CHARS)     | the length of the page's `<meta name="description">`                                                                                          |
| [`ALTERNATES`](#annals.share_page.ALTERNATES)            | path suffix, media type, label                                                                                                                |
| [`SHARE_FILE`](#annals.share_page.SHARE_FILE)            | the share's whole text, at `<link>/<SHARE_FILE>.<ext>`                                                                                        |
| [`VIEWER_PARAM`](#annals.share_page.VIEWER_PARAM)          | `<link>/?viewer` opens the script viewer (galleries, players, downloads) instead                                                              |

### Functions

| [`alternate_links`](#annals.share_page.alternate_links)(link[, doc_id])              | The `<link rel="alternate">` tags of [`alternate_urls()`](#annals.share_page.alternate_urls), for the `<head>`.                              |
|-----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`alternate_urls`](#annals.share_page.alternate_urls)(link[, doc_id])               | `(url, media type, label)` of the share (or of one document of it) as files.                                                                           |
| [`description_of`](#annals.share_page.description_of)(content, \*[, skip, n])       | The first `n` characters of the page's words (the title and alternates line left out).                                                                 |
| [`designed_page`](#annals.share_page.designed_page)(meta, files)                   | The html file a document's page *is*, when it is one, else `None`.                                                                                     |
| [`page_body`](#annals.share_page.page_body)(docs, \*, title, read_text, scope) | The page's content and its description: `(html, plain text of ~280 chars)`.                                                                            |
| [`with_base`](#annals.share_page.with_base)(page, href)                        | `page` with `<base href>` as its first element, so its relative references (images, styles, its other pages) resolve where the share serves its files. |

### Classes

| [`ShareScope`](#annals.share_page.ShareScope)(link, shared_ids[, root_id, ...])   | What a page of one share may show and link to.   |
|-------------------------------------------------------------------------------------------------|--------------------------------------------------|

### annals.share_page.ALTERNATES *= (('md', 'text/plain', 'Markdown'), ('pdf', 'application/pdf', 'PDF'))*

path suffix, media type, label

* **Type:**
  the alternate representations of a share

### annals.share_page.DESCRIPTION_CHARS *= 280*

the length of the page’s `<meta name="description">`

### annals.share_page.SHARE_FILE *= 'share'*

the share’s whole text, at `<link>/<SHARE_FILE>.<ext>`

### annals.share_page.STATIC_FILE_MAX_BYTES *= 2000000*

a document’s file larger than this is linked, not put in the page

### annals.share_page.STATIC_MAX_BYTES *= 1500000*

the page’s text stops growing past this many bytes of html; later documents are links

### annals.share_page.STATIC_MAX_FILES *= 40*

the text files rendered into one page at most; the rest are links (a page is made on
every request, and anyone holding the link may make one)

### annals.share_page.STATIC_MAX_IMAGES *= 60*

images shown for a document without text (a gallery folder); the rest are listed

### annals.share_page.STATIC_MAX_PLAYERS *= 20*

audio and video players in one document’s page; the rest are listed

### *class* annals.share_page.ShareScope(link, shared_ids, root_id='', private_hosts=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a page of one share may show and link to.

`link` is the share’s address (root-relative is fine: a fetcher resolves it against
the page), `shared_ids` the documents it includes, `root_id` its group (`""` for
a document share), `private_hosts` the owner’s hosts, never linked to.

#### shared(annals_id)

The share’s page for an annals id it includes, else `None`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.share_page.VIEWER_PARAM *= 'viewer'*

`<link>/?viewer` opens the script viewer (galleries, players, downloads) instead

### annals.share_page.alternate_links(link, doc_id=None)

The `<link rel="alternate">` tags of [`alternate_urls()`](#annals.share_page.alternate_urls), for the `<head>`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.share_page.alternate_urls(link, doc_id=None)

`(url, media type, label)` of the share (or of one document of it) as files.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### annals.share_page.description_of(content, , skip='', n=280)

The first `n` characters of the page’s words (the title and alternates line left out).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.share_page.designed_page(meta, files)

The html file a document’s page *is*, when it is one, else `None`.

Such a document is served as itself at its link (filtered and sandboxed, as `/raw`
serves it): a person sees it as designed, and a fetcher, even one that runs script,
reads it at the top level rather than inside a frame it does not open.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.share_page.page_body(docs, , title, read_text, scope, doc_id=None, viewer_url=None, max_bytes=None)

The page’s content and its description: `(html, plain text of ~280 chars)`.

`docs` are the `(meta, files)` pairs to show, in order (one, for a document’s
page); `read_text(doc_id, rel)` reads a file as it is on disk (the shared-text
filters are applied here). `doc_id` names the document a `/d/<id>` page is for,
which picks the alternates the page offers; `viewer_url` is where the script viewer
opens it. `max_bytes`: [`STATIC_MAX_BYTES`](#annals.share_page.STATIC_MAX_BYTES).

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.share_page.with_base(page, href)

`page` with `<base href>` as its first element, so its relative references
(images, styles, its other pages) resolve where the share serves its files.

The page’s own `<base>` and referrer `<meta>` go: either would send its requests,
or the link, elsewhere. The tag goes right after the doctype, where the parser puts it
in the head whatever comes later (a `<head>` written in a comment, say).

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)
