"""Many files of many kinds as ONE document: a Markdown, html or PDF file.

The mechanism is a registry. A *converter* turns one file of one kind into a *part* of the
output format (markdown text, an html fragment, a PDF); a *joiner* puts the parts of a
format together (a table of contents and a section each; bookmarks and pages). Which pairs
exist is the table :data:`REGISTRY`, filled by :func:`register`::

    @register("pdf", "md", requires=("pdfdol",))
    def pdf_to_md(item, ctx): ...

so a new pair (docx to pdf, say) is one decorated function, and the web page, the API and
the CLI all learn it from :func:`supported` without a change.

What goes in::

    =========  ===========  =======================================================
    input      to md        to html / to pdf
    =========  ===========  =======================================================
    md         as it is     rendered (images of the document inside)
    html       converted    its text and structure (scripts and styles dropped)
    text       a code block a preformatted block
    pdf        its text     html: its text; pdf: its pages, joined as they are
    image      -            a figure (html) / a page of its own (pdf)
    =========  ===========  =======================================================

Audio, video and other files have no place in a document: they are reported as left out,
each with the reason, never silently dropped. A file that cannot be read (a damaged or
password-protected PDF) is left out the same way, and the others still go in.

An image or a text file that sits in a document with pages (markdown, html, a PDF) is part
of that document, not a section of its own: a report and its figures combine as the report.

Heavy libraries load only when a pair needs them (WeasyPrint for PDF pages, pypdf and pdfdol
to join and read PDFs, markdownify for html to markdown); a missing one is a
:class:`annals.requirements.MissingDependency` that says what to install, raised before any
work starts. Nothing is stored: the document is made per call.

>>> combined = combine([_demo_source({"b.md": "# B\\ntext", "a.md": "hello"})], "md", title="T")
>>> combined.sections, combined.ext
(2, 'md')
>>> print(combined.data.decode().splitlines()[0])
# T
"""

from __future__ import annotations

import html
import io
import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from annals.aggregate import (
    TooLarge,
    aggregate_markdown,
    demote_headings,
    numbered_first,
    unique_paths,
)
from annals.config import MAX_AGGREGATE_BYTES, MAX_COMBINE_BYTES
from annals.render import (
    PDF_MAX_TEXT_BYTES,
    Embedder,
    html_to_pdf,
    inline_embedded,
    markdown_to_html,
    page_html,
    resolve_ref,
)
from annals import requirements
from annals.requirements import (
    MissingDependency,
    check_requirements,
    import_lazily,
)
from annals.store import FOLDER, kind_of

#: kinds whose file is a document in itself
PAGE_KINDS = frozenset({"md", "html", "pdf"})
#: kinds that illustrate or accompany a document with pages, so are not sections of its own
COMPANION_KINDS = frozenset({"image", "text"})
#: skipped files listed in a result (and its headers); the rest are counted
MAX_SKIPPED_LISTED = 4
#: a PDF with more pages than this is not read for its text (about 0.2 s a page)
MAX_TEXT_PAGES = 300
#: files made into PDF pages by rendering (about 0.4 s each) in one output
MAX_RENDERED_FILES = 60
#: a text or html file larger than this is left out, and the others still go in
MAX_TEXT_FILE_BYTES = 2_000_000
#: html nested deeper than this is flattened (very deep trees overflow the converters)
MAX_HTML_DEPTH = 100
#: a table cell may span this many columns or rows (a bigger number is a layout attack)
MAX_SPAN = 100
#: headings of an embedded markdown or html file go this far down, under the section's own
HTML_DEMOTE = 2


class NothingToCombine(ValueError):
    """No file could be put in the output (the message says which kinds could)."""


class ConversionError(ValueError):
    """One file could not be converted (damaged, protected, too large); the rest go on."""


@dataclass(frozen=True)
class Source:
    """One document, as a caller lets it be read: its files and how to get at them.

    ``read_text(rel)`` is the file's text (a share gives the *filtered* text);
    ``open_path(rel)`` its path on disk, for bytes. Either may raise ``OSError`` or
    ``KeyError`` for a file that is gone, which leaves that file out.
    """

    meta: dict
    files: Sequence[str]
    read_text: Callable[[str], str]
    open_path: Callable[[str], Path]
    file_url: Callable[[str], str | None] = lambda rel: None
    #: how bytes are read when not straight from ``open_path`` (a share filters svg text)
    read_bytes: Callable[[str], bytes] | None = None

    @property
    def title(self) -> str:
        return (self.meta.get("title") or self.meta["id"]).replace("/", "-").strip()

    def size(self, rel: str) -> int:
        return int((self.meta.get("sizes") or {}).get(rel, 0))

    def data(self, rel: str) -> bytes:
        if self.read_bytes is not None:
            return self.read_bytes(rel)
        return self.open_path(rel).read_bytes()


@dataclass(frozen=True)
class Item:
    """One file to put in the output: a section, or a run of pages."""

    source: Source
    rel: str
    kind: str
    label: str  # its name in the output: ``rel``, or ``Title/rel`` in a folder
    title: str  # the title of a page of its own

    @property
    def size(self) -> int:
        return self.source.size(self.rel)

    def text(self) -> str:
        return self.source.read_text(self.rel)

    def data(self) -> bytes:
        return self.source.data(self.rel)


@dataclass
class Context:
    """What a converter may use besides the item: where images go, and the output's own needs."""

    fmt: str
    embedder: Embedder = field(default_factory=Embedder)


Part = str | bytes
Converter = Callable[[Item, Context], Part]


@dataclass(frozen=True)
class Pair:
    """One (kind, format) cell of the registry."""

    kind: str
    fmt: str
    fn: Converter
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class Skipped:
    """A file left out, and why."""

    label: str
    reason: str


@dataclass(frozen=True)
class Combined:
    """The result: the file's bytes, what it is, how many files went in and which did not."""

    data: bytes
    fmt: str
    media_type: str
    ext: str
    sections: int
    skipped: tuple[Skipped, ...] = ()


# -- the registry ------------------------------------------------------------------------

#: (kind, format) -> :class:`Pair`; add a pair with :func:`register`
REGISTRY: dict[tuple[str, str], Pair] = {}


def register(
    kind: str, fmt: str, *, requires: Sequence[str] = ()
) -> Callable[[Converter], Converter]:
    """Decorator: the function turns a file of ``kind`` into a part of the ``fmt`` output.

    ``requires`` are the (importable) modules it needs, checked before any work starts.
    """

    def deco(fn: Converter) -> Converter:
        REGISTRY[(kind, fmt)] = Pair(kind, fmt, fn, tuple(requires))
        return fn

    return deco


def kinds_for(fmt: str) -> tuple[str, ...]:
    """The kinds of file that can be put in a ``fmt`` output, in a stable order."""
    order = ("md", "html", "text", "pdf", "image")
    got = {k for k, f in REGISTRY if f == fmt}
    return tuple(k for k in order if k in got) + tuple(sorted(got - set(order)))


def supported() -> dict[str, dict]:
    """What can be made: ``{format: {"label", "ext", "kinds"}}``, for a page or a message."""
    return {
        fmt: {"label": spec.label, "ext": spec.ext, "kinds": list(kinds_for(fmt))}
        for fmt, spec in FORMATS.items()
    }


_KIND_NAMES = {
    "md": "markdown",
    "html": "html",
    "text": "text",
    "pdf": "PDF",
    "image": "image",
    "video": "video",
    "audio": "audio",
    "file": "other",
}


def _kind_name(kind: str, *, plural: bool = False) -> str:
    name = _KIND_NAMES.get(kind, kind)
    return name + ("s" if plural and name not in ("other",) else "")


def explain(fmt: str) -> str:
    """One sentence on what a ``fmt`` output is made of (the 'supported' part of a message)."""
    spec = FORMATS[fmt]
    names = [_kind_name(k) for k in kinds_for(fmt)]
    return f"{spec.label} is made from {', '.join(names[:-1])} and {names[-1]} files"


# -- sources to items --------------------------------------------------------------------


def items_of(sources: Iterable[Source], fmt: str) -> Iterator[Item]:
    """The files to try for a ``fmt`` output, in the documents' order.

    A document with pages (markdown, html, PDF) contributes those; its images and text
    files are its own parts. A document with none contributes whatever it holds, so what
    cannot be used (a video) is reported and not silently missing. A folder, or a document
    with several such files, names each by its title then the file (``Report/01-intro.md``).
    """
    for src in sources:
        kinds = {rel: kind_of(rel) for rel in src.files}
        has_pages = any(k in PAGE_KINDS for k in kinds.values())
        md_stems = {_stem(rel) for rel, k in kinds.items() if k == "md"}
        chosen = [
            rel
            for rel, k in kinds.items()
            if (k in PAGE_KINDS if has_pages else True)
            # report.html / report.pdf beside report.md are renderings of it
            and not (k in ("html", "pdf") and _stem(rel) in md_stems)
        ]
        nested = src.meta.get("kind") == FOLDER or len(chosen) > 1
        for rel in chosen:
            label = f"{src.title}/{rel}" if nested else rel
            title = f"{src.title} / {rel}" if nested else src.title
            yield Item(src, rel, kinds[rel], label, title)


def _stem(rel: str) -> str:
    """``rel`` without its extension (``a/report.md`` and ``a/report.pdf`` share one)."""
    return str(Path(rel).with_suffix(""))


def _why_not(item: Item, fmt: str) -> str:
    """The sentence for a file that has no converter into ``fmt``."""
    what = _kind_name(item.kind)
    if item.kind in ("video", "audio"):
        return f"a {what} file cannot be part of a {FORMATS[fmt].label}; {explain(fmt)}"
    if item.kind == "file":
        ext = Path(item.rel).suffix or "this"
        return f"{ext} files are not supported; {explain(fmt)}"
    return f"{what} files cannot be put in a {FORMATS[fmt].label}; {explain(fmt)}"


# -- converters: to Markdown -------------------------------------------------------------


@register("md", "md")
def _md_to_md(item: Item, ctx: Context) -> str:
    return item.text()


@register("text", "md")
def _text_to_md(item: Item, ctx: Context) -> str:
    text = item.text().replace("\r\n", "\n")
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text.rstrip()}\n{fence}"


@register("html", "md", requires=("markdownify",))
def _html_to_md(item: Item, ctx: Context) -> str:
    markdownify = import_lazily("markdownify", what="Converting html to markdown")
    body = _nonempty(item, html_body(item.text(), rewrite_src=lambda src: None))
    return markdownify.markdownify(body, heading_style="ATX").strip()


@register("pdf", "md", requires=("pdfdol", "pypdf"))
def _pdf_to_md(item: Item, ctx: Context) -> str:
    text = "\n\n".join(_pdf_pages(item))
    return re.sub(r"(?m)^([ \t]*)([#>])", r"\1\\\2", text)  # not headings or quotes


def _pdf_pages(item: Item) -> list[str]:
    """The text of each page of a PDF (pdfdol), or a :class:`ConversionError` if it has none."""
    pdfdol = import_lazily("pdfdol", what="Reading a PDF")
    data = _readable_pdf(item)
    try:
        pages = [p.strip() for p in pdfdol.pdf_bytes_to_text_pages(data)]
    except Exception as e:  # pypdf raises its own hierarchy for damaged files
        raise ConversionError(f"could not read its text ({type(e).__name__})") from e
    pages = [p for p in pages if p]
    if len(pages) > MAX_TEXT_PAGES:
        raise ConversionError(
            f"it has {len(pages)} pages, too many to read the text of here "
            "(combine into a PDF instead)"
        )
    if not pages:
        raise ConversionError("it has no text to extract (a scan?)")
    return pages


def _readable_pdf(item: Item) -> bytes:
    """The PDF's bytes, once checked to open (not damaged, not password-protected)."""
    pypdf = import_lazily("pypdf", what="Reading a PDF")
    data = item.data()
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ConversionError("it is password-protected")
        if not len(reader.pages):
            raise ConversionError("it has no pages")
        trial = (
            pypdf.PdfWriter()
        )  # a page tree that cannot be joined fails here, not later
        for page in reader.pages:
            trial.add_page(page)
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"it is damaged or not a PDF ({type(e).__name__})") from e
    return data


# -- converters: to html and to PDF (both are html until the last step) --------------------


def _embed(item: Item, ctx: Context):
    """``rel -> placeholder url`` for the images of ``item``'s html, within the budget."""

    def rewrite(src: str) -> str | None:
        target = resolve_ref(src, rel=item.rel, files=item.source.files)
        if not target or kind_of(target) != "image":
            return None  # an external image is never fetched
        try:
            return ctx.embedder.add_image(
                lambda: item.source.data(target), target, item.source.size(target)
            )
        except (OSError, KeyError):
            return None

    return rewrite


def _md_body(item: Item, ctx: Context) -> str:
    text = item.text()
    if ctx.fmt == "html":
        text = demote_headings(text, HTML_DEMOTE)
    src = item.source
    body, _ = markdown_to_html(
        text,
        rel=item.rel,
        files=list(src.files),
        open_file=src.open_path,
        file_url=src.file_url,
        embedder=ctx.embedder,
        read_bytes=src.read_bytes,
        list_unreferenced=False,  # the document's other files are sections of their own
    )
    return body


def _html_body_of(item: Item, ctx: Context) -> str:
    return _nonempty(
        item,
        html_body(
            item.text(),
            rewrite_src=_embed(item, ctx),
            demote=HTML_DEMOTE if ctx.fmt == "html" else 0,
        ),
    )


def _nonempty(item: Item, body: str) -> str:
    """``body``, or a :class:`ConversionError` when a page with content came out empty."""
    if not body.strip() and item.size:
        raise ConversionError(
            "nothing in it could be shown (scripts, frames and forms only?)"
        )
    return body


def _text_body(item: Item, ctx: Context) -> str:
    return f"<pre>{html.escape(item.text().rstrip())}</pre>"


def _pdf_body(item: Item, ctx: Context) -> str:
    pages = _pdf_pages(item)
    return "".join(
        f'<section class="pdf-page"><p class="media-link">Page {n}</p>'
        f"<pre>{html.escape(p)}</pre></section>"
        for n, p in enumerate(pages, 1)
    )


def _image_body(item: Item, ctx: Context) -> str:
    key = ctx.embedder.add_image(item.data, item.rel, item.size)
    if key is None:
        raise ConversionError("it is too large to embed")
    return f'<figure><img src="{key}" alt="{html.escape(item.rel)}"><figcaption>{html.escape(item.rel)}</figcaption></figure>'


_BODIES: dict[str, tuple[Callable[[Item, Context], str], tuple[str, ...]]] = {
    "md": (_md_body, ("markdown_it",)),
    "html": (_html_body_of, ()),
    "text": (_text_body, ()),
    "pdf": (_pdf_body, ("pdfdol", "pypdf")),
    "image": (_image_body, ()),
}
for _kind, (_body, _req) in _BODIES.items():
    register(_kind, "html", requires=_req)(_body)


def _page_to_pdf(body_of: Callable[[Item, Context], str]) -> Converter:
    """A converter that makes the item's html and prints it: its own pages, titled."""

    def convert(item: Item, ctx: Context) -> bytes:
        if item.kind in ("md", "html", "text") and item.size > PDF_MAX_TEXT_BYTES:
            raise ConversionError("it is too large to make a PDF of")
        body = body_of(item, ctx)
        created = str(item.source.meta.get("created") or "")
        return html_to_pdf(page_html(item.title, body, created=created), ctx.embedder)

    return convert


for _kind in ("md", "html", "text", "image"):
    _body, _req = _BODIES[_kind]
    register(_kind, "pdf", requires=(*_req, "weasyprint"))(_page_to_pdf(_body))


@register("pdf", "pdf", requires=("pypdf", "pdfdol"))
def _pdf_to_pdf(item: Item, ctx: Context) -> bytes:
    return _readable_pdf(item)


# -- html: keep the words and structure, drop everything that runs or loads ---------------

_ALLOWED_TAGS = frozenset(
    "a abbr article aside b blockquote br caption cite code dd del details div dl dt em "
    "figcaption figure footer h1 h2 h3 h4 h5 h6 header hr i img ins kbd li main mark nav "
    "ol p pre q s section small span strong sub summary sup table tbody td tfoot th thead "
    "time tr u ul".split()
)
_VOID_TAGS = frozenset(
    "br hr img embed frame input source track wbr area col link meta base param".split()
)
#: an element dropped with everything inside it
_DROPPED_TAGS = frozenset(
    "script style head title noscript template iframe object embed svg math "
    "canvas audio video applet frame frameset".split()
)
_SAFE_LINK_SCHEMES = ("http", "https", "mailto")
_KEEP_ATTRS = {
    "a": ("href", "title"),
    "img": ("alt", "title"),
    "td": ("colspan", "rowspan"),
    "th": ("colspan", "rowspan"),
}


def html_body(
    text: str,
    *,
    rewrite_src: Callable[[str], str | None] = lambda src: None,
    demote: int = 0,
) -> str:
    """The content of an html page as a safe fragment: its structure and words, nothing live.

    Only a fixed set of tags survives, with a few plain attributes: no script, style, frame,
    form, event handler, ``class`` or ``id``; a link keeps only an ``http(s)`` or ``mailto``
    address. ``rewrite_src(src)`` decides each image: the url to show it from, or ``None``
    for its alt text instead (an image is never loaded from where the page says). ``demote``
    pushes headings that many levels down. Unbalanced tags are closed, so a fragment can
    never swallow what is joined after it.

    >>> html_body('<body><script>x()</script><h1 onclick="x()">Hi</h1><a href="javascript:x()">y</a></body>')
    '<h1>Hi</h1><a>y</a>'
    """
    from html.parser import HTMLParser

    out: list[str] = []
    open_tags: list[str] = []
    skip: list[str] = []  # the dropped elements we are inside

    class Cleaner(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "body" and skip and skip[0] in ("head", "title"):
                skip.clear()  # </head> or </title> was left out: the body starts here
            if skip:
                if tag == skip[-1]:
                    skip.append(tag)
                return
            if tag in _DROPPED_TAGS:
                if tag not in _VOID_TAGS:
                    skip.append(tag)
                return
            if tag not in _ALLOWED_TAGS or len(open_tags) >= MAX_HTML_DEPTH:
                return  # unwrapped: its content stays
            name = tag
            m = re.fullmatch(r"h([1-6])", tag)
            if m and demote:
                name = f"h{min(6, int(m.group(1)) + demote)}"
            kept = dict(attrs)
            parts = [name]
            for attr in _KEEP_ATTRS.get(tag, ()):
                value = kept.get(attr)
                if attr == "href":
                    if (
                        not value
                        or urlsplit(value.strip()).scheme not in _SAFE_LINK_SCHEMES
                    ):
                        continue
                if attr in ("colspan", "rowspan"):
                    if not (value or "").strip().isdigit():
                        continue
                    value = str(min(int(value.strip()), MAX_SPAN))
                if value is not None:
                    parts.append(f'{attr}="{html.escape(value, quote=True)}"')
            if tag == "img":
                shown = rewrite_src(kept.get("src") or "")
                if shown is None:
                    out.append(html.escape(kept.get("alt") or ""))
                    return
                parts.append(f'src="{html.escape(shown, quote=True)}"')
            out.append(f"<{' '.join(parts)}>")
            if tag not in _VOID_TAGS:
                open_tags.append(name)

        def handle_endtag(self, tag):
            if skip:
                if tag == skip[-1]:
                    skip.pop()
                return
            name = tag
            m = re.fullmatch(r"h([1-6])", tag)
            if m and demote:
                name = f"h{min(6, int(m.group(1)) + demote)}"
            if tag in _ALLOWED_TAGS and tag not in _VOID_TAGS and name in open_tags:
                while open_tags:
                    top = open_tags.pop()
                    out.append(f"</{top}>")
                    if top == name:
                        break

        def handle_data(self, data):
            if not skip:
                out.append(html.escape(data, quote=False))

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if tag not in _VOID_TAGS:
                self.handle_endtag(tag)

    cleaner = Cleaner(convert_charrefs=True)
    cleaner.feed(text)
    cleaner.close()
    while open_tags:
        out.append(f"</{open_tags.pop()}>")
    return "".join(out).strip()


# -- joiners and formats ------------------------------------------------------------------

HTML_CSS = """
:root { color-scheme: light dark; }
body { font: 16px/1.55 system-ui, sans-serif; max-width: 46rem; margin: 0 auto; padding: 1rem 16px 4rem; }
nav ol { padding-left: 1.2rem; } section { margin-top: 2.5rem; }
img { max-width: 100%; height: auto; } pre { white-space: pre-wrap; overflow-wrap: anywhere; background: rgba(127,127,127,.15); padding: .6rem; border-radius: 4px; }
table { border-collapse: collapse; } th, td { border: 1px solid rgba(127,127,127,.5); padding: .25rem .5rem; }
blockquote { margin-left: 0; padding-left: 1rem; border-left: 3px solid rgba(127,127,127,.5); }
.media-link { display: block; margin: .5rem 0; padding: .4rem .6rem; border: 1px solid rgba(127,127,127,.5); border-radius: 4px; overflow-wrap: anywhere; }
"""
#: what a combined html page may do: show itself, with its own styles and embedded images
HTML_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"

Join = Callable[[list[tuple[Item, Part]], "Job"], bytes]


@dataclass(frozen=True)
class Job:
    """What a joiner needs besides the parts."""

    title: str
    demote: int
    embedder: Embedder
    toc: bool = True
    unwrap: bool = True


@dataclass(frozen=True)
class Format:
    """An output format: how it is named, joined, and whether each file gets its own context."""

    name: str
    label: str
    ext: str
    media_type: str
    join: Join
    requires: tuple[str, ...] = ()
    #: one context (images, budget) per file rather than one for the whole output
    context_per_item: bool = False


def _join_md(parts, job: Job) -> bytes:
    pairs = [(item.label, part) for item, part in parts]
    text = aggregate_markdown(
        pairs,
        title=job.title,
        order=None,
        demote=job.demote,
        toc=job.toc,
        unwrap=job.unwrap,
    )
    return text.encode("utf-8")


def _join_html(parts, job: Job) -> bytes:
    labels = [label for label, _ in unique_paths([(i.label, "") for i, _ in parts])]
    toc = "".join(
        f'<li><a href="#s{n}">{html.escape(label)}</a></li>'
        for n, label in enumerate(labels, 1)
    )
    sections = "".join(
        f'<section id="s{n}"><h2>{html.escape(label)}</h2>{part}</section>'
        for n, (label, (_, part)) in enumerate(zip(labels, parts), 1)
    )
    title = html.escape(job.title)
    page = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{HTML_CSP}">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>{HTML_CSS}</style></head><body>"
        f"<h1>{title}</h1><nav><h2>Contents</h2><ol>{toc}</ol></nav>{sections}</body></html>"
    )
    return inline_embedded(page, job.embedder).encode("utf-8")


def _join_pdf(parts, job: Job) -> bytes:
    tools = import_lazily("pdfdol.tools", what="Joining PDFs")
    readers = [tools.bytes_to_pdf_reader_obj(part) for _, part in parts]
    writer = tools.concat_pdf_readers(readers)  # every page, in order
    labels = [label for label, _ in unique_paths([(i.label, "") for i, _ in parts])]
    first = 0
    for label, reader in zip(labels, readers):
        writer.add_outline_item(label, first)  # a bookmark at each file's first page
        first += len(reader.pages)
    writer.add_metadata({"/Title": job.title})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


FORMATS: dict[str, Format] = {
    "md": Format("md", "Markdown file", "md", "text/markdown; charset=utf-8", _join_md),
    "html": Format("html", "web page", "html", "text/html; charset=utf-8", _join_html),
    "pdf": Format(
        "pdf",
        "PDF",
        "pdf",
        "application/pdf",
        _join_pdf,
        requires=("pdfdol", "pypdf"),
        context_per_item=True,
    ),
}


# -- the entry point -----------------------------------------------------------------------


def combine(
    sources: Iterable[Source],
    fmt: str = "md",
    *,
    title: str = "",
    demote: int = 1,
    toc: bool = True,
    unwrap: bool = True,
    order: Callable[[Sequence[str]], Sequence[str]] | None = numbered_first,
    max_text_bytes: int | None = MAX_AGGREGATE_BYTES,
    max_input_bytes: int | None = MAX_COMBINE_BYTES,
    registry: Mapping[tuple[str, str], Pair] | None = None,
) -> Combined:
    """Every usable file of ``sources`` as one ``fmt`` ("md", "html" or "pdf") file.

    ``sources`` are the documents (:class:`Source`), in their order; files are arranged by
    ``order`` (:func:`annals.aggregate.numbered_first`: numbered names first, numerically;
    ``None`` keeps the documents' order). ``demote`` is how far an embedded markdown file's
    headings go down in a markdown output, which also takes ``toc`` (a table of contents)
    and ``unwrap`` (join hard-wrapped lines). ``max_text_bytes`` caps all the text read
    (:class:`annals.aggregate.TooLarge`), ``max_input_bytes`` all the files together.

    A file with no converter, or that cannot be read, is left out and listed in
    ``Combined.skipped`` with the reason. Raises :class:`NothingToCombine` when nothing is
    left, :class:`annals.requirements.MissingDependency` when a library the conversions need
    is not installed (before any work), and ``ValueError`` for an unknown ``fmt``.
    """
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}, not {fmt!r}")
    spec = FORMATS[fmt]
    registry = REGISTRY if registry is None else registry
    items = list(items_of(sources, fmt))
    if order and items:
        rank = {label: i for i, label in enumerate(order([i.label for i in items]))}
        items.sort(key=lambda it: rank.get(it.label, len(rank)))

    skipped: list[Skipped] = []
    todo: list[tuple[Item, Pair]] = []
    for item in items:
        pair = registry.get((item.kind, fmt))
        if pair is None:
            skipped.append(Skipped(item.label, _why_not(item, fmt)))
        elif item.kind in ("text", "html") and item.size > MAX_TEXT_FILE_BYTES:
            skipped.append(Skipped(item.label, "it is too large to put in"))
        else:
            todo.append((item, pair))
    if not todo:
        raise NothingToCombine(_nothing_message(fmt, items))
    what = f"Combining into a {spec.label}"
    check_requirements(
        *spec.requires, what=what
    )  # the format's own needs: before any work
    usable: list[tuple[Item, Pair]] = []
    first_missing: MissingDependency | None = None
    for (
        item,
        pair,
    ) in todo:  # a kind whose library is absent is left out, not fatal to all
        missing = requirements.missing_modules(pair.requires)
        if missing:
            first_missing = first_missing or MissingDependency(missing, what=what)
            skipped.append(Skipped(item.label, str(first_missing).replace("\n", " ")))
        else:
            usable.append((item, pair))
    if not usable:
        raise first_missing  # type: ignore[misc]
    todo = usable
    _check_sizes(
        todo,
        fmt=fmt,
        max_text_bytes=max_text_bytes,
        max_input_bytes=max_input_bytes,
    )

    shared = Context(fmt)
    parts: list[tuple[Item, Part]] = []
    for item, pair in todo:
        ctx = Context(fmt) if spec.context_per_item else shared
        try:
            parts.append((item, pair.fn(item, ctx)))
        except MissingDependency:
            raise
        except (
            Exception
        ) as e:  # one bad file (even RecursionError) must not sink the rest
            skipped.append(Skipped(item.label, _reason(e)))
    if not parts:
        raise NothingToCombine(
            "None of the files could be put in a "
            f"{spec.label}: " + "; ".join(f"{s.label}: {s.reason}" for s in skipped[:3])
        )
    data = spec.join(
        parts,
        Job(
            title=title, demote=demote, embedder=shared.embedder, toc=toc, unwrap=unwrap
        ),
    )
    return Combined(
        data=data,
        fmt=fmt,
        media_type=spec.media_type,
        ext=spec.ext,
        sections=len(parts),
        skipped=tuple(skipped),
    )


def _reason(e: BaseException) -> str:
    if isinstance(e, (KeyError, OSError)):
        return "the file could not be read"
    if isinstance(e, ValueError) and str(
        e
    ):  # ConversionError and friends: already worded
        return str(e)
    return f"it could not be converted ({type(e).__name__})"


def _check_sizes(todo, *, fmt, max_text_bytes, max_input_bytes) -> None:
    rendered = sum(1 for i, _ in todo if i.kind != "pdf")
    if fmt == "pdf" and rendered > MAX_RENDERED_FILES:
        raise TooLarge(f"more than {MAX_RENDERED_FILES} files to make PDF pages of")
    text = sum(i.size for i, _ in todo if i.kind in ("md", "html", "text"))
    if max_text_bytes is not None and text > max_text_bytes:
        raise TooLarge(f"more than {max_text_bytes} bytes of text to combine")
    total = sum(i.size for i, _ in todo)
    if max_input_bytes is not None and total > max_input_bytes:
        raise TooLarge(f"more than {max_input_bytes} bytes of files to combine")


def _nothing_message(fmt: str, items: Sequence[Item]) -> str:
    spec = FORMATS[fmt]
    if not items:
        return f"nothing to combine: the documents hold no files. {explain(fmt)}."
    found = sorted({_kind_name(i.kind) for i in items})
    return (
        f"no {_kind_name(kinds_for(fmt)[0])} or other usable files to combine into a "
        f"{spec.label}: these documents hold only {', '.join(found)} files. "
        f"{explain(fmt)}."
    )


def skipped_header(skipped: Sequence[Skipped]) -> str:
    """The skipped files as compact JSON for a response header: few, short, ascii.

    At most :data:`MAX_SKIPPED_LISTED` are listed (the count says how many there were) and
    names and reasons are cut, so the header stays far under what a proxy accepts.
    """

    def cut(text: str, n: int) -> str:
        return text if len(text) <= n else text[: n - 1] + "…"

    listed = [
        {"label": cut(s.label, 40), "reason": cut(s.reason, 80)}
        for s in skipped[:MAX_SKIPPED_LISTED]
    ]
    return json.dumps(
        {"n": len(skipped), "listed": listed}, ensure_ascii=True, separators=(",", ":")
    )


def _demo_source(files: Mapping[str, str]) -> Source:
    """A source of in-memory text files (for the doctest and for tests)."""
    return Source(
        meta={
            "id": "demo",
            "title": "Demo",
            "kind": FOLDER if len(files) > 1 else "md",
        },
        files=list(files),
        read_text=files.__getitem__,
        open_path=lambda rel: (_ for _ in ()).throw(OSError(rel)),
    )
