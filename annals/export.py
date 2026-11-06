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

:func:`aggregate_response` is the same kind of download for many files at once: a group's
(or a share's) files as one ``.md``, ``.html`` or ``.pdf``, made by :mod:`annals.combine`
from what the caller passes in. The page-rendering core is :mod:`annals.render`.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import HTTPException
from fastapi.responses import Response

from annals.aggregate import TooLarge
from annals.combine import (
    FORMATS as FORMATS_COMBINE,
    HTML_CSP,
    Combined,
    NothingToCombine,
    Source,
    combine,
    skipped_header,
)
from annals.config import MAX_AGGREGATE_BYTES
from annals.render import (  # noqa: F401  (re-exported: the names tests and callers know)
    PDF_CSS,
    PDF_IMAGE_MAX_BYTES,
    PDF_IMAGE_MAX_PIXELS,
    PDF_IMAGE_MAX_PX,
    PDF_IMAGES_TOTAL_BYTES,
    PDF_MAX_TEXT_BYTES,
    kind_of_mime,
    resolve_ref,
)
from annals.render import markdown_to_pdf as _markdown_to_pdf
from annals.requirements import MissingDependency
from annals.store import kind_of, slugify

FORMATS = ("md", "pdf")
#: PDFs rendered at once (each takes a core for a few seconds on a small server)
PDF_CONCURRENCY = 2
#: seconds a busy server tells a client to wait before asking again
PDF_RETRY_AFTER_S = 10
_pdf_active = 0  # PDFs being made; only touched on the event loop, so no lock


def export_filename(title: str, ext: str) -> str:
    """``<readable-slug>.<ext>``: the title's ascii words, hyphenated (see :func:`slugify`)."""
    return f"{slugify(title or '')}.{ext}"


def _attachment(title: str, ext: str) -> str:
    """``Content-Disposition``: an ascii name for old clients, the title itself in ``filename*``."""
    ascii_name = export_filename(title, ext)
    full = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]+', " ", title or "").strip()[:100]
    utf8 = f"{full}.{ext}" if full else ascii_name
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(utf8)}"


def markdown_response(
    text: str, *, title: str, download: bool = True, ext: str = "md"
) -> Response:
    """``text`` as a ``.md`` download named after ``title``, or (``download=False``) shown
    as plain text in the browser, which every phone can display, select and copy.

    ``ext="txt"`` saves it as plain text instead (a list of addresses is not markdown).
    """
    disposition = _attachment(title, ext)
    if not download:
        disposition = "inline" + disposition[len("attachment") :]
    markdown = download and ext == "md"
    return Response(
        text.encode("utf-8"),
        media_type=f"text/{'markdown' if markdown else 'plain'}; charset=utf-8",
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def markdown_to_pdf(*args, **kwargs) -> bytes:
    """:func:`annals.render.markdown_to_pdf`, a missing library being a ``501`` here."""
    try:
        return _markdown_to_pdf(*args, **kwargs)
    except MissingDependency as e:
        raise HTTPException(501, str(e))


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
        return markdown_response(text, title=title)
    if fmt == "pdf":
        if len(text.encode("utf-8")) > PDF_MAX_TEXT_BYTES:
            raise HTTPException(413, "this page is too large to make a PDF of")
        pdf = markdown_to_pdf(
            text,
            title=title,
            rel=rel,
            files=files,
            open_file=open_file,
            file_url=file_url,
            created=created,
        )
        return Response(
            pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": _attachment(title, "pdf"),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    raise HTTPException(400, f"format must be one of {', '.join(FORMATS)}")


def _no_files(rel: str) -> Path:
    raise OSError(f"no file access for {rel}")


def sources_of(
    docs: Iterable[tuple[dict, Iterable[str]]],
    *,
    read: Callable[[str, str], str],
    open_path: Callable[[str, str], Path] | None = None,
    read_bytes: Callable[[str, str], bytes] | None = None,
    file_url: Callable[[str, str], str | None] | None = None,
) -> list[Source]:
    """:class:`annals.combine.Source` for ``(meta, files)`` pairs and the callers' readers.

    ``open_path(doc_id, rel)`` gives a file's path; ``read_bytes(doc_id, rel)`` reads it
    where the caller must change the bytes (a share filters svg text). An ``HTTPException``
    from either (the servers' own "no such file", "too large") is a file that cannot be
    read here, which leaves it out of the result instead of ending the whole job.
    """

    def guarded(fn, doc_id: str):
        def call(rel: str):
            try:
                return fn(doc_id, rel)
            except HTTPException as e:
                raise ValueError(f"{rel}: {e.detail}") from e

        return call

    def opener(doc_id: str) -> Callable[[str], Path]:
        if open_path is None:
            return _no_files
        return guarded(open_path, doc_id)

    return [
        Source(
            meta=meta,
            files=list(files),
            read_text=guarded(read, meta["id"]),
            open_path=opener(meta["id"]),
            file_url=(
                functools.partial(file_url, meta["id"])
                if file_url
                else (lambda rel: None)
            ),
            read_bytes=guarded(read_bytes, meta["id"]) if read_bytes else None,
        )
        for meta, files in docs
    ]


def combine_is_heavy(fmt: str, docs: Iterable[tuple[dict, Iterable[str]]]) -> bool:
    """Whether making ``fmt`` of ``docs`` takes real CPU: a PDF, or any PDF to read the text of.

    Heavy jobs share the ``PDF_CONCURRENCY`` slots; a markdown of plain text does not wait
    for them.
    """
    return fmt == "pdf" or any(kind_of(f) == "pdf" for _, files in docs for f in files)


def aggregate_response(
    docs: Iterable[tuple[dict, Iterable[str]]],
    *,
    read: Callable[[str, str], str],
    title: str,
    download: bool = False,
    demote: int = 1,
    max_bytes: int = MAX_AGGREGATE_BYTES,
    fmt: str = "md",
    open_path: Callable[[str, str], Path] | None = None,
    read_bytes: Callable[[str, str], bytes] | None = None,
) -> Response:
    """The files of ``docs`` as ONE ``fmt`` ("md", "html" or "pdf") download, made now.

    ``docs`` are ``(meta, files)`` pairs, ``files`` being what the caller may serve;
    ``read(doc_id, rel)`` gives a file's text (filtered, for a share) and ``open_path(doc_id,
    rel)`` its path (for PDFs and images), ``read_bytes`` how to read one where the bytes
    must be changed (a share filters svg). See :mod:`annals.combine` for what goes into
    which format. Nothing is kept. ``X-Annals-Sections`` says how many files went in and
    ``X-Annals-Skipped`` (percent-encoded JSON) which were left out and why.
    """
    if fmt not in FORMATS_COMBINE:
        raise HTTPException(
            400, f"format must be one of {', '.join(FORMATS_COMBINE)}, not {fmt!r}"
        )
    try:
        combined = combine(
            sources_of(docs, read=read, open_path=open_path, read_bytes=read_bytes),
            fmt,
            title=title,
            demote=demote,
            max_text_bytes=max_bytes,
        )
    except TooLarge as e:
        raise HTTPException(413, str(e))
    except NothingToCombine as e:
        raise HTTPException(404, str(e))
    except MissingDependency as e:
        raise HTTPException(501, str(e))
    response = combined_response(combined, title=title, download=download)
    response.headers["X-Annals-Sections"] = str(combined.sections)
    response.headers["X-Annals-Format"] = combined.fmt
    if combined.skipped:
        response.headers["X-Annals-Skipped"] = quote(skipped_header(combined.skipped))
    return response


def combined_response(combined: Combined, *, title: str, download: bool) -> Response:
    """A :class:`annals.combine.Combined` as a response: shown, or saved with ``download``."""
    if combined.fmt == "md":
        return markdown_response(
            combined.data.decode("utf-8"), title=title, download=download
        )
    disposition = _attachment(title, combined.ext)
    if not download:
        disposition = "inline" + disposition[len("attachment") :]
    headers = {
        "Content-Disposition": disposition,
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if combined.fmt == "html":  # nothing in the page runs; the header says so too
        headers["Content-Security-Policy"] = f"sandbox; {HTML_CSP}"
    return Response(combined.data, media_type=combined.media_type, headers=headers)


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


async def run_limited(make: Callable[[], Response], *, limited: bool) -> Response:
    """``make`` in a worker thread; when ``limited``, at most ``PDF_CONCURRENCY`` at once.

    One over the limit is refused at once (``503`` and ``Retry-After``) instead of waiting:
    a waiting request would hold one of the threads every app shares.
    """
    global _pdf_active
    import anyio.to_thread

    if not limited:
        return await anyio.to_thread.run_sync(make)
    if _pdf_active >= PDF_CONCURRENCY:
        raise HTTPException(
            503,
            "busy making other PDFs, try again in a moment",
            headers={"Retry-After": str(PDF_RETRY_AFTER_S)},
        )
    _pdf_active += 1
    try:
        return await anyio.to_thread.run_sync(make)
    finally:
        _pdf_active -= 1


async def run_export(fmt: str, **kwargs) -> Response:
    """:func:`export_response` in a worker thread, PDFs limited (see :func:`run_limited`)."""
    return await run_limited(
        lambda: export_response(fmt, **kwargs), limited=fmt == "pdf"
    )
