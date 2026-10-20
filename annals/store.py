"""The document store: a flat set of documents, tags, groups and a recycle bin, as plain files.

Layout under the data root (local or remote, see :mod:`annals.target`)::

    docs/<id>/meta.json         one document: metadata
    docs/<id>/<main file>       its content (index.html, report.md, ...), plus any assets
    docs/<id>/.versions/<n>/    an earlier version, whole (its own meta.json and files)
    docs/<id>.r<stamp>-<hex>/   a replacement not applied yet (``publish(replace=<id>)``)
    trash/<id>/...              the same shape; the recycle bin is a move
    groups/<gid>.json           a named, ordered list of document ids with its own URL

Flat on purpose: agents from many corpora do not share a hierarchy, and every placement
decision costs tokens. Tags and groups carry the structure. Ids are time-sortable and
readable (``20261003-203301-starwars-theme-report-3f9a``), so a listing is already in
publication order and a URL says what it points to.

Plain files, written whole, because the same tree is written by rsync from another machine
and read by the server; there is no index to keep consistent.

Living documents (one link that stays current) are a replace: the new files are written as
a *pending* replacement next to the document, never over it, and whoever reads the store
applies it (:meth:`DocStore.settle`): the current files move under ``.versions/<n>/`` and
the replacement takes the id. Writing beside rather than over is what lets a replace travel
through an outbox (a directory another machine pulls and empties): the pending directory is
just another new directory to pull, and the store on the reading side applies it. Applying
is a sequence of renames, each claimed atomically, so two readers never apply the same
replacement twice and nothing is ever deleted.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import shutil
import tempfile
import time
import unicodedata
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from annals.target import LOCK_NOTE, LocalTarget, Target

DOCS = "docs"
TRASH = "trash"
GROUPS = "groups"
META = "meta.json"
MAX_SLUG_LEN = 48
EXCERPT_CHARS = 280
#: how much of a file is read to find its title and excerpt
HEAD_CHARS = 4000
#: names never published from a directory: hidden files, caches, compiled python
DFLT_EXCLUDE = (".*", "__pycache__", "*.pyc", "*.pyo")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
#: where a document keeps its earlier versions (hidden: a published folder's own content
#: skips hidden names, and a document that carries one anyway is refused)
VERSIONS = ".versions"
#: ``<id>@<n>`` names version ``n`` of a document; ``@`` is not an id character
VERSION_SEP = "@"
#: ``<id>.r<stamp>-<hex>`` is a pending replacement of ``<id>``
PENDING_SEP = ".r"
#: ``<root>/.lock-<id>/`` is held while a replacement of ``<id>`` is applied; it is also
#: the working directory, holding ``next`` (the replacement) and ``old`` (the version
#: being archived) between renames, and ``lock.json`` (what a recovery needs to know)
LOCK_PREFIX = ".lock-"
LOCK_INFO = LOCK_NOTE
#: a lock older than this was left by a crash: its work is finished or undone
LOCK_STALE_S = 600
#: a reader that misses a document being swapped waits for it this long, in steps
SWAP_WAIT_S, SWAP_STEP_S = 2.0, 0.02
#: a replacement is written under this hidden name, then renamed into place whole
INCOMING_PREFIX = ".incoming-"
#: names a document's own files may not use: the store's bookkeeping lives there
RESERVED = (VERSIONS,)
#: extension -> kind. ``html`` renders in a frame, ``md`` as markdown, ``text`` as
#: preformatted text, ``image``/``video``/``audio``/``pdf`` inline in the page; anything
#: else is a download. A document of several files with no single page to show is a
#: ``folder``, shown as a gallery and file list.
_EXTS = {
    "md": ".md .markdown",
    "html": ".html .htm",
    "text": ".txt .log .json .jsonl .csv .tsv .toml .yaml .yml .py .js .ts .sh .srt .vtt .xml",
    "image": ".png .jpg .jpeg .gif .webp .avif .svg .bmp",
    "video": ".mp4 .webm .mov .m4v .ogv",
    "audio": ".mp3 .wav .ogg .oga .m4a .aac .flac .opus",
    "pdf": ".pdf",
}
KINDS = {ext: kind for kind, exts in _EXTS.items() for ext in exts.split()}
TEXT_KINDS = frozenset({"md", "text"})
MEDIA_KINDS = frozenset({"image", "video", "audio", "pdf"})
PAGE_KINDS = frozenset({"md", "html"})
FOLDER = "folder"


def now_iso() -> str:
    """UTC timestamp with second precision, the format every meta.json uses."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str, *, max_len: int = MAX_SLUG_LEN) -> str:
    """Lowercase ascii words joined by hyphens; empty input becomes ``doc``."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    slug = "-".join(words)
    if len(slug) > max_len:  # cut at a word boundary, never mid-word
        slug = (
            slug[:max_len].rsplit("-", 1)[0]
            if "-" in slug[:max_len]
            else slug[:max_len]
        )
    return slug.strip("-") or "doc"


def mk_id(title: str, *, when: datetime | None = None) -> str:
    """``YYYYMMDD-HHMMSS-<slug>-<4 hex>``: sortable by time, readable in a URL."""
    when = when or datetime.now(timezone.utc)
    return f"{when.strftime('%Y%m%d-%H%M%S')}-{slugify(title)}-{secrets.token_hex(2)}"


def check_id(doc_id: str) -> str:
    """Raise ``ValueError`` on an id that could not have come from :func:`mk_id`."""
    if not ID_RE.match(doc_id):
        raise ValueError(f"not a document id: {doc_id!r}")
    return doc_id


def split_version(doc_id: str) -> tuple[str, int | None]:
    """``("<id>", n)`` from ``<id>@<n>`` (version ``n``), ``("<id>", None)`` from an id."""
    base, sep, n = doc_id.partition(VERSION_SEP)
    if sep and not (n.isdigit() and int(n) > 0):
        raise ValueError(f"not a document version: {doc_id!r}")
    return check_id(base), int(n) if sep else None


def mk_pending_id(doc_id: str, *, when: datetime | None = None) -> str:
    """``<id>.r<YYYYMMDDHHMMSSffffff>-<hex>``: sorts in publication order."""
    when = when or datetime.now(timezone.utc)
    stamp = when.strftime("%Y%m%d%H%M%S%f")
    return check_id(f"{doc_id}{PENDING_SEP}{stamp}-{secrets.token_hex(3)}")


def _is_pending_of(name, doc_id) -> bool:
    """True when ``name`` is a well-formed pending replacement of ``doc_id``."""
    return (
        isinstance(name, str)
        and bool(ID_RE.match(name))
        and name.rpartition(PENDING_SEP)[0] == doc_id
    )


def kind_of(filename: str) -> str:
    """The rendering kind of a file, from its extension."""
    return KINDS.get(Path(filename).suffix.lower(), "file")


def title_and_excerpt(head: str, kind: str) -> tuple[str | None, str]:
    """A title (markdown ``# h1`` or html ``<title>``) and a plain-text excerpt of ``head``."""
    title = None
    if kind == "md":
        m = re.search(r"^#\s+(.+?)\s*$", head, re.M)
        title = m.group(1).strip() if m else None
    elif kind == "html":
        m = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    if kind not in TEXT_KINDS:
        return title, ""
    text = re.sub(r"^#+\s.*$", "", head, flags=re.M)  # drop headings
    text = re.sub(r"[`*_>\[\]()#|]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return title, text[:EXCERPT_CHARS]


def _head(path: Path) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(HEAD_CHARS)
    except OSError:
        return ""


def _title_from_content(path: Path, kind: str) -> str | None:
    return title_and_excerpt(_head(path), kind)[0] if kind in ("md", "html") else None


def _excerpt(path: Path, kind: str) -> str:
    return title_and_excerpt(_head(path), kind)[1] if kind in TEXT_KINDS else ""


def _pick_main(files: list[Path]) -> tuple[Path, str]:
    """The file a viewer opens first, and the document's kind.

    ``index.html`` wins; else the only page (markdown or html) among the files, with the
    rest as its assets; else the file itself when there is one. Anything else (a folder of
    renders, several pages, mixed media) is a ``folder``: shown as a gallery and file list,
    with the first file as ``main``.
    """
    for f in files:
        if f.name.lower() in ("index.html", "index.htm"):
            return f, "html"
    pages = [f for f in files if kind_of(f.name) in PAGE_KINDS]
    if len(pages) == 1:
        return pages[0], kind_of(pages[0].name)
    if len(files) == 1:
        return files[0], kind_of(files[0].name)
    return files[0], FOLDER


def _folder_summary(files: list[str]) -> str:
    """``12 images, 3 audio, 1 md`` for a folder document's excerpt."""
    counts: dict[str, int] = {}
    for f in files:
        counts[kind_of(f)] = counts.get(kind_of(f), 0) + 1
    plural = {"image": "images", "video": "videos", "file": "files", "pdf": "pdfs"}
    order = ["image", "video", "audio", "pdf", "html", "md", "text", "file"]
    return ", ".join(
        f"{counts[k]} {plural.get(k, k) if counts[k] > 1 else k}"
        for k in order
        if k in counts
    )


def _stage(
    sources: list[Path], tmp: Path, *, exclude: Iterable[str] = DFLT_EXCLUDE
) -> tuple[Path, str, list[str]]:
    """Copy the sources into ``tmp`` and return (main file, kind, relative file list).

    Inside a directory, names matching ``exclude`` (glob patterns) are skipped; a file
    named explicitly is always published.
    """
    ignore = shutil.ignore_patterns(*exclude) if exclude else None
    if len(sources) == 1 and sources[0].is_dir():
        shutil.copytree(sources[0], tmp, dirs_exist_ok=True, ignore=ignore)
    else:
        for src in sources:
            if src.is_dir():
                shutil.copytree(src, tmp / src.name, dirs_exist_ok=True, ignore=ignore)
            else:
                shutil.copy2(src, tmp / src.name)
    files = sorted(p for p in tmp.rglob("*") if p.is_file() and p.name != META)
    if not files:
        raise ValueError("nothing to publish: no files found")
    reserved = [p for p in tmp.iterdir() if p.name in RESERVED]
    if reserved:
        raise ValueError(
            f"a document may not contain {reserved[0].name!r}: annals keeps versions there"
        )
    main, kind = _pick_main(files)
    return main, kind, [str(p.relative_to(tmp)) for p in files]


class DocStore:
    """Publish, list, read, trash, restore and group documents on a :class:`Target`."""

    def __init__(self, target: Target | Path | str, *, settle: bool = True):
        """``settle``: apply pending replacements when reading (see :meth:`settle`).

        False for an outbox, a directory another machine pulls and empties: the
        replacements must travel as they are and be applied where they land.
        """
        self.target: Target = (
            target if hasattr(target, "put_tree") else LocalTarget(target)  # type: ignore[arg-type]
        )
        self.auto_settle = settle

    # -- publishing -------------------------------------------------------------------

    def publish(
        self,
        *sources: Path | str,
        title: str | None = None,
        tags: Iterable[str] = (),
        source: dict | None = None,
        text: str | None = None,
        filename: str = "document.md",
        exclude: Iterable[str] = DFLT_EXCLUDE,
        replace: str | None = None,
    ) -> dict:
        """Publish files (or a directory, or ``text``) as ONE document; return its meta.

        One markdown or html file is the common case. A directory is published whole, with
        ``index.html`` (or the first renderable file) as the page shown. ``text`` publishes a
        string as ``filename`` instead of reading sources. ``exclude`` lists glob patterns
        skipped inside a directory (hidden files and caches by default; ``()`` keeps all).

        ``replace`` (a document id) publishes a new version of that document instead of a
        new document: same id, same link, the current files kept as a version. It is
        written as a pending replacement and applied at once when this store settles
        (otherwise where the store is read). The returned meta says ``pending`` until then.
        """
        if replace is not None:
            check_id(replace)
            if PENDING_SEP in replace and self._root_of(replace) is None:
                raise ValueError(f"{replace} is a pending replacement, not a document")
            if self.auto_settle and self._root_of(replace) is None:
                raise KeyError(f"no document {replace} to replace")
        with tempfile.TemporaryDirectory(prefix="annals-") as td:
            tmp = Path(td) / "doc"
            tmp.mkdir()
            if text is not None:
                (tmp / filename).write_text(text, encoding="utf-8")
                main, files = tmp / filename, [filename]
                kind = kind_of(filename)
            else:
                paths = [Path(s).expanduser() for s in sources]
                missing = [str(p) for p in paths if not p.exists()]
                if missing:
                    raise FileNotFoundError(", ".join(missing))
                main, kind, files = _stage(paths, tmp, exclude=exclude)
            default_title = (
                paths[0].name if kind == FOLDER and text is None else main.stem
            )
            title = (
                title
                or _title_from_content(main, kind)
                or default_title.replace("_", " ")
            )
            sizes = {f: (tmp / f).stat().st_size for f in files}
            doc_id = replace or mk_id(title)
            meta = {
                "id": doc_id,
                "title": title,
                "kind": kind,
                "main": str(main.relative_to(tmp)),
                "files": files,
                "tags": sorted({t.strip() for t in tags if t and t.strip()}),
                "source": source or {},
                "created": now_iso(),
                "size": sum(sizes.values()),
                "sizes": sizes,
                "excerpt": _folder_summary(files)
                if kind == FOLDER
                else _excerpt(main, kind),
            }
            if replace is not None:
                meta.update(replaces=replace, pending_id=mk_pending_id(replace))
            (tmp / META).write_text(json.dumps(meta, indent=1), encoding="utf-8")
            if replace is None:
                self.target.put_tree(tmp, f"{DOCS}/{doc_id}")
            else:  # appears whole, meta last, so no reader takes a half-written one
                incoming = f"{DOCS}/{INCOMING_PREFIX}{meta['pending_id']}"
                meta_text = (tmp / META).read_text(encoding="utf-8")
                (tmp / META).unlink()
                self.target.put_tree(tmp, incoming)
                self.target.write_text(f"{incoming}/{META}", meta_text)
                self.target.move(incoming, f"{DOCS}/{meta['pending_id']}")
        if replace is None:
            return meta
        if self.auto_settle:
            self.settle(replace)
            current = self.meta(replace)
            if current.get("updated") == meta["created"]:
                return current
        return {**meta, "pending": True}

    # -- versions: replacements and their application ---------------------------------

    def _root_of(self, doc_id: str) -> str | None:
        """``docs`` or ``trash``: where a document (not a version) lives, if anywhere."""
        for root in (DOCS, TRASH):
            if self.target.exists(f"{root}/{doc_id}/{META}"):
                return root
        return None

    def pending(
        self, doc_id: str | None = None, *, names: list[str] | None = None
    ) -> list[str]:
        """Pending replacements (directory names), oldest first; of one document if given.

        ``names``: the listing of ``docs/`` when the caller already has it.
        """
        names = [
            n
            for n in (self.target.list_dirs(DOCS) if names is None else names)
            if PENDING_SEP in n and not n.startswith(".")
        ]
        if doc_id is not None:
            names = [n for n in names if n.rpartition(PENDING_SEP)[0] == doc_id]
        return sorted(names, key=lambda n: n.rpartition(PENDING_SEP)[2])

    def settle(self, doc_id: str | None = None) -> list[str]:
        """Apply pending replacements (of one document, or all); return the ids replaced.

        A replacement whose document is not here yet (it is still on its way, or the
        document was purged) stays pending and is listed under its own id.
        """
        listing = {root: self.target.list_dirs(root) for root in (DOCS, TRASH)}
        recovered = False
        for root, names in listing.items():  # first, what a crash left half done
            for n in names:
                base = n[len(LOCK_PREFIX) :]
                if n.startswith(LOCK_PREFIX) and doc_id in (None, base):
                    recovered |= self._recover(f"{root}/{n}", root, base)
        pending = self.pending(doc_id, names=None if recovered else listing[DOCS])
        bases = {n.rpartition(PENDING_SEP)[0] for n in pending}
        return sorted(b for b in bases if self._apply(b))

    def _apply(self, base: str) -> bool:
        """Apply the pending replacements of ``base``, oldest first, under its lock.

        Stops at the first one that is not ready (still arriving, or unreadable): order
        matters, and the next pull or read retries it.
        """
        root = self._root_of(base)
        names = self.pending(base)
        if root is None or not names:
            return False
        lock = self._lock(root, base)
        if lock is None:
            return False  # another reader is applying them
        applied = False
        try:
            for name in names:
                if not self._swap_in(root, base, name, lock):
                    break
                applied = True
        finally:
            self._unlock(lock)
        return applied

    def _lock(self, root: str, base: str) -> str | None:
        """Take ``<root>/.lock-<base>`` (created with its note in one step); recover a
        stale one first. ``None`` when another reader holds it."""
        lock = f"{root}/{LOCK_PREFIX}{base}"
        for _ in range(2):
            try:
                self.target.make_lock(lock, json.dumps(self._holder()))
            except (OSError, RuntimeError):
                if not self._recover(lock, root, base):
                    return None
                continue
            return lock
        return None

    @contextmanager
    def _locked(self, root: str, base: str):
        """Hold the document's lock for a move of the whole document (trash, restore)."""
        lock = self._lock(root, base)
        if lock is None:
            raise RuntimeError(f"{base} is being replaced right now; try again")
        try:
            yield
        finally:
            self._unlock(lock)

    @staticmethod
    def _holder(**info) -> dict:
        return {"since": time.time(), "host": socket.gethostname(), "pid": os.getpid(), **info}

    def _lock_note(self, lock: str, info: dict) -> None:
        self.target.write_text(f"{lock}/{LOCK_INFO}", json.dumps(self._holder(**info)))

    @staticmethod
    def _stale(info: dict) -> bool:
        """Old, or held by a process of this host that is gone."""
        if time.time() - float(info.get("since", 0)) >= LOCK_STALE_S:
            return True
        if info.get("host") == socket.gethostname() and info.get("pid"):
            try:
                os.kill(int(info["pid"]), 0)
            except ProcessLookupError:
                return True
            except (PermissionError, ValueError, OverflowError):
                return False
        return False

    def _unlock(self, lock: str) -> None:
        """Release the lock, unless a failed step left files in it (recovery's job)."""
        if any(self.target.exists(f"{lock}/{d}") for d in ("next", "old")):
            return
        self.target.remove_tree(lock)  # holds only its notes now

    def _recover(self, lock: str, root: str, base: str) -> bool:
        """Finish or undo the work of a lock left by a crash; True when it is released.

        A lock is stale when its note is older than ``LOCK_STALE_S`` (or it has none, a
        moment after it was taken). Whatever step the crash interrupted, the files are in
        one of three places (the document, the lock's ``next`` or its ``old``), and each
        state has one way forward or back. Nothing is deleted but the emptied lock.
        """
        try:
            info = json.loads(self.target.read_text(f"{lock}/{LOCK_INFO}"))
            if not isinstance(info, dict):
                info = {"since": 0}
        except (OSError, RuntimeError, ValueError):
            # the note is written with the lock, so none means a crash in between (or
            # the lock is just gone, which the next take settles)
            info = {"since": 0}
        if not self._stale(info):
            return False
        live = f"{root}/{base}"
        nxt, old = f"{lock}/next", f"{lock}/old"
        try:
            pend = f"{DOCS}/{info['pending']}" if "pending" in info else None
            if self.target.exists(nxt):  # interrupted before the new version went live
                if not self.target.exists(f"{live}/{META}") and self.target.exists(old):
                    self.target.move(old, live)
                self.target.move(nxt, pend)
            elif self.target.exists(old):
                if "replaces" in json.loads(self.target.read_text(f"{live}/{META}")):
                    self._roll_back(live, old, pend)  # live, but its meta never written
                else:  # done but for archiving the old version
                    self._archive(old, live, int(info["n"]))
            self.target.remove_tree(lock)
        except (OSError, RuntimeError, KeyError, ValueError):
            return False  # leave it as it is: nothing is lost, it stays retryable
        return True

    def _ready(self, pend: str, base: str) -> dict | None:
        """The pending replacement's meta when it is complete and well formed, else None.

        Complete means every file its meta lists is there at the size it records, so a
        replacement still arriving (a pull in progress) is never applied.
        """
        try:
            meta = json.loads(self.target.read_text(f"{pend}/{META}"))
        except (OSError, RuntimeError, ValueError):
            return None
        if not isinstance(meta, dict):
            return None
        files, sizes = meta.get("files"), meta.get("sizes")
        if (
            meta.get("replaces") != base
            or not isinstance(files, list)
            or not isinstance(sizes, dict)
            or not all(isinstance(f, str) for f in files)
            or any(f.split("/", 1)[0] in RESERVED for f in files)
            or self.target.exists(f"{pend}/{VERSIONS}")
        ):
            return None
        try:
            on_disk = self.target.file_sizes(pend, files)
        except (OSError, RuntimeError, ValueError):
            return None
        return meta if all(on_disk.get(f) == sizes.get(f) for f in files) else None

    def _roll_back(self, live: str, old: str, pend: str) -> None:
        """Undo a swap whose new version went live without its final meta."""
        nxt = f"{old.rpartition('/')[0]}/next"
        self.target.move(live, nxt)
        self.target.move(old, live)
        self.target.move(nxt, pend)

    def _swap_in(self, root: str, base: str, name: str, lock: str) -> bool:
        """Make the pending replacement ``name`` the current version of ``base``.

        Everything that can fail is checked first. Then, renames only: the replacement
        into the lock (with its final meta), the document out of its place and the new
        version into it (the only moment the id has nothing behind it, and readers wait
        through it), the final meta written over the replacement's own, then the old
        version, whole, under ``.versions/<n>/``. Until that meta is written, every step
        is undone by renames alone, so a failing disk never strands a replacement.
        """
        live, pend = f"{root}/{base}", f"{DOCS}/{name}"
        new = self._ready(pend, base)
        if new is None:
            return False
        try:
            prev = json.loads(self.target.read_text(f"{live}/{META}"))
            history = prev.get("versions", [])
            if not isinstance(history, list) or not all(
                isinstance(v, dict) for v in history
            ):
                return False
            n = int(prev.get("version", 1))
        except (OSError, RuntimeError, ValueError, AttributeError, TypeError):
            return False
        applied = {v.get("from_pending") for v in history} | {prev.get("from_pending")}
        if name in applied:  # pulled twice: already in the history; to the bin with it
            try:
                self.target.move(pend, f"{TRASH}/{name}-{secrets.token_hex(2)}")
            except (OSError, RuntimeError):
                return False
            return True
        if self.target.exists(f"{live}/{VERSIONS}/{n}"):
            return False
        entry = {
            "n": n,
            "title": prev.get("title", ""),
            "kind": prev.get("kind", ""),
            "size": prev.get("size", 0),
            "created": prev.get("updated") or prev.get("created", ""),
            "from_pending": prev.get("from_pending"),
        }
        for key in ("replaces", "pending_id"):
            new.pop(key, None)
        meta = {
            **new,
            "id": base,
            "tags": new.get("tags") or prev.get("tags", []),
            "created": prev.get("created", new.get("created")),
            "updated": new.get("created"),
            "version": n + 1,
            "versions": [*history, entry],
            "from_pending": name,
        }
        if "trashed" in prev:
            meta["trashed"] = prev["trashed"]
        nxt, old = f"{lock}/next", f"{lock}/old"
        try:
            self._lock_note(lock, {"pending": name, "n": n})
            self.target.move(pend, nxt)
        except (OSError, RuntimeError):
            return False
        try:
            self.target.move(live, old)
        except (OSError, RuntimeError):
            self.target.move(nxt, pend)  # nothing changed: put it back
            return False
        try:
            self.target.move(nxt, live)
        except (OSError, RuntimeError):
            self.target.move(old, live)
            self.target.move(nxt, pend)
            return False
        try:
            self.target.write_text(f"{live}/{META}", json.dumps(meta, indent=1))
        except (OSError, RuntimeError):
            self._roll_back(live, old, pend)
            return False
        for _ in range(2):  # live already; a failure here leaves `old` to recovery
            try:
                self._archive(old, live, n)
                break
            except (OSError, RuntimeError):
                time.sleep(SWAP_STEP_S)
        return True

    def _archive(self, old: str, live: str, n: int) -> None:
        """Move the old version (with the history it carried) under the live document."""
        if self.target.exists(f"{old}/{VERSIONS}") and not self.target.exists(
            f"{live}/{VERSIONS}"
        ):
            self.target.move(f"{old}/{VERSIONS}", f"{live}/{VERSIONS}")
        self.target.move(old, f"{live}/{VERSIONS}/{n}")

    def doc_rel(self, doc_id: str) -> str:
        """The directory of a document (or of a version, ``<id>@<n>``) under the data root."""
        base, n = split_version(doc_id)
        root = self._where(base)
        return f"{root}/{base}" + (f"/{VERSIONS}/{n}" if n else "")

    def versions(self, doc_id: str) -> list[dict]:
        """Every version of a document, oldest first, the current one last."""
        meta = self.meta(doc_id)
        current = {
            "n": meta.get("version", 1),
            "title": meta.get("title", ""),
            "kind": meta.get("kind", ""),
            "size": meta.get("size", 0),
            "created": meta.get("updated") or meta.get("created", ""),
            "current": True,
        }
        return [*meta.get("versions", []), current]

    # -- reading ----------------------------------------------------------------------

    def list(self, *, trash: bool = False) -> list[dict]:
        """Every document's meta, last changed first (``updated``, else ``created``).

        Pending replacements are applied first (when this store settles). One whose
        document is not here is listed under its own id, so it is never out of sight.
        """
        metas = self.target.read_metas(TRASH if trash else DOCS)
        if self.auto_settle and any("replaces" in m for m in metas):
            if self.settle():
                metas = self.target.read_metas(TRASH if trash else DOCS)
        metas = [
            {**m, "id": m["pending_id"], "pending": True} if "replaces" in m else m
            for m in metas
            if "replaces" not in m or _is_pending_of(m.get("pending_id"), m["replaces"])
        ]
        return sorted(
            metas,
            key=lambda m: (m.get("updated") or m.get("created", ""), m.get("id", "")),
            reverse=True,
        )

    def _where(self, doc_id: str) -> str:
        root = self._root_of(check_id(doc_id))
        deadline = time.monotonic() + SWAP_WAIT_S
        while root is None and time.monotonic() < deadline and self._swapping(doc_id):
            time.sleep(SWAP_STEP_S)  # a replacement is going live: wait out the rename
            root = self._root_of(doc_id)
        if root is None:
            raise KeyError(doc_id)
        return root

    def _swapping(self, doc_id: str) -> bool:
        return any(
            self.target.exists(f"{r}/{LOCK_PREFIX}{doc_id}/old") for r in (DOCS, TRASH)
        )

    def meta(self, doc_id: str, *, settle: bool = True) -> dict:
        """One document's meta; ``in_trash`` says which side of the bin it is on.

        ``<id>@<n>`` is version ``n``: its own meta, with ``version_of`` naming the document.
        A pending replacement, read by its own id, says ``pending``. ``settle=False``
        skips applying pending replacements (for a hot path such as a raw file).
        """
        base, n = split_version(doc_id)
        if settle and n is None and self.auto_settle and PENDING_SEP not in base:
            self.settle(base)
        deadline = time.monotonic() + SWAP_WAIT_S
        for attempt in range(2):
            rel = self.doc_rel(doc_id)
            try:
                meta = json.loads(self.target.read_text(f"{rel}/{META}"))
            except (OSError, RuntimeError):
                if attempt:  # a swap landed between finding it and reading it: once more
                    raise KeyError(doc_id) from None
                continue
            # a new version that went live a moment ago, its final meta not yet written
            while (
                "replaces" in meta
                and n is None
                and PENDING_SEP not in base
                and time.monotonic() < deadline
                and self._swapping(base)
            ):
                time.sleep(SWAP_STEP_S)
                with suppress(OSError, RuntimeError, ValueError):
                    meta = json.loads(self.target.read_text(f"{rel}/{META}"))
            break
        meta["in_trash"] = rel.startswith(TRASH + "/")
        if n is not None:
            meta.update(id=doc_id, version_of=base, version=n)
        elif "replaces" in meta:
            meta.update(id=base, pending=True)
        return meta

    def read_text(self, doc_id: str, rel: str | None = None) -> str:
        """A document's main file (or one of its files) as text."""
        meta = self.meta(doc_id)
        rel = rel or meta["main"]
        if rel not in meta["files"]:
            raise KeyError(rel)
        return self.target.read_text(f"{self.doc_rel(doc_id)}/{rel}")

    def search(self, query: str, *, trash: bool = False) -> list[dict]:
        """Case-insensitive match of every query word against title, tags, excerpt, source."""
        words = [w for w in query.lower().split() if w]
        if not words:
            return self.list(trash=trash)

        def haystack(m: dict) -> str:
            return " ".join(
                [
                    m.get("title", ""),
                    " ".join(m.get("tags", [])),
                    m.get("excerpt", ""),
                    json.dumps(m.get("source", {})),
                ]
            ).lower()

        return [
            m for m in self.list(trash=trash) if all(w in haystack(m) for w in words)
        ]

    # -- the recycle bin --------------------------------------------------------------

    def trash(self, doc_id: str) -> dict:
        """Move a document into the bin (idempotent)."""
        meta = self._whole(doc_id)
        if not meta["in_trash"]:
            with self._locked(DOCS, doc_id):
                self.target.move(f"{DOCS}/{doc_id}", f"{TRASH}/{doc_id}")
            meta["trashed"] = now_iso()
            meta.pop("in_trash", None)
            self.target.write_text(
                f"{TRASH}/{doc_id}/{META}", json.dumps(meta, indent=1)
            )
        meta["in_trash"] = True
        return meta

    def restore(self, doc_id: str) -> dict:
        """Move a document out of the bin (idempotent)."""
        meta = self._whole(doc_id)
        if meta["in_trash"]:
            with self._locked(TRASH, doc_id):
                self.target.move(f"{TRASH}/{doc_id}", f"{DOCS}/{doc_id}")
            meta.pop("trashed", None)
            meta.pop("in_trash", None)
            self.target.write_text(
                f"{DOCS}/{doc_id}/{META}", json.dumps(meta, indent=1)
            )
        meta["in_trash"] = False
        return meta

    def _whole(self, doc_id: str) -> dict:
        """The meta of a whole document; a version is not trashed or restored on its own."""
        if split_version(doc_id)[1] is not None:
            raise ValueError(f"{doc_id} is a version; trash or restore the document")
        return self.meta(doc_id)

    def purge(self, doc_id: str) -> None:
        """Delete a document that is in the bin. Refuses one that is not."""
        meta = self._whole(doc_id)
        if not meta["in_trash"]:
            raise PermissionError(f"{doc_id} is not in the trash; trash it first")
        self.target.remove_tree(f"{TRASH}/{doc_id}")

    # -- groups -----------------------------------------------------------------------

    def make_group(
        self, title: str, doc_ids: Iterable[str], *, gid: str | None = None
    ) -> dict:
        """Create (or overwrite) a group: a titled, ordered list of document ids."""
        ids = [check_id(i) for i in doc_ids]
        gid = check_id(gid) if gid else mk_id(title)
        group = {"id": gid, "title": title, "docs": ids, "created": now_iso()}
        self.target.write_text(f"{GROUPS}/{gid}.json", json.dumps(group, indent=1))
        return group

    def add_to_group(self, gid: str, doc_ids: Iterable[str]) -> dict:
        """Append ids to an existing group, keeping order and skipping duplicates."""
        group = self.group(gid)
        for i in doc_ids:
            if check_id(i) not in group["docs"]:
                group["docs"].append(i)
        group["updated"] = now_iso()
        self.target.write_text(f"{GROUPS}/{gid}.json", json.dumps(group, indent=1))
        return group

    def group(self, gid: str) -> dict:
        """One group, by id."""
        check_id(gid)
        if not self.target.exists(f"{GROUPS}/{gid}.json"):
            raise KeyError(gid)
        return json.loads(self.target.read_text(f"{GROUPS}/{gid}.json"))

    def list_groups(self) -> list[dict]:
        """Every group, newest first."""
        names = [n for n in self.target.list_files(GROUPS) if n.endswith(".json")]
        groups = []
        for n in names:
            try:
                groups.append(json.loads(self.target.read_text(f"{GROUPS}/{n}")))
            except (
                OSError,
                RuntimeError,
                ValueError,
            ):  # ValueError: bad JSON, or a symlink out of the root
                continue
        return sorted(groups, key=lambda g: g.get("created", ""), reverse=True)
