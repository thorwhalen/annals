"""A share link's page with its text in it, and no script, so every reader can read it.

A share link used to answer with a shell: a ``<title>`` and an empty ``<div>`` that the
viewer's script filled, with an html document inside a frame. NotebookLM made a
twenty-minute audio overview of such a link's title. Its fetcher does run script, so it saw
the viewer's buttons, but a group shows only titles there and a frame is not read. So the
page a link opens is now the shared text itself, rendered on the server under the rules
every shared text already follows, and nothing on it runs. The owner asked for exactly that:
a person only needs the document. The script viewer (galleries, players, downloads) is one
link away, ``<link>/?viewer``.

The same share also answers as one Markdown file and one PDF, with the same token, expiry
and revocation (the routes are :mod:`annals.share_api`'s); the page names them in
``<link rel="alternate">`` and in a line at its top::

    <link>/                 the page: every shared document's text (a group's, in order)
    <link>/d/<id>           the page of one document of the share
    <link>/share.md         the whole share as one Markdown file
    <link>/share.pdf        the whole share as one PDF (images included)
    <link>/d/<id>.md|.pdf   one document of it
    <link>/?viewer          the script viewer, as before

What goes in the page, per document: its markdown and html files (the notebook sources of
:mod:`annals.notebook`, numbered files first), markdown rendered with links and images
made safe by :func:`annals.notebook.render_source_body`, html reduced to its structure and
words by :func:`annals.combine.html_body` with a link to the page as designed; for a
document with no text, its images; its audio and video with the browser's own players;
then links to its other files. Past :data:`STATIC_MAX_BYTES` of text or
:data:`STATIC_MAX_FILES` files, the remaining files and documents are links to their own pages, so a large group still answers quickly and every
document stays reachable. A document that *is* an html page (:func:`designed_page`) is
served as itself at its own link, filtered and sandboxed as ``/raw`` serves it, with a
``<base>`` (:func:`with_base`) so its images and styles load.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import quote

from annals.aggregate import demote_headings
from annals.combine import html_body
from annals.notebook import render_source_body, source_files
from annals.share import dir_of, filter_refs, ref_decider, references, resolve_rel
from annals.store import kind_of

#: the page's text stops growing past this many bytes of html; later documents are links
STATIC_MAX_BYTES = 1_500_000
#: the text files rendered into one page at most; the rest are links (a page is made on
#: every request, and anyone holding the link may make one)
STATIC_MAX_FILES = 40
#: a document's file larger than this is linked, not put in the page
STATIC_FILE_MAX_BYTES = 2_000_000
#: images shown for a document without text (a gallery folder); the rest are listed
STATIC_MAX_IMAGES = 60
#: audio and video players in one document's page; the rest are listed
STATIC_MAX_PLAYERS = 20
#: the length of the page's ``<meta name="description">``
DESCRIPTION_CHARS = 280
#: the alternate representations of a share: path suffix, media type, label
ALTERNATES = (
    ("md", "text/plain", "Markdown"),  # served as text, so a browser shows it
    ("pdf", "application/pdf", "PDF"),
)
#: the share's whole text, at ``<link>/<SHARE_FILE>.<ext>``
SHARE_FILE = "share"
#: ``<link>/?viewer`` opens the script viewer (galleries, players, downloads) instead
VIEWER_PARAM = "viewer"
#: media a page plays with the browser's own controls
_PLAYED = {"audio": "audio", "video": "video"}


@dataclass(frozen=True)
class ShareScope:
    """What a page of one share may show and link to.

    ``link`` is the share's address (root-relative is fine: a fetcher resolves it against
    the page), ``shared_ids`` the documents it includes, ``root_id`` its group (``""`` for
    a document share), ``private_hosts`` the owner's hosts, never linked to.
    """

    link: str
    shared_ids: tuple[str, ...]
    root_id: str = ""
    private_hosts: tuple[str, ...] = ()

    def shared(self, annals_id: str) -> str | None:
        """The share's page for an annals id it includes, else ``None``."""
        link = self.link.rstrip("/")
        if annals_id in self.shared_ids:
            return f"{link}/d/{annals_id}"
        return f"{link}/" if self.root_id and annals_id == self.root_id else None

    def raw_url(self, doc_id: str, rel: str) -> str:
        rel_q = "/".join(quote(p, safe="") for p in rel.split("/"))
        return f"{self.link.rstrip('/')}/raw/{quote(doc_id, safe='')}/{rel_q}"


def alternate_urls(link: str, doc_id: str | None = None) -> list[tuple[str, str, str]]:
    """``(url, media type, label)`` of the share (or of one document of it) as files."""
    link = link.rstrip("/")
    stem = f"{link}/d/{doc_id}" if doc_id else f"{link}/{SHARE_FILE}"
    return [(f"{stem}.{ext}", mime, label) for ext, mime, label in ALTERNATES]


def alternate_links(link: str, doc_id: str | None = None) -> str:
    """The ``<link rel="alternate">`` tags of :func:`alternate_urls`, for the ``<head>``."""
    return "".join(
        f'<link rel="alternate" type="{mime}" href="{html.escape(url)}" '
        f'title="{label}">\n'
        for url, mime, label in alternate_urls(link, doc_id)
    )


class _Budget:
    """What one page may still render: bytes of text and a number of files."""

    def __init__(self, max_bytes: int, max_files: int | None = None):
        self.bytes_left = max_bytes
        self.files_left = STATIC_MAX_FILES if max_files is None else max_files

    @property
    def spent(self) -> bool:
        return self.bytes_left <= 0 or self.files_left <= 0

    def spend(self, n_bytes: int) -> None:
        self.bytes_left -= n_bytes
        self.files_left -= 1


def designed_page(meta: Mapping, files: Sequence[str]) -> str | None:
    """The html file a document's page *is*, when it is one, else ``None``.

    Such a document is served as itself at its link (filtered and sandboxed, as ``/raw``
    serves it): a person sees it as designed, and a fetcher, even one that runs script,
    reads it at the top level rather than inside a frame it does not open.
    """
    main = meta.get("main") or ""
    return main if main in files and kind_of(main) == "html" else None


_BASE_RE = re.compile(rb"<base\b[^>]*>", re.I)
#: a page's own referrer policy would override the share's ``no-referrer`` (the link is a key)
_REFERRER_META_RE = re.compile(
    rb"<meta\b[^>]*\bname\s*=\s*[\"']?referrer\b[^>]*>", re.I
)
_DOCTYPE_AT_START = re.compile(rb"(?:\xef\xbb\xbf)?\s*<!doctype[^>]*>", re.I)


def with_base(page: bytes, href: str) -> bytes:
    """``page`` with ``<base href>`` as its first element, so its relative references
    (images, styles, its other pages) resolve where the share serves its files.

    The page's own ``<base>`` and referrer ``<meta>`` go: either would send its requests,
    or the link, elsewhere. The tag goes right after the doctype, where the parser puts it
    in the head whatever comes later (a ``<head>`` written in a comment, say).
    """
    page = _REFERRER_META_RE.sub(b"", _BASE_RE.sub(b"", page))
    tag = f'<base href="{html.escape(href, quote=True)}">'.encode()
    d = _DOCTYPE_AT_START.match(page)
    at = d.end() if d else 0
    return page[:at] + tag + page[at:]


def _doc_html(
    meta: Mapping,
    files: Sequence[str],
    *,
    read_text: Callable[[str, str], str],
    scope: ShareScope,
    demote: int,
    budget: "_Budget",
) -> str:
    """One document's text and files as an html fragment (see the module docstring).

    ``read_text`` raising ``KeyError``, ``OSError`` or ``ValueError`` (a file gone, or too
    large) leaves that file as a link; ``budget`` is spent per file rendered, and once it
    is spent the remaining files are links too.
    """
    doc_id = meta["id"]
    sizes = meta.get("sizes") or {}
    sources = source_files(meta, files)
    shown: set[str] = set()
    parts: list[str] = []
    for rel in sources:
        if budget.spent or int(sizes.get(rel, 0)) > STATIC_FILE_MAX_BYTES:
            continue  # listed with the other files below
        try:
            text = read_text(doc_id, rel)
        except (KeyError, OSError, ValueError):
            continue
        budget.spend(len(text))
        shown.add(rel)
        if len(sources) > 1:
            parts.append(f"<p><strong>{html.escape(rel)}</strong></p>")
        if kind_of(rel) == "md":
            parts.append(
                render_source_body(
                    demote_headings(text, demote) if demote else text,
                    link=scope.link,
                    doc_id=doc_id,
                    rel=rel,
                    files=tuple(files),
                    sources=tuple(sources),
                    shared_ids=scope.shared_ids,
                    root_id=scope.root_id,
                    private_hosts=scope.private_hosts,
                )
            )
        else:
            designed = scope.shared(doc_id)
            if designed and rel == designed_page(meta, files):
                parts.append(
                    f'<p class="muted"><a href="{html.escape(designed)}">'
                    "Open the page as designed</a></p>"
                )
            parts.append(
                _html_doc(text, doc_id, rel, files, scope=scope, demote=demote)
            )
        shown |= set(references(text, kind_of(rel), from_dir=dir_of(rel))["files"])
    if not shown:
        images = [f for f in files if kind_of(f) == "image"][:STATIC_MAX_IMAGES]
        parts.extend(
            f'<figure><img src="{html.escape(scope.raw_url(doc_id, f))}" '
            f'alt="{html.escape(f)}" loading="lazy"></figure>'
            for f in images
        )
        shown |= set(images)
    played = [f for f in files if f not in shown and kind_of(f) in _PLAYED]
    for f in played[:STATIC_MAX_PLAYERS]:
        tag = _PLAYED[kind_of(f)]
        src = html.escape(scope.raw_url(doc_id, f))
        parts.append(
            f'<p>{html.escape(f)}</p><{tag} controls preload="none" src="{src}"></{tag}>'
        )
        shown.add(f)
    rest = [f for f in files if f not in shown]
    if rest:
        items = "".join(
            f'<li><a href="{html.escape(scope.raw_url(doc_id, f))}">{html.escape(f)}</a></li>'
            for f in rest
        )
        parts.append(f"<p>Files:</p><ul>{items}</ul>")
    return "\n".join(parts)


def _html_doc(
    text: str,
    doc_id: str,
    rel: str,
    files: Sequence[str],
    *,
    scope: ShareScope,
    demote: int,
) -> str:
    """An html file of the share: filtered like any shared text, then its words and structure."""
    text = filter_refs(
        text,
        "html",
        files=files,
        shared=scope.shared,
        from_dir=dir_of(rel),
        private_hosts=scope.private_hosts,
    )
    included = set(files)

    def image_src(src: str) -> str | None:
        target = resolve_rel(src, dir_of(rel))
        if target in included and kind_of(target) == "image":
            return scope.raw_url(doc_id, target)
        return None  # an image elsewhere is never loaded from the share's page

    decide = ref_decider(
        from_dir=dir_of(rel),
        files=included,
        shared=scope.shared,
        private_hosts=scope.private_hosts,
    )
    # the link filter read the text as text; the parser here may read an attribute
    # differently, so every link it keeps is decided again
    return html_body(text, rewrite_src=image_src, rewrite_href=decide, demote=demote)


def page_body(
    docs: Iterable[tuple[Mapping, Sequence[str]]],
    *,
    title: str,
    read_text: Callable[[str, str], str],
    scope: ShareScope,
    doc_id: str | None = None,
    viewer_url: str | None = None,
    max_bytes: int | None = None,
) -> tuple[str, str]:
    """The page's content and its description: ``(html, plain text of ~280 chars)``.

    ``docs`` are the ``(meta, files)`` pairs to show, in order (one, for a document's
    page); ``read_text(doc_id, rel)`` reads a file as it is on disk (the shared-text
    filters are applied here). ``doc_id`` names the document a ``/d/<id>`` page is for,
    which picks the alternates the page offers; ``viewer_url`` is where the script viewer
    opens it. ``max_bytes``: :data:`STATIC_MAX_BYTES`.
    """
    max_bytes = STATIC_MAX_BYTES if max_bytes is None else max_bytes
    docs = list(docs)
    several = len(docs) > 1
    alts = " · ".join(
        f'<a href="{html.escape(url)}">{label}</a>'
        for url, _, label in alternate_urls(scope.link, doc_id)
    )
    if viewer_url:
        alts += f' · <a href="{html.escape(viewer_url)}">open in the viewer</a>'
    out = [
        f"<h1>{html.escape(title)}</h1>",
        f'<p class="muted">Also as {alts}.</p>',
    ]
    budget, more = _Budget(max_bytes), []
    for meta, files in docs:
        name = meta.get("title") or meta["id"]
        if budget.spent:
            more.append((meta["id"], name))
            continue
        body = _doc_html(
            meta,
            files,
            read_text=read_text,
            scope=scope,
            demote=2 if several else 0,
            budget=budget,
        )
        if several:
            href = html.escape(scope.shared(meta["id"]) or "")
            body = f'<h2><a href="{href}">{html.escape(name)}</a></h2>\n{body}'
        out.append(f"<article>\n{body}\n</article>")
    if more:
        items = "".join(
            f'<li><a href="{html.escape(scope.shared(i) or "")}">{html.escape(n)}</a></li>'
            for i, n in more
        )
        out.append(f"<h2>More in this share</h2><ul>{items}</ul>")
    content = "\n".join(out)
    return content, description_of(content, skip=title)


def description_of(content: str, *, skip: str = "", n: int = DESCRIPTION_CHARS) -> str:
    """The first ``n`` characters of the page's words (the title and alternates line left out)."""
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", content, flags=re.S | re.I)
    text = re.sub(r'<p class="muted">Also as .*?</p>', " ", text, count=1, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = " ".join(text.split())
    if skip and text.startswith(skip):
        text = text[len(skip) :].lstrip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"
