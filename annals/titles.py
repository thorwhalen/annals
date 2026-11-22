"""A title for a file whose name says nothing: ``overview.mp3``, ``output.html``, ``index.md``.

A document is titled by what it says (a ``# heading``, a ``<title>``), else by its file
name. Tools that make media often name every output the same (podpatch and hailing both
write ``<folder>/overview.mp3``), so seven audio overviews were all titled "overview". When
the file name is one of :data:`GENERIC_STEMS`, the title comes from beside the file
instead: the ``title`` of a JSON manifest in its folder (:data:`TITLE_FILES`), else the
folder's own name without its date and hash.

>>> is_generic("overview") and is_generic("Final_Output") and not is_generic("theremin")
True
>>> folder_title("20261119-223540-theremin-and-gesture-controlled-7d32")
'theremin and gesture controlled'
"""

import json
import re
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
_STAMP_RE = re.compile(r"^\d{8}(?:[-_T]?\d{4,6})?[-_ ]+")
_HASH_RE = re.compile(r"[-_ ]+(?=[0-9a-f]*\d)[0-9a-f]{4,8}$")  # a digit in it: "cafe" is a word
_MAX_FILE_BYTES = 1 << 20


#: folder names that say nothing either (a title from one would be noise)
UNINFORMATIVE_FOLDERS = frozenset(
    {"tmp", "temp", "downloads", "desktop", "documents", "home", "root", "work", "scratchpad", "overviews"}
)


def is_generic(stem: str, *, generic: frozenset = GENERIC_STEMS | UNINFORMATIVE_FOLDERS) -> bool:
    """Whether a file name (without extension) says nothing about what it holds: one of
    ``generic``, or two of them ("final output", "audio overview")."""
    words = [w for w in re.split(r"[-_\s.]+", stem.strip().lower()) if w]
    return not words or all(w in generic for w in words)


def folder_title(name: str) -> str:
    """A folder's name as a title: date stamp and trailing hash dropped, separators spaced."""
    core = _HASH_RE.sub("", _STAMP_RE.sub("", name.strip()))
    return " ".join(re.split(r"[-_\s]+", core)).strip()


def _manifest_title(folder: Path, *, names=TITLE_FILES) -> str | None:
    for name in names:
        f = folder / name
        try:
            if not f.is_file() or f.stat().st_size > _MAX_FILE_BYTES:
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        title = data.get("title") if isinstance(data, dict) else None
        if isinstance(title, str) and title.strip():
            return title.strip()
    return None


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
    folder = Path(path).expanduser().resolve().parent
    title = _manifest_title(folder) or folder_title(folder.name)
    return title if title and not is_generic(title) else None
