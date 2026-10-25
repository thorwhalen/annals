"""Download a markdown document as a ``.md`` file or a titled PDF, from the server.

Both surfaces (the owner's API and the public share server) hand this module the text they
would show and the files they would serve, and nothing else: access is decided before the
call, here only what was passed in can reach the output. The text is the share's *filtered*
text for a recipient, and an image is read only when it is among the files given (a path
that climbs out, or an absolute URL, is never opened). So a download can show no more than
the page it came from.

The PDF is made by WeasyPrint from markdown-it's HTML (raw html in the markdown is shown as
text, never interpreted). Images are embedded in it; audio, video, other PDFs and files
become a visible link to the resource, so the reader can open or play it. WeasyPrint is
imported on first use, and a missing one is a ``501`` with the install hint, not an import
error at startup.
"""

from __future__ import annotations

import html
import io
import posixpath
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from fastapi import HTTPException
from fastapi.responses import Response

from annals.share import dir_of
from annals.store import kind_of, slugify

FORMATS = ("md", "pdf")
#: longest side of an embedded image; a 6000 px render is shrunk, a phone screenshot is not
PDF_IMAGE_MAX_PX = 1800
#: an image larger than this on disk is linked, not embedded
PDF_IMAGE_MAX_BYTES = 25_000_000
#: all embedded images of one PDF together
PDF_IMAGES_TOTAL_BYTES = 80_000_000
#: PDFs rendered at once (each takes a core for a few seconds on a small server)
PDF_CONCURRENCY = 2
_pdf_slots = threading.BoundedSemaphore(PDF_CONCURRENCY)
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


def export_filename(title: str, ext: str) -> str:
    """``<readable-slug>.<ext>``: the title's ascii words, hyphenated (see :func:`slugify`)."""
    return f"{slugify(title or '')}.{ext}"


def _attachment(name: str) -> str:
    """``Content-Disposition`` for ``name`` (ascii by construction, still quoted)."""
    return f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"


def export_response(
    fmt: str,
    *,
    title: str,
    text: str,
    rel: str,
    files: Sequence[str],
    open_file: Callable[[str], Path],
    file_url: Callable[[str], str | None],
    created: str = "",
) -> Response:
    """The ``.md`` or ``.pdf`` download of ``text`` (the markdown file ``rel`` of a document).

    ``files`` are the files the caller may serve; ``open_file(rel)`` gives one's path;
    ``file_url(rel)`` is the absolute url a reader of the PDF can open it at, or ``None``.
    """
    if fmt == "md":
        return Response(
            text.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": _attachment(export_filename(title, "md")),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    if fmt == "pdf":
        if not _pdf_slots.acquire(timeout=20):
            raise HTTPException(503, "busy making other PDFs, try again in a moment")
        try:
            pdf = markdown_to_pdf(
                text,
                title=title,
                rel=rel,
                files=files,
                open_file=open_file,
                file_url=file_url,
                created=created,
            )
        finally:
            _pdf_slots.release()
        return Response(
            pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": _attachment(export_filename(title, "pdf")),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    raise HTTPException(400, f"format must be one of {', '.join(FORMATS)}")


def trusted_base(request, base: str) -> str:
    """``base`` (the page's own url prefix, which the page sends) if it is on this request's host.

    The PDF carries links built from it, so a ``base`` naming another host is dropped
    rather than printed into a document the owner or a recipient will trust.
    """
    host = request.headers.get("x-forwarded-host", "").split(",")[
        0
    ].strip() or request.headers.get("host", "")
    parts = urlsplit(base)
    if parts.scheme in ("http", "https") and parts.netloc and parts.netloc == host:
        return base.rstrip("/")
    return ""


def file_url_builder(base: str, doc_id: str) -> Callable[[str], str | None]:
    """``rel -> <base>/raw/<doc_id>/<rel>`` (``None`` when there is no trusted base)."""

    def file_url(rel: str) -> str | None:
        if not base:
            return None
        return (
            f"{base}/raw/{quote(doc_id)}/{'/'.join(quote(p) for p in rel.split('/'))}"
        )

    return file_url


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
    try:
        from markdown_it import MarkdownIt
        from weasyprint import HTML
    except ImportError:
        raise HTTPException(
            501, "PDF export needs `pip install annals[pdf]` on the server"
        )

    allowed = list(files)
    embedded: dict[str, tuple[bytes, str]] = {}  # placeholder url -> (bytes, mime)
    used = 0
    referenced: set[str] = set()  # every file the text names
    linked: set[str] = set()  # the ones named by a link, not shown inline

    def link_for(target: str) -> str | None:
        return file_url(target)

    def image_src(target: str) -> str | None:
        """A placeholder url for an embeddable image file, or ``None`` (then it is linked)."""
        nonlocal used
        if kind_of(target) != "image":
            return None
        key = f"annals-file:{len(embedded)}"
        try:
            path = open_file(target)
            size = path.stat().st_size
            if size > PDF_IMAGE_MAX_BYTES or used + size > PDF_IMAGES_TOTAL_BYTES:
                return None
            data, mime = _shrunk(path.read_bytes(), target)
        except (HTTPException, OSError):
            return None
        used += size
        embedded[key] = (data, mime)
        return key

    md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(
        ["table", "strikethrough"]
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
                    child.attrSet("data-linked", link_for(target) or "")
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
                    child.attrSet("href", link_for(target) or "")
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
            rows.append(_media_row(kind, target, link_for(target)))
    media_in_body = "".join(
        _media_row(kind_of(t), t, link_for(t))
        for t in sorted(linked)
        if kind_of(t) in _MEDIA_LABELS or kind_of(t) == "file"
    )
    if media_in_body:
        body += f'<section class="more"><h2>Linked media</h2>{media_in_body}</section>'
    if rows:
        body += f'<section class="more"><h2>More in this document</h2>{"".join(rows)}</section>'

    meta = f'<p class="doc-meta">{html.escape(created[:10])}</p>' if created else ""
    doc = (
        f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
        f'</head><body><h1 class="doc-title">{html.escape(title)}</h1>{meta}{body}</body></html>'
    )

    def fetch(url: str, *args, **kwargs):
        if url in embedded:
            data, mime = embedded[url]
            return _fetched(data, mime)
        raise ValueError(f"not fetched: {url[:40]}")

    from weasyprint import CSS

    return HTML(string=doc, base_url="annals-doc:/", url_fetcher=fetch).write_pdf(
        stylesheets=[CSS(string=PDF_CSS)]
    )


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
