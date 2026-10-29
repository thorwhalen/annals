"""Many markdown files as ONE markdown document: a title, a table of contents, a section per file.

The mechanism is text in, text out. :func:`aggregate_markdown` takes ``(path, text)`` pairs
and knows nothing of documents, groups or shares; its choices are keyword arguments with
working defaults::

    >>> print(aggregate_markdown(
    ...     {"notes.md": "# Notes\\nOne line\\nwrapped.", "01-intro.md": "Hello."},
    ...     title="Bundle"), end="")
    # Bundle
    <BLANKLINE>
    **Contents**
    <BLANKLINE>
    - [01-intro.md](#01-intromd)
    - [notes.md](#notesmd)
    <BLANKLINE>
    ## 01-intro.md
    <BLANKLINE>
    Hello.
    <BLANKLINE>
    ## notes.md
    <BLANKLINE>
    ## Notes
    One line wrapped.

- ``order``: how the files are arranged; :func:`numbered_first` by default (paths whose
  parts start with a number first, numerically, the rest in the order given), ``None``
  keeps the order given, or any ``paths -> paths`` callable.
- ``demote``: how many levels each file's own headings go down (``1``: a file's ``#``
  becomes ``##``); ``0`` leaves them.
- ``unwrap``: join hard-wrapped lines of a paragraph or list item into one line
  (:func:`unwrap_lines`); code, tables, quotes and html are left as they are.
- ``toc``: the table of contents, as links to the sections' GitHub-style anchors.

:func:`doc_markdown_files` is the bridge from annals documents: it yields the pairs for a
set of documents and the files of each a caller may read, through a ``read`` callable, so
the owner's API, the share server (which reads filtered text) and the CLI share it.
Nothing is stored: the document is made per request.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence

from annals.store import FOLDER, kind_of

Files = Mapping[str, str] | Iterable[tuple[str, str]]
Order = Callable[[Sequence[str]], Sequence[str]]

_NUM_PREFIX = re.compile(r"^(\d+)")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_ATX = re.compile(r"^( {0,3})(#{1,6})(?=[ \t]|$)(.*)$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_LIST_ITEM = re.compile(r"^ *(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
_BREAK = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_TABLE_DELIM = re.compile(
    r"^ *\|?(?: *:?-+:? *\|)+ *:?-*:? *\|? *$|^ *\|? *:?-+:? *\|? *$"
)
_REF_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:")
#: lines that start a block of their own: never joined to the line before, nor it to them
_STRUCTURAL = (_ATX, _SETEXT, _LIST_ITEM, _BREAK, _REF_DEF, _FENCE)
_OPAQUE_STARTS = (">", "|", "<", "$$")


def numbered_first(paths: Sequence[str]) -> list[str]:
    """``paths`` with numbered ones first, compared part by part, the rest in their given order.

    A part (a folder or file name) that starts with digits sorts by that number, before any
    part that does not; parts without a number keep the order they first appeared in, so a
    folder's files stay together.

    >>> numbered_first(["b.md", "10-z.md", "a.md", "2-y.md", "r/02.md", "r/01.md"])
    ['2-y.md', '10-z.md', 'b.md', 'a.md', 'r/01.md', 'r/02.md']
    """
    first_seen: dict[tuple[str, ...], int] = {}
    for p in paths:
        parts = p.split("/")
        for depth in range(1, len(parts) + 1):
            first_seen.setdefault(tuple(parts[:depth]), len(first_seen))

    def key(i_path: tuple[int, str]) -> tuple:
        i, path = i_path
        parts = path.split("/")
        k = []
        for depth, part in enumerate(parts):
            m = _NUM_PREFIX.match(part)
            if m:
                k.append((0, int(m.group(1)), part.lower()))
            else:
                k.append((1, first_seen[tuple(parts[: depth + 1])], ""))
        return (k, i)

    return [p for _, p in sorted(enumerate(paths), key=key)]


def _fenced(lines: Sequence[str]) -> list[bool]:
    """For each line, whether it is inside (or delimits) a fenced code block."""
    out, fence = [], None
    for line in lines:
        m = _FENCE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
            out.append(fence is not None)
        else:
            out.append(True)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                if not line.strip()[len(m.group(1)) :].strip():
                    fence = None
    return out


def _is_plain(line: str) -> bool:
    """A line of ordinary paragraph text (not blank, not the start of another block)."""
    s = line.lstrip()
    if not s or s.startswith(_OPAQUE_STARTS):
        return False
    return not any(rx.match(line) for rx in _STRUCTURAL)


def strip_front_matter(text: str) -> str:
    """``text`` without a leading YAML front-matter block (``---`` ... ``---``).

    >>> strip_front_matter("---\\ntitle: x\\n---\\n# Body")
    '# Body'
    """
    if not text.startswith("---\n"):
        return text
    end = re.search(r"^(?:---|\.\.\.)[ \t]*$\n?", text[4:], flags=re.M)
    return text[4 + end.end() :].lstrip("\n") if end else text


def demote_headings(text: str, levels: int = 1, *, max_level: int = 6) -> str:
    """``text`` with every heading ``levels`` deeper (at most ``max_level``); code untouched.

    Setext headings (a line underlined with ``===`` or ``---``) become ``#`` headings.

    >>> print(demote_headings("# A\\nB\\n---\\n```\\n# code\\n```"))
    ## A
    ### B
    ```
    # code
    ```
    """
    if levels <= 0:
        return text
    lines = text.split("\n")
    fenced = _fenced(lines)
    out: list[str] = []
    for i, line in enumerate(lines):
        if fenced[i]:
            out.append(line)
            continue
        m = _ATX.match(line)
        if m:
            level = min(max_level, len(m.group(2)) + levels)
            out.append(f"{m.group(1)}{'#' * level}{m.group(3)}")
            continue
        s = _SETEXT.match(line)
        prev_ok = out and i and not fenced[i - 1] and _is_plain(lines[i - 1])
        before_ok = i < 2 or not lines[i - 2].strip() or bool(_ATX.match(lines[i - 2]))
        if s and prev_ok and before_ok:
            level = min(max_level, (1 if s.group(1)[0] == "=" else 2) + levels)
            out[-1] = f"{'#' * level} {lines[i - 1].strip()}"
            continue
        out.append(line)
    return "\n".join(out)


def unwrap_lines(text: str) -> str:
    """``text`` with hard-wrapped paragraphs and list items joined into one line each.

    Only ordinary text lines are joined: headings, list markers, quotes, tables, html,
    fenced or indented code, and a line ending in a hard break (two spaces or ``\\``)
    keep their line breaks.

    >>> print(unwrap_lines("A long\\nsentence.\\n\\n- item\\n  goes on\\n- next\\n\\n    code\\n    more"))
    A long sentence.
    <BLANKLINE>
    - item goes on
    - next
    <BLANKLINE>
        code
        more
    """
    lines = text.split("\n")
    fenced = _fenced(lines)
    table_heads = {
        i
        for i in range(len(lines) - 1)
        if "|" in lines[i] and _TABLE_DELIM.match(lines[i + 1])
    }
    out: list[str] = []
    prev = "blank"  # what the last line was: blank, para, list, code, other
    in_list = False
    for i, line in enumerate(lines):
        if fenced[i]:
            out.append(line)
            prev = "other"
            continue
        if not line.strip():
            out.append(line)
            prev = "blank"
            continue
        indent = len(line) - len(line.lstrip(" "))
        if i in table_heads or _TABLE_DELIM.match(line) and "|" in line:
            kind = "other"
        elif _LIST_ITEM.match(line):
            kind, in_list = "list", True
        elif not _is_plain(line):
            kind = "other"
        elif indent >= 4 and prev in ("blank", "code", "other") and not in_list:
            kind = "code"
        else:
            hard_break = out and (out[-1].endswith("  ") or out[-1].endswith("\\"))
            if prev in ("para", "list") and not hard_break:
                out[-1] = f"{out[-1].rstrip()} {line.strip()}"
                continue
            if prev == "blank" and in_list and indent == 0:
                in_list = False
            kind = "list" if in_list and indent else "para"
        out.append(line)
        prev = kind
    return "\n".join(out)


def heading_anchor(text: str, seen: dict[str, int] | None = None) -> str:
    """The id GitHub (and most renderers) give a heading; ``seen`` numbers repeats.

    >>> seen = {}
    >>> heading_anchor("01-intro.md", seen), heading_anchor("01-intro.md", seen)
    ('01-intromd', '01-intromd-1')
    """
    slug = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    if seen is None:
        return slug
    n = seen.get(slug, 0)
    seen[slug] = n + 1
    return slug if n == 0 else f"{slug}-{n}"


def _unique(pairs: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """The pairs with repeated paths told apart: ``a.md``, ``a.md (2)``."""
    count: dict[str, int] = {}
    out = []
    for path, text in pairs:
        count[path] = count.get(path, 0) + 1
        out.append((path if count[path] == 1 else f"{path} ({count[path]})", text))
    return out


def aggregate_markdown(
    files: Files,
    *,
    title: str = "",
    order: Order | None = numbered_first,
    demote: int = 1,
    unwrap: bool = True,
    toc: bool = True,
    section_level: int = 2,
) -> str:
    """One markdown document of ``files`` (``{path: text}`` or ``(path, text)`` pairs).

    A ``# title``, a table of contents, then one section per file, headed by its path,
    with the file's text below (front matter dropped, headings ``demote``-d, lines
    unwrapped); see the module docstring for each choice.
    """
    pairs = _unique(list(files.items() if isinstance(files, Mapping) else files))
    texts = dict(pairs)
    paths = list(order([p for p, _ in pairs]) if order else texts)
    seen: dict[str, int] = {}
    head = "#" * section_level
    parts: list[str] = [f"# {title}"] if title else []
    if title:
        heading_anchor(title, seen)
    anchors = [heading_anchor(p, seen) for p in paths]
    if toc and paths:
        parts.append(
            "**Contents**\n\n"
            + "\n".join(f"- [{p}](#{a})" for p, a in zip(paths, anchors))
        )
    for path in paths:
        body = strip_front_matter(texts[path].replace("\r\n", "\n"))
        body = demote_headings(body, demote)
        if unwrap:
            body = unwrap_lines(body)
        parts.append(f"{head} {path}\n\n{body.strip()}".rstrip())
    return "\n\n".join(parts) + "\n"


class TooLarge(ValueError):
    """The markdown to aggregate is over the size a caller allows."""


def doc_markdown_files(
    docs: Iterable[tuple[dict, Iterable[str]]],
    *,
    read: Callable[[str, str], str],
    max_bytes: int | None = None,
    skip: tuple[type[BaseException], ...] = (KeyError, OSError, ValueError),
) -> Iterator[tuple[str, str]]:
    """``(path, text)`` for every markdown file of ``docs`` (``(meta, files)`` pairs).

    ``files`` are the files of that document the caller may read, and ``read(doc_id,
    rel)`` reads one (the share server passes its filtered reader). A document whose one
    markdown file is its page is named by that file; a folder, or a document with several
    markdown files, by its title then the file (``Report/01-intro.md``). A file ``read``
    cannot read (one of ``skip``) is left out; past ``max_bytes`` in all, :class:`TooLarge`.
    """
    total = 0
    for meta, files in docs:
        mds = [f for f in files if kind_of(f) == "md"]
        nested = meta.get("kind") == FOLDER or len(mds) > 1
        label = (meta.get("title") or meta["id"]).replace("/", "-").strip()
        for rel in mds:
            try:
                text = read(meta["id"], rel)
            except skip:
                continue
            total += len(text.encode("utf-8"))
            if max_bytes is not None and total > max_bytes:
                raise TooLarge(f"more than {max_bytes} bytes of markdown to combine")
            yield (f"{label}/{rel}" if nested else rel), text
