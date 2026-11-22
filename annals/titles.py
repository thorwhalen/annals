"""A title for a file whose name says nothing: ``overview.mp3``, ``output.html``, ``index.md``.

A document is titled by what it says (a ``# heading``, a ``<title>``), else by its file
name. Tools that make media often name every output the same (podpatch and hailing both
write ``<folder>/overview.mp3``), so seven audio overviews were all titled "overview". When
the file name is one of :data:`GENERIC_STEMS`, the title comes from beside the file
instead: the ``title`` of a JSON manifest in its folder (:data:`TITLE_FILES`), else the
folder's own name without its date and hash, but only when the folder was made by a tool
(its name carries a date stamp or a short hash): a person's folder (their home, a repo, a
client's) never names a document, since a title shows wherever the document is shared.

>>> is_generic("overview") and is_generic("Final_Output") and not is_generic("theremin")
True
>>> folder_title("20261119-223540-theremin-and-gesture-controlled-7d32")
'theremin and gesture controlled'
"""

import json
import re
import unicodedata
from pathlib import Path

#: file names (without extension) that never title a document on their own
GENERIC_STEMS = frozenset(
    {
        "overview", "audio", "video", "output", "out", "result", "final", "render",
        "recording", "untitled", "index", "main", "page", "report", "document", "file",
        "player", "track", "take", "export", "speech", "voice", "narration", "summary",
    }
)  # fmt: skip
#: files a maker writes beside its output whose ``title`` names it, tried in order
TITLE_FILES = ("manifest.json", "meta.json", "script.json", "info.json")
#: a folder name's machine parts: a leading date or time stamp, a trailing short hash
_STAMP_RE = re.compile(
    r"^(?:\d{8}(?:[-_T]?\d{4,6})?|\d{4}-\d{2}-\d{2}(?:[-_T]\d{2}-?\d{2}(?:-?\d{2})?)?)[-_ ]+"
)
_HASH_RE = re.compile(
    r"[-_ ]+(?=[0-9a-f]*\d)[0-9a-f]{4,8}$"
)  # a digit in it: "cafe" is a word
_MAX_FILE_BYTES = 1 << 20
#: the longest title taken from a manifest (a rename allows as much)
MAX_TITLE = 200


#: folder names that say nothing either (a title from one would be noise)
UNINFORMATIVE_FOLDERS = frozenset(
    {
        "tmp",
        "temp",
        "downloads",
        "desktop",
        "documents",
        "home",
        "root",
        "work",
        "scratchpad",
        "overviews",
    }
)


def is_generic(
    stem: str, *, generic: frozenset = GENERIC_STEMS | UNINFORMATIVE_FOLDERS
) -> bool:
    """Whether a file name (without extension) says nothing about what it holds: one of
    ``generic``, or two of them ("final output", "audio overview")."""
    words = [w for w in re.split(r"[-_\s.]+", stem.strip().lower()) if w]
    return not words or all(w in generic for w in words)


def folder_title(name: str) -> str:
    """A tool's output folder's name as a title: date stamp and trailing hash dropped,
    separators spaced; ``""`` for a folder no tool made (no stamp and no hash), or one whose
    words are only digits and hex (a uuid, a temporary folder's name).

    >>> folder_title("2026-11-22-tables-and-session-links"), folder_title("thorwhalen")
    ('tables and session links', '')
    """
    name = name.strip()
    core = _HASH_RE.sub("", _STAMP_RE.sub("", name))
    if core == name:  # not a tool's output folder
        return ""
    words = [w for w in re.split(r"[-_\s]+", core) if w]
    if all(re.fullmatch(r"[0-9a-f]+", w) for w in words):
        return ""
    return " ".join(words)


def _manifest_title(folder: Path, *, names=TITLE_FILES) -> str | None:
    for name in names:
        f = folder / name
        try:
            if not f.is_file() or f.stat().st_size > _MAX_FILE_BYTES:
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        title = _clean(data.get("title") if isinstance(data, dict) else None)
        if title and not is_generic(title):
            return title
    return None


def _clean(title) -> str | None:
    """One line of plain text, as a heading would give: control and format characters
    (bidi overrides) dropped, whitespace collapsed, cut at :data:`MAX_TITLE` characters."""
    if not isinstance(title, str):
        return None
    kept = "".join(
        " " if c.isspace() else c
        for c in title
        if c.isspace() or unicodedata.category(c) not in ("Cc", "Cf")
    )
    kept = " ".join(kept.split())
    return kept[:MAX_TITLE].rstrip() or None


def title_beside(path: Path | str) -> str | None:
    """A title for the file ``path`` from what is beside it (see the module doc), or ``None``
    when its folder says nothing either.

    >>> import tempfile, os
    >>> d = Path(tempfile.mkdtemp()) / "20261119-223540-theremin-7d32"; d.mkdir()
    >>> title_beside(d / "overview.mp3")
    'theremin'
    >>> _ = (d / "manifest.json").write_text('{"title": "The Theremin: Invention, Spies"}')
    >>> title_beside(d / "overview.mp3")
    'The Theremin: Invention, Spies'
    """
    folder = (
        Path(path).expanduser().absolute().parent
    )  # a symlink's own folder, not its target's
    for title in (_manifest_title(folder), folder_title(folder.name)):
        if title and not is_generic(title):
            return title
    return None
