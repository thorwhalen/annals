"""The references of documents, extracted and combined, in three forms.

A document's references are the body of its references section: a markdown heading named
"References", "Sources", "Bibliography", "Works cited" or "Citations" (any level, any case),
down to the next heading of the same or a higher level. Three forms, each text in, text out:

- ``grouped`` (the default): one ``###`` section per document holding its references as
  they are, under ``## References for <title>``;
- ``deduped``: every entry once, its citation number removed, as one bulleted list;
- ``urls``: every web address once, one per line and nothing else, the form a notebook
  (Gemini Notebook, formerly NotebookLM) accepts as pasted website sources.

>>> doc = '''# Bees
... Text [1].
... ## REFERENCES
... 1. [Hive life](https://bees.org/hive). 2024.
... [2] Smith J. Pollen, <https://pollen.net/a>
... ## Appendix
... not a reference https://no.org
... '''
>>> reference_sections(doc)
['1. [Hive life](https://bees.org/hive). 2024.\\n[2] Smith J. Pollen, <https://pollen.net/a>']
>>> [strip_citation_number(e) for e in reference_entries(reference_sections(doc)[0])]
['[Hive life](https://bees.org/hive). 2024.', 'Smith J. Pollen, <https://pollen.net/a>']
>>> print(combine_references([("Bees", [doc]), ("Wasps", ["no references here"])],
...                          title="Insects", form="urls"), end="")
https://bees.org/hive
https://pollen.net/a

The mechanism knows nothing of the store: :func:`doc_reference_texts` is the bridge that
reads a set of documents through a ``read(doc_id, rel)`` callable, so the owner's API and,
later, a share can use it alike.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Iterator, Sequence

from annals.aggregate import numbered_first
from annals.store import kind_of

FORMS = ("grouped", "deduped", "urls")
DFLT_FORM = "grouped"
#: section names that hold references (a heading's text starts with one of them)
REFERENCE_HEADINGS = (
    "references",
    "sources",
    "bibliography",
    "works cited",
    "citations",
)

_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
#: the start of an entry: "1." "1)" "[1]" "- " "* " "+ "
_ENTRY_RE = re.compile(r"^ {0,3}(?:\d{1,4}[.)]|\[\d{1,4}\]|[-*+])\s+")
_NUMBER_RE = re.compile(r"^\s*(?:\d{1,4}[.)]|\[\d{1,4}\]|[-*+])\s+")
#: a markdown link's target, allowing one level of parentheses in it (wikipedia)
_MD_LINK_RE = re.compile(
    r"\]\(\s*<?(https?://(?:[^()\s<>]|\([^()\s]*\))+)>?(?:\s+\"[^\"]*\")?\s*\)", re.I
)
_AUTOLINK_RE = re.compile(r"<(https?://[^\s<>]+)>", re.I)
_BARE_URL_RE = re.compile(r"https?://[^\s<>\[\]\"'`]+", re.I)
_TRAILING = ".,;:!?)]}'\"*_"


def _is_reference_heading(text: str) -> bool:
    name = re.sub(r"[*_`:]", "", text).strip().lower()
    return any(name == h or name.startswith(h + " ") for h in REFERENCE_HEADINGS)


def reference_sections(text: str) -> list[str]:
    """The body of each references section of a markdown text, as written (blank edges trimmed)."""
    sections, current, level, fence = [], None, 0, None
    for line in text.splitlines():
        if fence:
            fence = None if line.strip().startswith(fence) else fence
            if current is not None:
                current.append(line)
            continue
        if m := _FENCE_RE.match(line):
            fence = m.group(1)[:3]
        elif m := _HEADING_RE.match(line):
            depth = len(m.group(1))
            if current is not None and depth <= level:
                sections.append(current)
                current = None
            if current is None and _is_reference_heading(m.group(2)):
                current, level = [], depth
                continue
        if current is not None:
            current.append(line)
    if current is not None:
        sections.append(current)
    return [
        body for body in ("\n".join(s).strip("\n") for s in sections) if body.strip()
    ]


def reference_entries(section: str) -> list[str]:
    """The entries of a references section: each numbered or bulleted item, with its wrapped lines.

    Prose that is not an item (an "Accessed on ..." note) is not an entry. A section with no
    list markers at all is one entry per non-blank line.
    """
    lines = section.splitlines()
    if not any(_ENTRY_RE.match(ln) for ln in lines):
        return [ln.strip() for ln in lines if ln.strip()]
    entries, current = [], None
    for line in lines:
        if _ENTRY_RE.match(line):
            if current:
                entries.append(current)
            current = line.strip()
        elif current is not None and line.strip():
            current += " " + line.strip()
        elif not line.strip() and current:
            entries.append(current)
            current = None
    if current:
        entries.append(current)
    return entries


def strip_citation_number(entry: str) -> str:
    """``entry`` without its leading number or bullet (``1.``, ``[1]``, ``-``)."""
    return _NUMBER_RE.sub("", entry, count=1).strip()


def urls_of(text: str) -> list[str]:
    """The web addresses in ``text``, in order of appearance, each once as written."""
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for rx in (_MD_LINK_RE, _AUTOLINK_RE):
        for m in rx.finditer(text):
            found.append((m.start(1), m.group(1)))
            taken.append(m.span())
    for m in _BARE_URL_RE.finditer(text):
        if not any(a <= m.start() < b for a, b in taken):
            url = m.group(0).rstrip(_TRAILING)
            if url.count("(") > url.count(")") and m.group(0).endswith(")"):
                url += ")"
            found.append((m.start(), url))
    return _unique(url for _, url in sorted(found))


def url_key(url: str) -> str:
    """What makes two addresses the same page: no fragment, no trailing slash, host in lowercase."""
    url = url.split("#", 1)[0]
    scheme, _, rest = url.partition("://")
    host, slash, path = rest.partition("/")
    return f"{scheme.lower()}://{host.lower()}{slash}{path}".rstrip("/")


def _unique(urls: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for url in urls:
        if (k := url_key(url)) not in seen:
            seen.add(k)
            out.append(url)
    return out


def _entry_key(entry: str) -> str:
    urls = urls_of(entry)
    return url_key(urls[0]) if urls else re.sub(r"\W+", " ", entry).strip().lower()


def combine_references(
    items: Iterable[tuple[str, Sequence[str]]],
    *,
    title: str,
    form: str = DFLT_FORM,
) -> str:
    """``items`` (a title and the texts of its pages) as their references in ``form``.

    Items with no references section are left out. An empty string means none had any.
    """
    if form not in FORMS:
        raise ValueError(f"form must be one of {list(FORMS)}")
    found = [
        (name, [s for t in texts for s in reference_sections(t)])
        for name, texts in items
    ]
    found = [(name, secs) for name, secs in found if secs]
    if not found:
        return ""
    if form == "urls":
        return (
            "\n".join(_unique(u for _, secs in found for s in secs for u in urls_of(s)))
            + "\n"
        )
    if form == "deduped":
        seen, lines = set(), []
        for _, secs in found:
            for entry in (e for s in secs for e in reference_entries(s)):
                if (k := _entry_key(strip_citation_number(entry))) not in seen:
                    seen.add(k)
                    lines.append("- " + strip_citation_number(entry))
        return f"## References for {title}\n\n" + "\n".join(lines) + "\n"
    parts = [f"## References for {title}"]
    for name, secs in found:
        parts.append(f"### {name}")
        parts.extend(secs)
    return "\n\n".join(parts) + "\n"


def doc_reference_texts(
    docs: Iterable[tuple[dict, Iterable[str]]],
    *,
    read: Callable[[str, str], str],
    skip: tuple[type[BaseException], ...] = (KeyError, OSError, ValueError),
) -> Iterator[tuple[str, list[str]]]:
    """``(title, texts)`` for each of ``docs`` (``(meta, files)`` pairs): its markdown pages' text.

    Pages come in :func:`~annals.aggregate.numbered_first` order; a page ``read`` cannot read
    (one of ``skip``) is left out.
    """
    for meta, files in docs:
        texts = []
        for rel in numbered_first([f for f in files if kind_of(f) == "md"]):
            try:
                texts.append(read(meta["id"], rel))
            except skip:
                continue
        yield (meta.get("title") or meta["id"]), texts
