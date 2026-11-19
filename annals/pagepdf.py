"""Every published html page carries its own Download PDF button, and the PDF beside it.

A page is often read without the annals page around it: opened full page, its raw url
mailed on, or shared. So at publish time the stored html itself gets a small "Download
PDF" link (hidden when printing), pointing at ``<stem>.pdf`` in the same document:

1. **The page opts out** (``data-annals-pdf="off"`` on ``<html>`` or ``<body>``, or
   ``annals publish --no-pdf``): nothing is added.
2. **The page has its own button** (any element with ``data-annals-pdf``): nothing is
   added; it already says where its PDF is.
3. **The page declares its PDF** (``<link rel="alternate" type="application/pdf"
   href="...">``): the button points there, and nothing is printed.
4. **The document already holds** ``<stem>.pdf`` beside the page: the button points at it.
5. **Otherwise the page is printed** to ``<stem>.pdf`` by ``pdf_renderer`` (default
   :func:`print_with_chromium`, pdfdol's headless Chromium, in the ``pdf`` extra). When it
   cannot print (no Chromium, a page that will not load), the button calls the browser's
   own print dialog instead, so it is never missing.

What this adds is wrapped in ``<!--annals-pdf-->`` markers, so publishing a page that
already went through here (a new version through ``--replace``) swaps the old button for
a new one and prints the new page again.
"""

import html as _html
import logging
import re
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

#: ``path of a staged html page -> PDF bytes``; raises when it cannot print
PdfRenderer = Callable[[Path], bytes]

_OPEN, _CLOSE = "<!--annals-pdf-->", "<!--/annals-pdf-->"
_INJECTED_RE = re.compile(re.escape(_OPEN) + r".*?" + re.escape(_CLOSE), re.S)
_OPT_OUT_RE = re.compile(
    r"<(?:html|body)\b[^>]*\bdata-annals-pdf\s*=\s*[\"']?off\b", re.I
)
_OWN_BUTTON_RE = re.compile(r"<[a-z][^>]*\sdata-annals-pdf\b", re.I)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_ATTR_RE = re.compile(
    r"""([a-zA-Z-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))"""
)
_LAZY_RE = re.compile(r"""\sloading\s*=\s*["']?lazy["']?""", re.I)

_STYLE = (
    "#annals-pdf{position:fixed;top:10px;right:10px;z-index:2147483000;"
    "font:600 13px/1 system-ui,sans-serif;padding:7px 11px;border-radius:7px;"
    "background:#1f2937;color:#fff;text-decoration:none;border:0;cursor:pointer;"
    "opacity:.85;box-shadow:0 1px 4px rgba(0,0,0,.25)}"
    "#annals-pdf:hover,#annals-pdf:focus{opacity:1}"
    "@media print{#annals-pdf{display:none!important}}"
)
LABEL = "↓ PDF"


def _attrs(tag: str) -> dict[str, str]:
    return {
        m.group(1).lower(): next(g for g in m.groups()[1:] if g is not None)
        for m in _ATTR_RE.finditer(tag)
    }


def strip_button(page: str) -> str:
    """``page`` without what :func:`add_button` put in it.

    >>> strip_button(add_button("<body><p>x</p></body>", "x.pdf"))
    '<body><p>x</p></body>'
    """
    return _INJECTED_RE.sub("", page)


def declared_pdf(page: str) -> str | None:
    """The href of the page's own ``<link rel="alternate" type="application/pdf">``.

    >>> declared_pdf('<link rel="alternate" type="application/pdf" href="guide.pdf">')
    'guide.pdf'
    >>> declared_pdf('<link rel="stylesheet" href="a.css">') is None
    True
    """
    for m in _LINK_RE.finditer(strip_button(page)):
        a = _attrs(m.group(0))
        rels = a.get("rel", "").lower().split()
        if "alternate" in rels and a.get("type", "").lower() == "application/pdf":
            return a.get("href") or None
    return None


def wants_button(page: str) -> bool:
    """False when the page opts out, or already has a PDF button of its own.

    >>> wants_button("<p>plain</p>")
    True
    >>> wants_button('<body data-annals-pdf="off"><p>x</p></body>')
    False
    >>> wants_button('<a href="g.pdf" data-annals-pdf>PDF</a>')
    False
    """
    page = strip_button(page)
    return not (_OPT_OUT_RE.search(page) or _OWN_BUTTON_RE.search(page))


def add_button(page: str, href: str | None) -> str:
    """``page`` with a Download PDF link to ``href`` (or a print button when ``None``).

    The link goes right after ``<body>`` (or at the start), with a ``<link
    rel="alternate">`` declaring the PDF in ``<head>`` when there is one, so readers and
    agents find it too. Any button added earlier is replaced.

    >>> out = add_button("<html><head></head><body><p>x</p></body></html>", "x.pdf")
    >>> 'href="x.pdf"' in out and 'type="application/pdf"' in out
    True
    >>> "window.print()" in add_button("<p>x</p>", None)
    True
    """
    page = strip_button(page)
    style = f"<style>{_STYLE}</style>"
    if href:
        h = _html.escape(href, quote=True)
        button = (
            f'<a id="annals-pdf" data-annals-pdf="auto" href="{h}" download '
            f'target="_blank" rel="noopener" title="Download this page as a PDF">{LABEL}</a>'
        )
        head_link = f'{_OPEN}<link rel="alternate" type="application/pdf" href="{h}">{_CLOSE}'
    else:
        button = (
            '<button id="annals-pdf" data-annals-pdf="print" type="button" '
            'onclick="window.print()" title="Print this page, or save it as a PDF">'
            f"{LABEL}</button>"
        )
        head_link = ""
    block = f"{_OPEN}{style}{button}{_CLOSE}"
    if head_link and (m := re.search(r"</head\s*>", page, re.I)):
        page = page[: m.start()] + head_link + page[m.start() :]
    m = re.search(r"<body\b[^>]*>", page, re.I)
    at = m.end() if m else 0
    return page[:at] + block + page[at:]


def print_with_chromium(page: Path) -> bytes:
    """Print an html file to PDF with headless Chromium (pdfdol), with its print css.

    Needs ``pip install 'annals[pdf]'`` and ``playwright install chromium``. Images marked
    ``loading="lazy"`` would print blank, so the page is printed from a copy, beside it so
    its relative files still load, without that attribute.
    """
    from annals.requirements import check_requirements

    check_requirements("pdfdol", "playwright", what="Printing an html page to PDF")
    from pdfdol.chromium import html_to_pdf_w_chromium

    copy = page.with_name(f".annals-print-{page.name}")
    copy.write_text(
        _LAZY_RE.sub("", page.read_text(encoding="utf-8", errors="replace")),
        encoding="utf-8",
    )
    try:
        return html_to_pdf_w_chromium(str(copy), media="print", on_overlap="ignore")
    finally:
        copy.unlink(missing_ok=True)


#: what :func:`attach_pdf` prints with when not told; read at call time, so a test or an
#: embedding app can swap it once
DFLT_PDF_RENDERER: PdfRenderer | None = print_with_chromium
#: "the default renderer", told apart from ``None`` (never print)
DFLT = "default"


def attach_pdf(
    root: Path,
    main: str,
    files: list[str],
    *,
    pdf_renderer: PdfRenderer | None | str = DFLT,
) -> list[str]:
    """Give the staged html page ``root/main`` its PDF button (and its PDF); return ``files``.

    ``pdf_renderer`` defaults to :data:`DFLT_PDF_RENDERER`. ``files`` (relative to ``root``) gains ``<stem>.pdf`` when it is printed here.
    ``pdf_renderer=None`` never prints: the button links to a PDF the document or the
    page already has, else opens the print dialog. A renderer that fails is logged and
    treated the same way; publishing never fails for want of a PDF.
    """
    if pdf_renderer == DFLT:
        pdf_renderer = DFLT_PDF_RENDERER
    path = root / main
    page = path.read_text(encoding="utf-8", errors="replace")
    if not wants_button(page):
        return files
    pdf_rel = str(Path(main).with_suffix(".pdf"))
    href = declared_pdf(page)
    if href is None and pdf_rel in files:
        href = Path(pdf_rel).name
    if href is None and pdf_renderer is not None:
        clean = strip_button(page)
        if clean != page:  # print the page itself, not its old button
            path.write_text(clean, encoding="utf-8")
        try:
            (root / pdf_rel).write_bytes(pdf_renderer(path))
            files = sorted({*files, pdf_rel})
            href = Path(pdf_rel).name
        except Exception as e:  # noqa: BLE001 - any failure falls back to print
            log.warning("annals: no PDF for %s (%s); the button prints instead", main, e)
    path.write_text(add_button(page, href), encoding="utf-8")
    return files
