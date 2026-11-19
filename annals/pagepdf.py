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
   cannot print (no Chromium, a page that will not load in time), the button calls the
   browser's own print dialog instead, so it is never missing.

What this adds is one block wrapped in ``<!--annals-pdf-->`` markers (pure ASCII, so it
suits a page in any charset), so publishing a page that already went through here (a new
version through ``--replace``) swaps the old button for a new one and prints the new page
again. The page's bytes are otherwise kept as they were, whatever their encoding.
"""

import html as _html
import logging
import os
import re
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)

#: ``path of a staged html page -> PDF bytes``; raises when it cannot print
PdfRenderer = Callable[[Path], bytes]
#: the longest a page may take to print, in seconds, before the button prints instead
DFLT_PRINT_TIMEOUT_S = 60

_OPEN, _CLOSE = "<!--annals-pdf-->", "<!--/annals-pdf-->"
_INJECTED_RE = re.compile(re.escape(_OPEN) + r".*?" + re.escape(_CLOSE), re.S)
#: what holds text that only looks like markup: a tag found there is not a tag
_OPAQUE_RE = re.compile(
    r"<(script|style|textarea|template)\b.*?</\1\s*>|<!--.*?-->", re.I | re.S
)
#: the rest of a tag after its name; quoted attribute values may hold ``>``
_TAG_REST = r"""(?:[^>"']|"[^"]*"|'[^']*')*>"""
_BODY_RE = re.compile(r"<body\b" + _TAG_REST, re.I)
_HEAD_END_RE = re.compile(r"</head\s*>", re.I)
_HTML_RE = re.compile(r"<html\b" + _TAG_REST, re.I)
_DOCTYPE_RE = re.compile(r"<!doctype\b[^>]*>", re.I)
_LINK_RE = re.compile(r"<link\b" + _TAG_REST, re.I)
_OPT_OUT_RE = re.compile(
    r"<(?:html|body)\b[^>]*\bdata-annals-pdf\s*=\s*[\"']?off\b", re.I
)
_OWN_BUTTON_RE = re.compile(r"<[a-z][^>]*\sdata-annals-pdf(?=[\s=/>])", re.I)
_ATTR_RE = re.compile(r"""([a-zA-Z-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
_LAZY_RE = re.compile(r"""\sloading\s*=\s*["']?lazy["']?""", re.I)
_INJECTED_HREF_RE = re.compile(r'<a id="annals-pdf"[^>]*\shref="([^"]*)"')

_STYLE = (
    "#annals-pdf{position:fixed;top:10px;right:10px;z-index:2147483000;"
    "font:600 13px/1 system-ui,sans-serif;padding:7px 11px;border-radius:7px;"
    "background:#1f2937;color:#fff;text-decoration:none;border:0;cursor:pointer;"
    "opacity:.85;box-shadow:0 1px 4px rgba(0,0,0,.25)}"
    "#annals-pdf:hover,#annals-pdf:focus{opacity:1}"
    "@media print{#annals-pdf{display:none!important}}"
)
LABEL = "&#8595; PDF"


def _attrs(tag: str) -> dict[str, str]:
    return {
        m.group(1).lower(): next(g for g in m.groups()[1:] if g is not None)
        for m in _ATTR_RE.finditer(tag)
    }


def _masked(page: str) -> str:
    """``page`` with scripts, styles and comments blanked, every offset kept."""
    return _OPAQUE_RE.sub(lambda m: " " * len(m.group(0)), page)


def strip_button(page: str) -> str:
    """``page`` without what :func:`add_button` put in it.

    >>> strip_button(add_button("<body><p>x</p></body>", "x.pdf"))
    '<body><p>x</p></body>'
    """
    return _INJECTED_RE.sub("", page)


def button_href(page: str) -> str | None:
    """Where the button annals put in ``page`` points (``None``: none, or a print button).

    >>> button_href(add_button("<p>x</p>", "x.pdf"))
    'x.pdf'
    """
    m = _INJECTED_HREF_RE.search(page)
    return _html.unescape(m.group(1)) if m else None


def declared_pdf(page: str) -> str | None:
    """The href of the page's own ``<link rel="alternate" type="application/pdf">``.

    A link annals added itself does not count: that is not the page declaring one.

    >>> declared_pdf('<link rel="alternate" type="application/pdf" href="guide.pdf">')
    'guide.pdf'
    >>> declared_pdf('<link rel="stylesheet" href="a.css">') is None
    True
    """
    for m in _LINK_RE.finditer(_masked(strip_button(page))):
        a = _attrs(m.group(0))
        rels = a.get("rel", "").lower().split()
        if "alternate" in rels and a.get("type", "").lower() == "application/pdf":
            return _html.unescape(a["href"]) if a.get("href") else None
    return None


def wants_button(page: str) -> bool:
    """False when the page opts out, or already has a PDF button of its own.

    >>> wants_button("<p>plain</p>")
    True
    >>> wants_button('<body data-annals-pdf="off"><p>x</p></body>')
    False
    >>> wants_button('<a href="g.pdf" data-annals-pdf>PDF</a>')
    False
    >>> wants_button('<script>"<a data-annals-pdf>"</script><p data-annals-pdf-note=1>')
    True
    """
    page = _masked(strip_button(page))
    return not (_OPT_OUT_RE.search(page) or _OWN_BUTTON_RE.search(page))


def _insertion_point(page: str) -> int:
    """Right after ``<body>``; else after ``</head>``, ``<html>`` or the doctype; else 0."""
    masked = _masked(page)
    for pattern in (_BODY_RE, _HEAD_END_RE, _HTML_RE, _DOCTYPE_RE):
        if m := pattern.search(masked):
            return m.end()
    return 0


def add_button(page: str, href: str | None) -> str:
    """``page`` with a Download PDF link to ``href`` (or a print button when ``None``).

    One block goes right after ``<body>`` (or where the body would start): a ``<link
    rel="alternate">`` declaring the PDF, so readers and agents find it, its style, and
    the button. Any button added earlier is replaced. ``href`` is used as given (quote a
    file name first: :func:`attach_pdf` does).

    >>> page = "<!doctype html><html><head></head><body><p>x</p></body></html>"
    >>> out = add_button(page, "x.pdf")
    >>> 'href="x.pdf"' in out and 'type="application/pdf"' in out
    True
    >>> out.startswith("<!doctype html>")
    True
    >>> "window.print()" in add_button("<p>x</p>", None)
    True
    """
    page = strip_button(page)
    style = f"<style>{_STYLE}</style>"
    if href:
        h = _html.escape(href, quote=True)
        parts = (
            f'<link rel="alternate" type="application/pdf" href="{h}">',
            style,
            f'<a id="annals-pdf" data-annals-pdf="auto" href="{h}" download '
            f'target="_blank" rel="noopener" title="Download this page as a PDF">{LABEL}</a>',
        )
    else:
        parts = (
            style,
            '<button id="annals-pdf" data-annals-pdf="print" type="button" '
            'onclick="window.print()" title="Print this page, or save it as a PDF">'
            f"{LABEL}</button>",
        )
    at = _insertion_point(page)
    return page[:at] + _OPEN + "".join(parts) + _CLOSE + page[at:]


#: run in a child process, so a hung page can be killed and an asyncio caller is no obstacle
_PRINT_SCRIPT = (
    "import sys\n"
    "from pdfdol.chromium import html_to_pdf_w_chromium\n"
    "html_to_pdf_w_chromium(sys.argv[1], sys.argv[2], media='print',"
    " on_overlap='ignore', wait_until='load')\n"
)


def print_with_chromium(page: Path, *, timeout: float = DFLT_PRINT_TIMEOUT_S) -> bytes:
    """Print an html file to PDF with headless Chromium (pdfdol), with its print css.

    Needs the ``pdf`` extra and ``playwright install chromium``. It runs in a child
    process, killed (with its browser) after ``timeout`` seconds. Images marked
    ``loading="lazy"`` would print blank, so the page is printed from a copy without
    that attribute, beside it so its relative files still load.
    """
    from annals.requirements import check_requirements

    check_requirements("pdfdol", "playwright", what="Printing an html page to PDF")
    copy = page.with_name(f".annals-print-{page.name}")
    out = copy.with_suffix(".pdf")
    raw = page.read_bytes().decode("utf-8", "surrogateescape")
    copy.write_bytes(_LAZY_RE.sub("", raw).encode("utf-8", "surrogateescape"))
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", _PRINT_SCRIPT, str(copy), str(out)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,  # its own process group: the browser dies with it
        )
        try:
            _, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise TimeoutError(f"printing took more than {timeout:g}s") from None
        if proc.returncode or not out.is_file():
            lines = err.decode(errors="replace").strip().splitlines()
            raise RuntimeError(lines[-1] if lines else f"exit {proc.returncode}")
        return out.read_bytes()
    finally:
        copy.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


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
) -> tuple[list[str], str | None]:
    """Give the staged html page ``root/main`` its PDF button (and its PDF).

    Returns ``(files, pdf)``: ``files`` (relative to ``root``) gains ``<stem>.pdf`` when it
    is printed here, and ``pdf`` is where the page's PDF is (a file of the document, or
    the url the page declared), ``None`` when there is none. ``pdf_renderer`` defaults to
    :data:`DFLT_PDF_RENDERER`; ``None`` never prints: the button links to a PDF the
    document or the page already has, else opens the print dialog. A renderer that fails
    is logged and treated the same way; publishing never fails for want of a PDF.
    """
    if pdf_renderer == DFLT:
        pdf_renderer = DFLT_PDF_RENDERER
    path = root / main
    page = path.read_bytes().decode("utf-8", "surrogateescape")
    if not wants_button(page):
        return files, None
    pdf_rel = str(Path(main).with_suffix(".pdf"))
    pdf = href = declared_pdf(page)
    if pdf is None:
        pdf = next((f for f in files if f.lower() == pdf_rel.lower()), None)
    if pdf is None and pdf_renderer is not None:
        clean = strip_button(page)
        if clean != page:  # print the page itself, not its old button
            path.write_bytes(clean.encode("utf-8", "surrogateescape"))
        try:
            (root / pdf_rel).write_bytes(pdf_renderer(path))
            files, pdf = sorted({*files, pdf_rel}), pdf_rel
        except Exception as e:  # noqa: BLE001 - any failure falls back to print
            log.warning("annals: no PDF for %s (%s); the button prints instead", main, e)
    if href is None and pdf is not None:
        href = quote(Path(pdf).name)
    path.write_bytes(add_button(page, href).encode("utf-8", "surrogateescape"))
    return files, pdf
