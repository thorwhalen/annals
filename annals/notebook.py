"""A share's documents as separate notebook sources: one plain web page per text file.

A notebook product (NotebookLM, and Gemini's notebooks, which share its sources) takes a
web page by its link, one source per link, and several links pasted at once; it reads
the page's text and keeps its own copy. It does not unpack a zip, and its upload picker
needs the files on the device first. So the fewest taps from an iPad is: tick the
documents, copy one list of links, paste it into the notebook (see
``misc/docs/notebook-sources.md`` for the research behind this).

The links are a share's (:mod:`annals.share`): unguessable, scoped to the documents
ticked, expiring, revocable, and filtered like every shared text. This module only
decides what becomes a source and how one looks::

    GET <share link>/source/<doc id>/<file>   a script-free html page: <title>, the text

- :func:`source_files`: which files of a document are sources (markdown and html pages,
  numbered files first, as :func:`annals.aggregate.numbered_first` orders them).
- :func:`notebook_sources`: the ``{doc, file, title, url}`` rows of a share, in its order.
- :func:`source_scope`: what a notebook share includes of a document: its source pages
  and the files they show, never the rest of a folder.
- :func:`render_source`: one markdown file as its source page, shared-text rules applied
  twice: to the text (:func:`annals.share.filter_refs`), then to every link and image of
  the rendered page (:func:`annals.share.ref_decider` over markdown-it's tokens), and
  any annals id left in it removed. Cached, and rendered only up to
  :data:`RENDER_MAX_BYTES` (a larger file is sent as escaped text): it is a public route.
- :func:`source_page`: the page a notebook reads. Its ``<title>`` is the document's title,
  which the notebook shows as the source's name, so the sources can be told apart.
- :func:`markdown_html`: markdown to html; ``markdown-it-py`` when installed (the
  ``pdf`` extra), else the text escaped in a ``<pre>``, which a notebook reads as well.
"""

from __future__ import annotations

import functools
import html
from collections.abc import Callable, Iterable, Mapping
from urllib.parse import quote

from annals.aggregate import numbered_first
from annals.share import (
    REMOVED_LINK,
    dir_of,
    filter_refs,
    ref_decider,
    references,
    remove_unshared_ids,
    resolve_rel,
)
from annals.store import kind_of

#: the kinds of file a notebook can take from a link (images, audio, video and pdf it
#: takes only as uploads)
SOURCE_KINDS = ("md", "html")
#: the path segment of a source page under a share link
SOURCE_SEGMENT = "source"
#: a source page is read by a fetcher and, now and then, by a person: plain, readable,
#: light or dark, no script and nothing loaded from elsewhere
SOURCE_CSS = (
    ":root{color-scheme:light dark}"
    "body{font:17px/1.6 system-ui,-apple-system,'Segoe UI',sans-serif;"
    "max-width:46rem;margin:0 auto;padding:1.5rem 1rem 4rem}"
    "pre,code{font-family:ui-monospace,Menlo,monospace;font-size:.9em}"
    "pre{white-space:pre-wrap;overflow-wrap:anywhere}"
    "table{border-collapse:collapse}th,td{border:1px solid #8884;padding:.3em .6em}"
    "img{max-width:100%;height:auto}"
)
#: what a source page may do: show its own images (and data: ones), nothing else; a
#: sandbox (no origin, no script, no form) even so, since it is served beside the owner's app
SOURCE_CSP = (
    "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
#: an html source: its own styles and images, no script, no request elsewhere
HTML_SOURCE_CSP = (
    "sandbox; default-src 'none'; img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
#: markdown past this size is sent as escaped text, not rendered: rendering is
#: superlinear on hostile input, and the route is public
RENDER_MAX_BYTES = 300_000
#: rendered source pages kept in memory (each at most a few times RENDER_MAX_BYTES)
SOURCE_CACHE_SIZE = 32


def source_files(meta: Mapping, files: Iterable[str]) -> list[str]:
    """The files of a document (``files``: those a caller may serve) that are sources."""
    del meta  # the kind of each file decides; kept for a caller who wants per-doc rules
    return list(numbered_first([f for f in files if kind_of(f) in SOURCE_KINDS]))


def source_scope(
    read_text: Callable[[str, str], str],
) -> Callable[[Mapping], list[str]]:
    """``meta -> files``: a document's source pages and the files they show, for a share.

    ``read_text(doc_id, rel)`` reads one file. A notebook share made with this (the
    ``files_of`` of :meth:`annals.share.Shares.create`) reaches nothing else of a folder.
    """

    def files_of(meta: Mapping) -> list[str]:
        files = list(meta.get("files", []))
        keep = set(source_files(meta, files))
        for rel in list(keep):
            try:
                text = read_text(meta["id"], rel)
            except (KeyError, OSError, ValueError, UnicodeDecodeError):
                continue
            keep |= set(references(text, kind_of(rel), from_dir=dir_of(rel))["files"])
        return [f for f in files if f in keep]

    return files_of


def source_title(meta: Mapping, rel: str, *, several: bool) -> str:
    """The source's name in the notebook: the document's title, plus the file if it has several."""
    title = (meta.get("title") or meta.get("id") or rel).strip()
    return f"{title} · {rel}" if several else title


def source_url(link: str, doc_id: str, rel: str) -> str:
    """``<link>/source/<doc id>/<file>`` (``link``: the share's, with or without a slash)."""
    rel_q = "/".join(quote(p, safe="") for p in rel.split("/"))
    return f"{link.rstrip('/')}/{SOURCE_SEGMENT}/{doc_id}/{rel_q}"


def notebook_sources(
    scope: Iterable[tuple[Mapping, Iterable[str]]], *, link: str
) -> dict:
    """One row per source file of ``scope`` (``(meta, files)`` pairs, in the share's order).

    ``{"sources": [{"doc", "file", "title", "url"}], "skipped": [{"doc", "title",
    "kinds"}]}``; ``skipped`` names the documents with nothing a notebook can take from a
    link (only images, audio, pdf...), so the page can say why they are missing.
    """
    sources, skipped = [], []
    for meta, files in scope:
        files = list(files)
        rels = source_files(meta, files)
        if not rels:
            kinds = sorted({kind_of(f) for f in files})
            skipped.append(
                {"doc": meta["id"], "title": meta.get("title"), "kinds": kinds}
            )
            continue
        for rel in rels:
            sources.append(
                {
                    "doc": meta["id"],
                    "file": rel,
                    "title": source_title(meta, rel, several=len(rels) > 1),
                    "url": source_url(link, meta["id"], rel),
                }
            )
    return {"sources": sources, "skipped": skipped}


@functools.lru_cache(maxsize=1)
def _markdown_it():
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        return None
    # raw html in the markdown is shown as text, never run: the page is public
    return MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(
        ["table", "strikethrough"]
    )


def _default_markdown_renderer() -> Callable[..., str] | None:
    md = _markdown_it()
    if md is None:
        return None

    def render(
        text: str, rewrite_url: Callable[[str], str | None] | None = None
    ) -> str:
        tokens = md.parse(text)
        if rewrite_url:
            for tok in tokens:
                if tok.children:
                    tok.children = _rewritten(tok.children, rewrite_url)
        return md.renderer.render(tokens, md.options, {})

    return render


def _rewritten(children: list, rewrite_url: Callable[[str], str | None]) -> list:
    """Inline tokens with every link and image passed through ``rewrite_url``.

    A link it refuses keeps its words and loses its target, except an autolink, whose
    words are the target: they become :data:`annals.share.REMOVED_LINK`. An image it
    refuses goes.
    """
    out, dropped = [], []  # dropped: one flag per open link, so its close goes too
    hiding = False  # inside a refused autolink
    for tok in children:
        if tok.type == "link_open":
            new = rewrite_url(tok.attrGet("href") or "")
            dropped.append(new is None)
            if new is None:
                hiding = tok.markup == "autolink"
                continue
            tok.attrSet("href", new)
        elif tok.type == "link_close":
            if dropped and dropped.pop():
                if hiding:
                    tok.type, tok.tag, tok.nesting, tok.content = (
                        "text",
                        "",
                        0,
                        REMOVED_LINK,
                    )
                    hiding = False
                    out.append(tok)
                continue
        elif hiding:
            continue
        elif tok.type == "image":
            new = rewrite_url(tok.attrGet("src") or "")
            if new is None:
                continue
            tok.attrSet("src", new)
        out.append(tok)
    return out


def markdown_html(
    text: str,
    *,
    rewrite_url: Callable[[str], str | None] | None = None,
    render: Callable[..., str] | None = None,
) -> str:
    """``text`` (markdown) as html; every link and image through ``rewrite_url``.

    ``render(text, rewrite_url)`` overrides the default renderer. Without one (no
    ``markdown-it-py``) the text is escaped in a ``<pre>``: no markup, so no link.
    """
    render = render or _default_markdown_renderer()
    if render is None:
        return f"<pre>{html.escape(text)}</pre>"
    return render(text, rewrite_url)


def source_link_rewriter(
    decide: Callable[[str], str | None],
    *,
    link: str,
    doc_id: str,
    from_dir: str,
    sources: Iterable[str],
) -> Callable[[str], str | None]:
    """``url -> url | None`` for a source page, which has no ``<base>``.

    ``decide`` (:func:`annals.share.ref_decider`) says what may stay; a relative file it
    keeps becomes absolute here: another source page of the document links to that
    page, any other file to the share's raw file. Anchors and web links stay as they are.
    """
    sources = set(sources)
    raw = f"{link.rstrip('/')}/raw/{doc_id}/"

    def rewrite(url: str) -> str | None:
        new = decide(url)
        if new is None:
            return None
        rel = resolve_rel(new, from_dir)
        if rel is None:
            return new
        frag = new[new.index("#") :] if "#" in new else ""
        if rel in sources:
            return source_url(link, doc_id, rel) + frag
        return raw + "/".join(quote(p, safe="") for p in rel.split("/")) + frag

    return rewrite


@functools.lru_cache(maxsize=SOURCE_CACHE_SIZE)
def render_source(
    text: str,
    *,
    title: str,
    link: str,
    doc_id: str,
    rel: str,
    files: tuple[str, ...],
    sources: tuple[str, ...],
    shared_ids: tuple[str, ...],
    root_id: str = "",
    private_hosts: tuple[str, ...] = (),
) -> str:
    """One markdown file of a share as its source page (see the module docstring).

    Every argument is hashable, so a page is rendered once per text and scope.
    ``shared_ids`` are the annals ids the share includes (opened at ``<link>/d/<id>``),
    ``root_id`` the shared group's (opened at ``<link>/``).
    """
    link = link.rstrip("/")

    def shared(annals_id: str) -> str | None:
        if annals_id in shared_ids:
            return f"{link}/d/{annals_id}"
        return f"{link}/" if root_id and annals_id == root_id else None

    from_dir = dir_of(rel)
    text = filter_refs(
        text,
        "md",
        files=files,
        shared=shared,
        from_dir=from_dir,
        private_hosts=private_hosts,
    )
    if len(text.encode("utf-8")) > RENDER_MAX_BYTES:
        body = f"<pre>{html.escape(text)}</pre>"
    else:
        decide = ref_decider(
            from_dir=from_dir,
            files=set(files),
            shared=shared,
            private_hosts=private_hosts,
        )
        rewrite = source_link_rewriter(
            decide, link=link, doc_id=doc_id, from_dir=from_dir, sources=sources
        )
        body = markdown_html(text, rewrite_url=rewrite)
    return source_page(title, remove_unshared_ids(body, shared))


def source_page(title: str, body_html: str) -> str:
    """The page a notebook reads: a ``<title>``, the body, plain style, no script."""
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        '<meta name="referrer" content="no-referrer">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{SOURCE_CSS}</style>\n</head>\n<body>\n<main>\n{body_html}\n</main>\n"
        "</body>\n</html>\n"
    )
