# annals.pagepdf

Every published html page carries its own Download PDF button, and the PDF beside it.

A page is often read without the annals page around it: opened full page, its raw url
mailed on, or shared. So at publish time the stored html itself gets a small “Download
PDF” link (hidden when printing), pointing at `<stem>.pdf` in the same document:

1. **The page opts out** (`data-annals-pdf="off"` on `<html>` or `<body>`, or
   `annals publish --no-pdf`): nothing is added.
2. **The page has its own button** (any element with `data-annals-pdf`): nothing is
   added; it already says where its PDF is.
3. **The page declares its PDF** (`<link rel="alternate" type="application/pdf"
   href="...">`): the button points there, and nothing is printed.
4. **The document already holds** `<stem>.pdf` beside the page: the button points at it.
5. **Otherwise the page is printed** to `<stem>.pdf` by `pdf_renderer` (default
   [`print_with_chromium()`](#annals.pagepdf.print_with_chromium), pdfdol’s headless Chromium, in the `pdf` extra). When it
   > cannot print (no Chromium, a page that will not load in time), the button calls the
   > browser’s own print dialog instead, so it is never missing.

What this adds is one block wrapped in `<!--annals-pdf-->` markers (pure ASCII, so it
suits a page in any charset), so publishing a page that already went through here (a new
version through `--replace`) swaps the old button for a new one and prints the new page
again. The page’s bytes are otherwise kept as they were, whatever their encoding.

### Module Attributes

| [`PdfRenderer`](#annals.pagepdf.PdfRenderer)                            | `path of a staged html page -> PDF bytes`; raises when it cannot print                                                                                          |
|-----------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_PRINT_TIMEOUT_S`](#annals.pagepdf.DFLT_PRINT_TIMEOUT_S)                   | the longest a page may take to print, in seconds, before the button prints instead                                                                              |
| [`DFLT_PDF_RENDERER`](#annals.pagepdf.DFLT_PDF_RENDERER)(page, \*[, timeout]) | what [`attach_pdf()`](#annals.pagepdf.attach_pdf) prints with when not told; read at call time, so a test or an embedding app can swap it once |
| [`DFLT`](#annals.pagepdf.DFLT)                                   | "the default renderer", told apart from `None` (never print)                                                                                                    |

### Functions

| [`DFLT_PDF_RENDERER`](#annals.pagepdf.DFLT_PDF_RENDERER)(page, \*[, timeout])            | what [`attach_pdf()`](#annals.pagepdf.attach_pdf) prints with when not told; read at call time, so a test or an embedding app can swap it once   |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`add_button`](#annals.pagepdf.add_button)(page, href)                            | `page` with a Download PDF link to `href` (or a print button when `None`).                                                                                        |
| [`attach_pdf`](#annals.pagepdf.attach_pdf)(root, main, files, \*[, pdf_renderer]) | Give the staged html page `root/main` its PDF button (and its PDF).                                                                                               |
| [`button_href`](#annals.pagepdf.button_href)(page)                                 | Where the button annals put in `page` points (`None`: none, or a print button).                                                                                   |
| [`declared_pdf`](#annals.pagepdf.declared_pdf)(page)                                | The href of the page's own `<link rel="alternate" type="application/pdf">`.                                                                                       |
| [`print_with_chromium`](#annals.pagepdf.print_with_chromium)(page, \*[, timeout])          | Print an html file to PDF with headless Chromium (pdfdol), with its print css.                                                                                    |
| [`strip_button`](#annals.pagepdf.strip_button)(page)                                | `page` without what [`add_button()`](#annals.pagepdf.add_button) put in it.                                                                      |
| [`wants_button`](#annals.pagepdf.wants_button)(page)                                | False when the page opts out, or already has a PDF button of its own.                                                                                             |

### annals.pagepdf.DFLT *= 'default'*

“the default renderer”, told apart from `None` (never print)

### annals.pagepdf.DFLT_PDF_RENDERER(page, , timeout=60)

what [`attach_pdf()`](#annals.pagepdf.attach_pdf) prints with when not told; read at call time, so a test or an
embedding app can swap it once

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### annals.pagepdf.DFLT_PRINT_TIMEOUT_S *= 60*

the longest a page may take to print, in seconds, before the button prints instead

### annals.pagepdf.PdfRenderer

`path of a staged html page -> PDF bytes`; raises when it cannot print

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)], [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]

### annals.pagepdf.add_button(page, href)

`page` with a Download PDF link to `href` (or a print button when `None`).

One block goes right after `<body>` (or where the body would start): a `<link
rel="alternate">` declaring the PDF, so readers and agents find it, its style, and
the button. Any button added earlier is replaced. `href` is used as given (quote a
file name first: [`attach_pdf()`](#annals.pagepdf.attach_pdf) does).

```pycon
>>> page = "<!doctype html><html><head></head><body><p>x</p></body></html>"
>>> out = add_button(page, "x.pdf")
>>> 'href="x.pdf"' in out and 'type="application/pdf"' in out
True
>>> out.startswith("<!doctype html>")
True
>>> "window.print()" in add_button("<p>x</p>", None)
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.pagepdf.attach_pdf(root, main, files, , pdf_renderer='default')

Give the staged html page `root/main` its PDF button (and its PDF).

Returns `(files, pdf)`: `files` (relative to `root`) gains `<stem>.pdf` when it
is printed here, and `pdf` is where the page’s PDF is (a file of the document, or
the url the page declared), `None` when there is none. `pdf_renderer` defaults to
[`DFLT_PDF_RENDERER`](#annals.pagepdf.DFLT_PDF_RENDERER); `None` never prints: the button links to a PDF the
document or the page already has, else opens the print dialog. A renderer that fails
is logged and treated the same way; publishing never fails for want of a PDF.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### annals.pagepdf.button_href(page)

Where the button annals put in `page` points (`None`: none, or a print button).

```pycon
>>> button_href(add_button("<p>x</p>", "x.pdf"))
'x.pdf'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.pagepdf.declared_pdf(page)

The href of the page’s own `<link rel="alternate" type="application/pdf">`.

A link annals added itself does not count: that is not the page declaring one.

```pycon
>>> declared_pdf('<link rel="alternate" type="application/pdf" href="guide.pdf">')
'guide.pdf'
>>> declared_pdf('<link rel="stylesheet" href="a.css">') is None
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.pagepdf.print_with_chromium(page, , timeout=60)

Print an html file to PDF with headless Chromium (pdfdol), with its print css.

Needs the `pdf` extra and `playwright install chromium`. It runs in a child
process, killed (with its browser) after `timeout` seconds. Images marked
`loading="lazy"` would print blank, so the page is printed from a copy without
that attribute, beside it so its relative files still load.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### annals.pagepdf.strip_button(page)

`page` without what [`add_button()`](#annals.pagepdf.add_button) put in it.

```pycon
>>> strip_button(add_button("<body><p>x</p></body>", "x.pdf"))
'<body><p>x</p></body>'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.pagepdf.wants_button(page)

False when the page opts out, or already has a PDF button of its own.

```pycon
>>> wants_button("<p>plain</p>")
True
>>> wants_button('<body data-annals-pdf="off"><p>x</p></body>')
False
>>> wants_button('<a href="g.pdf" data-annals-pdf>PDF</a>')
False
>>> wants_button('<script>"<a data-annals-pdf>"</script><p data-annals-pdf-note=1>')
True
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
