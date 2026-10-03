"""The document store: a flat set of documents, tags, groups and a recycle bin, as plain files.

Layout under the data root (local or remote, see :mod:`intray.target`)::

    docs/<id>/meta.json         one document: metadata
    docs/<id>/<main file>       its content (index.html, report.md, ...), plus any assets
    trash/<id>/...              the same shape; the recycle bin is a move
    groups/<gid>.json           a named, ordered list of document ids with its own URL

Flat on purpose: agents from many corpora do not share a hierarchy, and every placement
decision costs tokens. Tags and groups carry the structure. Ids are time-sortable and
readable (``20261003-203301-starwars-theme-report-3f9a``), so a listing is already in
publication order and a URL says what it points to.

Plain files, written whole, because the same tree is written by rsync from another machine
and read by the server; there is no index to keep consistent.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from intray.target import LocalTarget, Target

DOCS = "docs"
TRASH = "trash"
GROUPS = "groups"
META = "meta.json"
MAX_SLUG_LEN = 48
EXCERPT_CHARS = 280
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
#: extension -> kind. ``html`` renders in a frame, ``md`` renders as markdown, ``text`` as
#: preformatted text, anything else is a download.
KINDS = {
    ".md": "md",
    ".markdown": "md",
    ".html": "html",
    ".htm": "html",
    ".txt": "text",
    ".log": "text",
    ".json": "text",
    ".csv": "text",
    ".toml": "text",
    ".yaml": "text",
    ".yml": "text",
    ".py": "text",
}
TEXT_KINDS = frozenset({"md", "text"})


def now_iso() -> str:
    """UTC timestamp with second precision, the format every meta.json uses."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str, *, max_len: int = MAX_SLUG_LEN) -> str:
    """Lowercase ascii words joined by hyphens; empty input becomes ``doc``."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    slug = "-".join(words)
    if len(slug) > max_len:  # cut at a word boundary, never mid-word
        slug = slug[:max_len].rsplit("-", 1)[0] if "-" in slug[:max_len] else slug[:max_len]
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


def kind_of(filename: str) -> str:
    """The rendering kind of a file, from its extension."""
    return KINDS.get(Path(filename).suffix.lower(), "file")


def _title_from_content(path: Path, kind: str) -> str | None:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return None
    if kind == "md":
        m = re.search(r"^#\s+(.+?)\s*$", head, re.M)
        return m.group(1).strip() if m else None
    if kind == "html":
        m = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    return None


def _excerpt(path: Path, kind: str) -> str:
    if kind not in TEXT_KINDS:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return ""
    text = re.sub(r"^#+\s.*$", "", text, flags=re.M)  # drop headings
    text = re.sub(r"[`*_>\[\]()#]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:EXCERPT_CHARS]


def _pick_main(files: list[Path]) -> Path:
    """The file a viewer opens first: index.html, else the first renderable, else the first."""
    for f in files:
        if f.name.lower() in ("index.html", "index.htm"):
            return f
    for f in files:
        if kind_of(f.name) != "file":
            return f
    return files[0]


def _stage(sources: list[Path], tmp: Path) -> tuple[Path, list[str]]:
    """Copy the sources into ``tmp`` and return (main file, relative file list)."""
    if len(sources) == 1 and sources[0].is_dir():
        shutil.copytree(sources[0], tmp, dirs_exist_ok=True)
    else:
        for src in sources:
            if src.is_dir():
                shutil.copytree(src, tmp / src.name, dirs_exist_ok=True)
            else:
                shutil.copy2(src, tmp / src.name)
    files = sorted(p for p in tmp.rglob("*") if p.is_file() and p.name != META)
    if not files:
        raise ValueError("nothing to publish: no files found")
    main = _pick_main(files)
    return main, [str(p.relative_to(tmp)) for p in files]


class DocStore:
    """Publish, list, read, trash, restore and group documents on a :class:`Target`."""

    def __init__(self, target: Target | Path | str):
        self.target: Target = (
            target if hasattr(target, "put_tree") else LocalTarget(target)  # type: ignore[arg-type]
        )

    # -- publishing -------------------------------------------------------------------

    def publish(
        self,
        *sources: Path | str,
        title: str | None = None,
        tags: Iterable[str] = (),
        source: dict | None = None,
        text: str | None = None,
        filename: str = "document.md",
    ) -> dict:
        """Publish files (or a directory, or ``text``) as ONE document; return its meta.

        One markdown or html file is the common case. A directory is published whole, with
        ``index.html`` (or the first renderable file) as the page shown. ``text`` publishes a
        string as ``filename`` instead of reading sources.
        """
        with tempfile.TemporaryDirectory(prefix="tray-") as td:
            tmp = Path(td) / "doc"
            tmp.mkdir()
            if text is not None:
                (tmp / filename).write_text(text, encoding="utf-8")
                paths = [tmp / filename]
                main, files = paths[0], [filename]
            else:
                paths = [Path(s).expanduser() for s in sources]
                missing = [str(p) for p in paths if not p.exists()]
                if missing:
                    raise FileNotFoundError(", ".join(missing))
                main, files = _stage(paths, tmp)
            kind = kind_of(main.name)
            title = title or _title_from_content(main, kind) or main.stem.replace("_", " ")
            doc_id = mk_id(title)
            meta = {
                "id": doc_id,
                "title": title,
                "kind": kind,
                "main": str(main.relative_to(tmp)),
                "files": files,
                "tags": sorted({t.strip() for t in tags if t and t.strip()}),
                "source": source or {},
                "created": now_iso(),
                "size": sum((tmp / f).stat().st_size for f in files),
                "excerpt": _excerpt(main, kind),
            }
            (tmp / META).write_text(json.dumps(meta, indent=1), encoding="utf-8")
            self.target.put_tree(tmp, f"{DOCS}/{doc_id}")
        return meta

    # -- reading ----------------------------------------------------------------------

    def list(self, *, trash: bool = False) -> list[dict]:
        """Every document's meta, newest first (ids sort by time; ``created`` breaks ties)."""
        metas = self.target.read_metas(TRASH if trash else DOCS)
        return sorted(metas, key=lambda m: (m.get("created", ""), m.get("id", "")), reverse=True)

    def _where(self, doc_id: str) -> str:
        check_id(doc_id)
        for root in (DOCS, TRASH):
            if self.target.exists(f"{root}/{doc_id}/{META}"):
                return root
        raise KeyError(doc_id)

    def meta(self, doc_id: str) -> dict:
        """One document's meta; ``in_trash`` says which side of the bin it is on."""
        root = self._where(doc_id)
        meta = json.loads(self.target.read_text(f"{root}/{doc_id}/{META}"))
        meta["in_trash"] = root == TRASH
        return meta

    def read_text(self, doc_id: str, rel: str | None = None) -> str:
        """A document's main file (or one of its files) as text."""
        meta = self.meta(doc_id)
        root = TRASH if meta["in_trash"] else DOCS
        rel = rel or meta["main"]
        if rel not in meta["files"]:
            raise KeyError(rel)
        return self.target.read_text(f"{root}/{doc_id}/{rel}")

    def search(self, query: str, *, trash: bool = False) -> list[dict]:
        """Case-insensitive match of every query word against title, tags, excerpt, source."""
        words = [w for w in query.lower().split() if w]
        if not words:
            return self.list(trash=trash)

        def haystack(m: dict) -> str:
            return " ".join(
                [m.get("title", ""), " ".join(m.get("tags", [])), m.get("excerpt", ""), json.dumps(m.get("source", {}))]
            ).lower()

        return [m for m in self.list(trash=trash) if all(w in haystack(m) for w in words)]

    # -- the recycle bin --------------------------------------------------------------

    def trash(self, doc_id: str) -> dict:
        """Move a document into the bin (idempotent)."""
        meta = self.meta(doc_id)
        if not meta["in_trash"]:
            self.target.move(f"{DOCS}/{doc_id}", f"{TRASH}/{doc_id}")
            meta["trashed"] = now_iso()
            meta.pop("in_trash", None)
            self.target.write_text(f"{TRASH}/{doc_id}/{META}", json.dumps(meta, indent=1))
        meta["in_trash"] = True
        return meta

    def restore(self, doc_id: str) -> dict:
        """Move a document out of the bin (idempotent)."""
        meta = self.meta(doc_id)
        if meta["in_trash"]:
            self.target.move(f"{TRASH}/{doc_id}", f"{DOCS}/{doc_id}")
            meta.pop("trashed", None)
            meta.pop("in_trash", None)
            self.target.write_text(f"{DOCS}/{doc_id}/{META}", json.dumps(meta, indent=1))
        meta["in_trash"] = False
        return meta

    def purge(self, doc_id: str) -> None:
        """Delete a document that is in the bin. Refuses one that is not."""
        meta = self.meta(doc_id)
        if not meta["in_trash"]:
            raise PermissionError(f"{doc_id} is not in the trash; trash it first")
        self.target.remove_tree(f"{TRASH}/{doc_id}")

    # -- groups -----------------------------------------------------------------------

    def make_group(self, title: str, doc_ids: Iterable[str], *, gid: str | None = None) -> dict:
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
        names = []
        if hasattr(self.target, "root") and isinstance(getattr(self.target, "root"), Path):
            base = self.target.root / GROUPS  # type: ignore[union-attr]
            names = sorted(p.name for p in base.glob("*.json")) if base.is_dir() else []
        else:
            names = [n for n in self.target.list_dirs(GROUPS) if n.endswith(".json")]
        groups = []
        for n in names:
            try:
                groups.append(json.loads(self.target.read_text(f"{GROUPS}/{n}")))
            except (OSError, RuntimeError, json.JSONDecodeError):
                continue
        return sorted(groups, key=lambda g: g.get("created", ""), reverse=True)
