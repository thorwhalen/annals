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
- :func:`source_page`: the page a notebook reads. Its ``<title>`` is the document's title,
  which the notebook shows as the source's name, so the sources can be told apart.
- :func:`markdown_html`: markdown to html; ``markdown-it-py`` when installed (the
  ``pdf`` extra), else the text escaped in a ``<pre>``, which a notebook reads as well.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable, Mapping
from urllib.parse import quote

from annals.aggregate import numbered_first
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
#: what a source page may do: show its own images (and data: ones), nothing else
SOURCE_CSP = (
    "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
    "base-uri 'self'; form-action 'none'; frame-ancestors 'none'"
)


def source_files(meta: Mapping, files: Iterable[str]) -> list[str]:
    """The files of a document (``files``: those a caller may serve) that are sources."""
    del meta  # the kind of each file decides; kept for a caller who wants per-doc rules
    return list(numbered_first([f for f in files if kind_of(f) in SOURCE_KINDS]))


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
            skipped.append({"doc": meta["id"], "title": meta.get("title"), "kinds": kinds})
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


def _default_markdown_renderer() -> Callable[[str], str] | None:
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        return None
    # raw html in the markdown is shown as text, never run: the page is public
    md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(
        ["table", "strikethrough"]
    )
    return md.render


def markdown_html(text: str, *, render: Callable[[str], str] | None = None) -> str:
    """``text`` (markdown) as html; ``render`` overrides the default renderer."""
    render = render or _default_markdown_renderer()
    if render is None:
        return f"<pre>{html.escape(text)}</pre>"
    return render(text)


def source_page(title: str, body_html: str, *, base_href: str = "") -> str:
    """The page a notebook reads: a ``<title>``, the body, plain style, no script.

    ``base_href`` is where the body's relative links resolve (the document's files in
    the share), so an image of the document shows when a person opens the page.
    """
    base = f'<base href="{html.escape(base_href)}">\n' if base_href else ""
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        '<meta name="referrer" content="no-referrer">\n'
        f"<title>{html.escape(title)}</title>\n{base}"
        f"<style>{SOURCE_CSS}</style>\n</head>\n<body>\n<main>\n{body_html}\n</main>\n"
        "</body>\n</html>\n"
    )
