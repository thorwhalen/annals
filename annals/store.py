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
import re
import secrets
import shutil
import tempfile
import unicodedata
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from annals.target import LocalTarget, Target

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
#: a pending replacement being applied is renamed to this prefix first (the claim)
CLAIM_PREFIX = ".claim-"
PREV, NEXT = ".prev", ".next"
#: names a document's own files may not use: the store's bookkeeping lives there
RESERVED = (VERSIONS, PREV, NEXT)
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
            self.target.put_tree(tmp, f"{DOCS}/{meta.get('pending_id', doc_id)}")
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

    def pending(self, doc_id: str | None = None) -> list[str]:
        """Pending replacements (directory names), oldest first; of one document if given."""
        names = [
            n
            for n in self.target.list_dirs(DOCS)
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
        bases = {n.rpartition(PENDING_SEP)[0] for n in self.pending(doc_id)}
        return sorted(b for b in bases if self._apply(b))

    def _apply(self, base: str) -> bool:
        """Apply every pending replacement of ``base``, oldest first.

        Every step is a rename. The first claims the document: it is renamed into a
        working directory only this call knows, so a competing call fails that rename and
        leaves the work to the winner, and no replacement is applied twice or out of
        order. Each replacement is then claimed the same way, the current version moved
        under its ``.versions/``, and the result renamed back into place. No file is ever
        removed (only the emptied working directory); the document is absent from its place for those few renames.
        """
        root = self._root_of(base)
        names = self.pending(base)
        if root is None or not names:
            return False
        work = f"{root}/{CLAIM_PREFIX}{base}-{secrets.token_hex(3)}"
        try:
            self.target.move(f"{root}/{base}", f"{work}/{PREV}")
        except (OSError, RuntimeError):
            with suppress(OSError, RuntimeError):  # the move made it, then lost the race
                self.target.remove_empty_dir(work)
            return False  # another reader holds it
        applied = False
        try:
            for name in names:
                try:
                    self.target.move(f"{DOCS}/{name}", f"{work}/{NEXT}")
                except (OSError, RuntimeError):
                    continue  # gone since it was listed
                self._stack(work)
                applied = True
        finally:
            self.target.move(f"{work}/{PREV}", f"{root}/{base}")
        self.target.remove_empty_dir(work)
        return applied

    def _stack(self, work: str) -> None:
        """In ``work``: put ``.next`` on top of ``.prev`` and make the result ``.prev``."""
        prev = json.loads(self.target.read_text(f"{work}/{PREV}/{META}"))
        new = json.loads(self.target.read_text(f"{work}/{NEXT}/{META}"))
        n = int(prev.get("version", 1))
        if self.target.exists(f"{work}/{PREV}/{VERSIONS}"):
            self.target.move(f"{work}/{PREV}/{VERSIONS}", f"{work}/{NEXT}/{VERSIONS}")
        self.target.move(f"{work}/{PREV}", f"{work}/{NEXT}/{VERSIONS}/{n}")
        entry = {
            "n": n,
            "title": prev.get("title", ""),
            "kind": prev.get("kind", ""),
            "size": prev.get("size", 0),
            "created": prev.get("updated") or prev.get("created", ""),
        }
        for key in ("replaces", "pending_id"):
            new.pop(key, None)
        meta = {
            **new,
            "id": prev["id"],
            "tags": new.get("tags") or prev.get("tags", []),
            "created": prev.get("created", new.get("created")),
            "updated": new.get("created"),
            "version": n + 1,
            "versions": [*prev.get("versions", []), entry],
        }
        if "trashed" in prev:
            meta["trashed"] = prev["trashed"]
        self.target.write_text(f"{work}/{NEXT}/{META}", json.dumps(meta, indent=1))
        self.target.move(f"{work}/{NEXT}", f"{work}/{PREV}")

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
            if "replaces" not in m or m.get("pending_id")
        ]
        return sorted(
            metas,
            key=lambda m: (m.get("updated") or m.get("created", ""), m.get("id", "")),
            reverse=True,
        )

    def _where(self, doc_id: str) -> str:
        root = self._root_of(check_id(doc_id))
        if root is None:
            raise KeyError(doc_id)
        return root

    def meta(self, doc_id: str) -> dict:
        """One document's meta; ``in_trash`` says which side of the bin it is on.

        ``<id>@<n>`` is version ``n``: its own meta, with ``version_of`` naming the document.
        A pending replacement, read by its own id, says ``pending``.
        """
        base, n = split_version(doc_id)
        if n is None and self.auto_settle and PENDING_SEP not in base:
            self.settle(base)
        rel = self.doc_rel(doc_id)
        meta = json.loads(self.target.read_text(f"{rel}/{META}"))
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
