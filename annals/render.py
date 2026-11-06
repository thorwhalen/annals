"""Render markdown (and other page-like files) to html and PDF, with their images inside.

No web framework in here, so the CLI can use it as the server does. The PDF is made by
WeasyPrint from markdown-it's HTML (raw html in the markdown is shown as text, never
interpreted). Images are embedded; audio, video, other PDFs and files become a visible link
to the resource, so the reader can open or play it. WeasyPrint is imported on first use; a
missing one is a :class:`annals.requirements.MissingDependency` with the install hint.

Nothing is fetched from the network: an image outside the document is a link, never loaded.
Everything WeasyPrint is allowed to load is a placeholder url (``annals-file:N``) for bytes
this module already holds (:class:`Embedded`).
"""

from __future__ import annotations

import html
import io
import posixpath
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import unquote, urlsplit

from annals.requirements import import_lazily
from annals.share import dir_of
from annals.store import kind_of

#: longest side of an embedded image; a 6000 px render is shrunk, a phone screenshot is not
PDF_IMAGE_MAX_PX = 1800
#: an image larger than this on disk is linked, not embedded
PDF_IMAGE_MAX_BYTES = 25_000_000
#: an image with more pixels than this is not decoded to be shrunk (a small box would run out of memory)
PDF_IMAGE_MAX_PIXELS = 40_000_000
#: all embedded images of one PDF together
PDF_IMAGES_TOTAL_BYTES = 80_000_000
#: markdown larger than this is not made into a PDF (rendering cost grows faster than size)
PDF_MAX_TEXT_BYTES = 400_000
_MEDIA_LABELS = {"video": "Video", "audio": "Audio", "pdf": "PDF", "html": "Page"}

PDF_CSS = """
@page { size: A4; margin: 20mm 18mm 22mm;
  @bottom-left { content: string(doctitle); font: 8pt sans-serif; color: #666; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 8pt sans-serif; color: #666; } }
html { font: 10.5pt/1.5 "DejaVu Serif", "Noto Serif", serif; color: #111; }
h1.doc-title { string-set: doctitle content(); font: 700 21pt/1.2 "DejaVu Sans", sans-serif; margin: 0 0 4pt; }
p.doc-meta { color: #666; font: 9pt "DejaVu Sans", sans-serif; margin: 0 0 16pt; }
h1, h2, h3, h4 { font-family: "DejaVu Sans", sans-serif; line-height: 1.25; break-after: avoid; }
h1 { font-size: 17pt; } h2 { font-size: 14pt; } h3 { font-size: 12pt; } h4 { font-size: 10.5pt; }
a { color: #1a5fb4; text-decoration: none; overflow-wrap: anywhere; }
img { max-width: 100%; max-height: 220mm; height: auto; }
figure { margin: 10pt 0; break-inside: avoid; }
figcaption { color: #666; font: 8.5pt "DejaVu Sans", sans-serif; }
pre, code { font: 8.8pt/1.4 "DejaVu Sans Mono", monospace; }
pre { background: #f3f3f3; padding: 8pt; border-radius: 4pt; white-space: pre-wrap; overflow-wrap: anywhere; }
code { background: #f3f3f3; padding: 0 2pt; }
pre code { background: none; padding: 0; }
blockquote { margin: 8pt 0; padding-left: 10pt; border-left: 2.5pt solid #ccc; color: #444; }
table { border-collapse: collapse; margin: 8pt 0; font-size: 9.5pt; }
th, td { border: .5pt solid #bbb; padding: 3pt 6pt; text-align: left; vertical-align: top; }
th { background: #f3f3f3; }
.media-link { display: block; margin: 8pt 0; padding: 6pt 9pt; border: .5pt solid #bbb; border-radius: 4pt;
  font: 9.5pt "DejaVu Sans", sans-serif; overflow-wrap: anywhere; break-inside: avoid; }
.more h2 { font-size: 12pt; }
"""


def resolve_ref(href: str, *, rel: str, files: Sequence[str]) -> str | None:
    """The document file a relative ``href`` of the markdown file ``rel`` names, or ``None``.

    Absolute urls, paths that leave the document and files not in ``files`` are ``None``.
    """
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
        return None
    target = posixpath.normpath(posixpath.join(dir_of(rel), unquote(parts.path)))
    return target if target in set(files) else None


def _shrunk(data: bytes, rel: str) -> tuple[bytes, str]:
    """``data`` as an image no wider than ``PDF_IMAGE_MAX_PX`` (Pillow, when installed)."""
    try:
        from PIL import Image
    except ImportError:
        return data, kind_of_mime(rel)
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > PDF_IMAGE_MAX_PIXELS:
                return data, Image.MIME.get(
                    im.format, kind_of_mime(rel)
                )  # not decoded here
            if max(im.size) <= PDF_IMAGE_MAX_PX or im.format == "GIF":
                return data, Image.MIME.get(im.format, kind_of_mime(rel))
            im.thumbnail((PDF_IMAGE_MAX_PX, PDF_IMAGE_MAX_PX))
            out = io.BytesIO()
            keep_alpha = im.mode in ("RGBA", "LA", "P")
            im.convert("RGBA" if keep_alpha else "RGB").save(
                out,
                "PNG" if keep_alpha else "JPEG",
                **({} if keep_alpha else {"quality": 85}),
            )
            return out.getvalue(), "image/png" if keep_alpha else "image/jpeg"
    except Exception:  # a file Pillow cannot read is left to WeasyPrint, which may
        return data, kind_of_mime(rel)


def kind_of_mime(rel: str) -> str:
    import mimetypes

    return mimetypes.guess_type(rel)[0] or "application/octet-stream"


class Embedder:
    """The bytes a page may show, under placeholder urls, within a size budget.

    WeasyPrint is only ever allowed to load these (:func:`html_to_pdf`), and an html output
    gets them as ``data:`` urls (:func:`inline_embedded`), so no render reaches the network
    or the disk on its own.
    """

    def __init__(self, *, max_total: int = PDF_IMAGES_TOTAL_BYTES):
        self.items: dict[
            str, tuple[bytes, str]
        ] = {}  # placeholder url -> (bytes, mime)
        self.max_total = max_total
        self.used = 0

    def add_image(self, read: Callable[[], bytes], rel: str, size: int) -> str | None:
        """A placeholder url for an image (shrunk), or ``None`` when it is too big to embed."""
        if size > PDF_IMAGE_MAX_BYTES or self.used + size > self.max_total:
            return None
        try:
            data, mime = _shrunk(read(), rel)
        except OSError:
            return None
        self.used += size
        key = f"annals-file:{len(self.items)}"
        self.items[key] = (data, mime)
        return key


def markdown_to_html(
    text: str,
    *,
    rel: str,
    files: Sequence[str],
    open_file: Callable[[str], Path],
    file_url: Callable[[str], str | None],
    embedder: Embedder | None = None,
    read_bytes: Callable[[str], bytes] | None = None,
    list_unreferenced: bool = True,
) -> tuple[str, Embedder]:
    """The html body of the markdown ``text`` (the file ``rel`` of a document) and its images.

    Images the document holds are embedded (placeholder urls in the returned
    :class:`Embedder`); other files become links, shown as media rows; external images are
    never fetched. Raw html in the markdown is text, not markup. ``read_bytes(rel)`` reads
    an image the way the caller allows (a share filters svg text); ``list_unreferenced=False``
    leaves out the "More in this document" rows (when the document's other files are
    sections of a combined output of their own).
    """
    markdown_it = import_lazily("markdown_it", what="Rendering markdown")
    md = markdown_it.MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(
        ["table", "strikethrough"]
    )
    embedder = embedder or Embedder()
    allowed = list(files)
    referenced: set[str] = set()  # every file the text names
    linked: set[str] = set()  # the ones named by a link, not shown inline

    def image_src(target: str) -> str | None:
        """A placeholder url for an embeddable image file, or ``None`` (then it is linked)."""
        if kind_of(target) != "image":
            return None
        try:
            path = open_file(target)
            size = path.stat().st_size
        except (OSError, KeyError, LookupError):
            return None
        except Exception:  # the caller's opener may raise its own "not found" (a 404)
            return None
        return embedder.add_image(
            (lambda: read_bytes(target)) if read_bytes else path.read_bytes,
            target,
            size,
        )

    tokens = md.parse(text)
    for tok in tokens:
        for child in tok.children or []:
            if child.type == "image":
                src = child.attrGet("src") or ""
                target = resolve_ref(src, rel=rel, files=allowed)
                if target:
                    referenced.add(target)
                    placeholder = image_src(target)
                    if placeholder:
                        child.attrSet("src", placeholder)
                        continue
                    child.attrSet("src", "annals-file:missing")
                    child.attrSet("data-linked", file_url(target) or "")
                    child.attrSet(
                        "data-kind",
                        _MEDIA_LABELS.get(
                            kind_of(target),
                            "Image" if kind_of(target) == "image" else "File",
                        ),
                    )
                else:  # external or unknown images are never fetched
                    child.attrSet("src", "annals-file:missing")
                    child.attrSet(
                        "data-linked",
                        src if urlsplit(src).scheme in ("http", "https") else "",
                    )
            elif child.type == "link_open":
                href = child.attrGet("href") or ""
                target = resolve_ref(href, rel=rel, files=allowed)
                if target:
                    referenced.add(target)
                    linked.add(target)
                    child.attrSet("href", file_url(target) or "")
                elif href.startswith("#"):
                    child.attrSet("href", "")
                elif urlsplit(href).scheme not in ("http", "https", "mailto"):
                    child.attrSet("href", "")

    renderer = md.renderer
    default_image = renderer.rules["image"]

    def render_image(tokens_, idx, options, env):
        tok = tokens_[idx]
        src = tok.attrGet("src") or ""
        alt = tok.content or ""
        if src == "annals-file:missing":
            href = tok.attrGet("data-linked") or ""
            label = html.escape(alt or posixpath.basename(href) or "image")
            inner = f'<a href="{html.escape(href)}">{label}</a>' if href else label
            kind = html.escape(tok.attrGet("data-kind") or "Image")
            return f'<span class="media-link">{kind}: {inner}</span>'
        return default_image(tokens_, idx, options, env)

    renderer.rules["image"] = render_image
    body = renderer.render(tokens, md.options, {})

    # the media a page names but does not embed, then the ones it never names at all
    rows: list[str] = []
    for target in allowed:
        kind = kind_of(target)
        if kind in _MEDIA_LABELS and target not in referenced and target != rel:
            rows.append(_media_row(kind, target, file_url(target)))
    media_in_body = "".join(
        _media_row(kind_of(t), t, file_url(t))
        for t in sorted(linked)
        if kind_of(t) in _MEDIA_LABELS or kind_of(t) == "file"
    )
    if media_in_body:
        body += f'<section class="more"><h2>Linked media</h2>{media_in_body}</section>'
    if rows and list_unreferenced:
        body += f'<section class="more"><h2>More in this document</h2>{"".join(rows)}</section>'
    return body, embedder


def page_html(title: str, body: str, *, created: str = "") -> str:
    """A standalone html page: the ``title`` as the document title, then ``body``."""
    meta = f'<p class="doc-meta">{html.escape(created[:10])}</p>' if created else ""
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
        f'</head><body><h1 class="doc-title">{html.escape(title)}</h1>{meta}{body}</body></html>'
    )


def inline_embedded(body: str, embedder: Embedder) -> str:
    """``body`` with each placeholder url replaced by a ``data:`` url of its bytes."""
    import base64

    # longest first: annals-file:1 is a prefix of annals-file:10
    for key in sorted(embedder.items, key=len, reverse=True):
        data, mime = embedder.items[key]
        uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        body = body.replace(f'src="{key}"', f'src="{uri}"')
    return body


def html_to_pdf(doc: str, embedder: Embedder) -> bytes:
    """A4 PDF of the html page ``doc``; the only things it may load are ``embedder``'s."""
    weasyprint = import_lazily("weasyprint", what="Making a PDF")

    def fetch(url: str, *args, **kwargs):
        if url in embedder.items:
            data, mime = embedder.items[url]
            return _fetched(data, mime)
        raise ValueError(f"not fetched: {url[:40]}")

    return weasyprint.HTML(
        string=doc, base_url="annals-doc:/", url_fetcher=fetch
    ).write_pdf(stylesheets=[weasyprint.CSS(string=PDF_CSS)])


def markdown_to_pdf(
    text: str,
    *,
    title: str,
    rel: str,
    files: Sequence[str],
    open_file: Callable[[str], Path],
    file_url: Callable[[str], str | None],
    created: str = "",
) -> bytes:
    """A titled A4 PDF of the markdown ``text`` with its images inside (see the module doc)."""
    body, embedder = markdown_to_html(
        text, rel=rel, files=files, open_file=open_file, file_url=file_url
    )
    return html_to_pdf(page_html(title, body, created=created), embedder)


def _fetched(data: bytes, mime: str):
    """A url fetcher's answer (WeasyPrint 68 wants a response object, older ones a dict)."""
    try:
        from weasyprint.urls import URLFetcherResponse
    except ImportError:
        return {"string": data, "mime_type": mime}
    return URLFetcherResponse("annals-file:", body=data, headers={"Content-Type": mime})


def _media_row(kind: str, rel: str, url: str | None) -> str:
    label = _MEDIA_LABELS.get(kind, "File")
    name = html.escape(posixpath.basename(rel))
    inner = f'<a href="{html.escape(url)}">{name}</a>' if url else name
    return f'<span class="media-link">{label}: {inner}</span>'
