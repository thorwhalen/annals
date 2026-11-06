# annals.render

Render markdown (and other page-like files) to html and PDF, with their images inside.

No web framework in here, so the CLI can use it as the server does. The PDF is made by
WeasyPrint from markdown-it’s HTML (raw html in the markdown is shown as text, never
interpreted). Images are embedded; audio, video, other PDFs and files become a visible link
to the resource, so the reader can open or play it. WeasyPrint is imported on first use; a
missing one is a [`annals.requirements.MissingDependency`](annals.requirements.html.md#annals.requirements.MissingDependency) with the install hint.

Nothing is fetched from the network: an image outside the document is a link, never loaded.
Everything WeasyPrint is allowed to load is a placeholder url (`annals-file:N`) for bytes
this module already holds (`Embedded`).

### Module Attributes

| [`PDF_IMAGE_MAX_PX`](#annals.render.PDF_IMAGE_MAX_PX)       | longest side of an embedded image; a 6000 px render is shrunk, a phone screenshot is not              |
|-------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| [`PDF_IMAGE_MAX_BYTES`](#annals.render.PDF_IMAGE_MAX_BYTES)    | an image larger than this on disk is linked, not embedded                                             |
| [`PDF_IMAGE_MAX_PIXELS`](#annals.render.PDF_IMAGE_MAX_PIXELS)   | an image with more pixels than this is not decoded to be shrunk (a small box would run out of memory) |
| [`PDF_IMAGES_TOTAL_BYTES`](#annals.render.PDF_IMAGES_TOTAL_BYTES) | all embedded images of one PDF together                                                               |
| [`PDF_MAX_TEXT_BYTES`](#annals.render.PDF_MAX_TEXT_BYTES)     | markdown larger than this is not made into a PDF (rendering cost grows faster than size)              |

### Functions

| [`html_to_pdf`](#annals.render.html_to_pdf)(doc, embedder)                         | A4 PDF of the html page `doc`; the only things it may load are `embedder`'s.        |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`inline_embedded`](#annals.render.inline_embedded)(body, embedder)                    | `body` with each placeholder url replaced by a `data:` url of its bytes.            |
| `kind_of_mime`(rel)                                                                                 |                                                                                     |
| [`markdown_to_html`](#annals.render.markdown_to_html)(text, \*, rel, files, ...[, ...]) | The html body of the markdown `text` (the file `rel` of a document) and its images. |
| [`markdown_to_pdf`](#annals.render.markdown_to_pdf)(text, \*, title, rel, files, ...)  | A titled A4 PDF of the markdown `text` with its images inside (see the module doc). |
| [`page_html`](#annals.render.page_html)(title, body, \*[, created])              | A standalone html page: the `title` as the document title, then `body`.             |
| [`resolve_ref`](#annals.render.resolve_ref)(href, \*, rel, files)                  | The document file a relative `href` of the markdown file `rel` names, or `None`.    |

### Classes

| [`Embedder`](#annals.render.Embedder)(\*[, max_total])   | The bytes a page may show, under placeholder urls, within a size budget.   |
|------------------------------------------------------------------------------|----------------------------------------------------------------------------|

### *class* annals.render.Embedder(, max_total=80000000)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The bytes a page may show, under placeholder urls, within a size budget.

WeasyPrint is only ever allowed to load these ([`html_to_pdf()`](#annals.render.html_to_pdf)), and an html output
gets them as `data:` urls ([`inline_embedded()`](#annals.render.inline_embedded)), so no render reaches the network
or the disk on its own.

#### add_image(read, rel, size)

A placeholder url for an image (shrunk), or `None` when it is too big to embed.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.render.PDF_IMAGES_TOTAL_BYTES *= 80000000*

all embedded images of one PDF together

### annals.render.PDF_IMAGE_MAX_BYTES *= 25000000*

an image larger than this on disk is linked, not embedded

### annals.render.PDF_IMAGE_MAX_PIXELS *= 40000000*

an image with more pixels than this is not decoded to be shrunk (a small box would run out of memory)

### annals.render.PDF_IMAGE_MAX_PX *= 1800*

longest side of an embedded image; a 6000 px render is shrunk, a phone screenshot is not

### annals.render.PDF_MAX_TEXT_BYTES *= 400000*

markdown larger than this is not made into a PDF (rendering cost grows faster than size)

### annals.render.html_to_pdf(doc, embedder)

A4 PDF of the html page `doc`; the only things it may load are `embedder`’s.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### annals.render.inline_embedded(body, embedder)

`body` with each placeholder url replaced by a `data:` url of its bytes.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.render.markdown_to_html(text, , rel, files, open_file, file_url, embedder=None, read_bytes=None, list_unreferenced=True)

The html body of the markdown `text` (the file `rel` of a document) and its images.

Images the document holds are embedded (placeholder urls in the returned
[`Embedder`](#annals.render.Embedder)); other files become links, shown as media rows; external images are
never fetched. Raw html in the markdown is text, not markup. `read_bytes(rel)` reads
an image the way the caller allows (a share filters svg text); `list_unreferenced=False`
leaves out the “More in this document” rows (when the document’s other files are
sections of a combined output of their own).

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Embedder`](#annals.render.Embedder)]

### annals.render.markdown_to_pdf(text, , title, rel, files, open_file, file_url, created='')

A titled A4 PDF of the markdown `text` with its images inside (see the module doc).

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### annals.render.page_html(title, body, , created='')

A standalone html page: the `title` as the document title, then `body`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.render.resolve_ref(href, , rel, files)

The document file a relative `href` of the markdown file `rel` names, or `None`.

Absolute urls, paths that leave the document and files not in `files` are `None`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
