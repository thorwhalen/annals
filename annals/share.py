"""Share links: one document (or a group) behind a public, unguessable, revocable link.

A share is a record under the data root, ``shares/<token>.json``, written through the
same :class:`annals.target.Target` as the documents, so ``annals share`` works over ssh
exactly like ``annals publish``. The record is the whole contract; the owner's API, the
page's Share button, the CLI and the public share server (:mod:`annals.share_api`) are
surfaces over it::

    {
     "token": "<22 url-safe chars, 128 random bits>",
     "title": "...", "created": "<iso>",
     "root": {"kind": "doc" | "group", "id": "<id>"},
     "docs": {"<doc id>": ["<file>", ...], ...},   # what the link may reach, and only that
     "expires": "<iso>" | null,
     "password": "scrypt$..." | null,               # a hash; the password is never stored
     "revoked": "<iso>" | null                       # a tombstone: a revoked link is a 404
    }

``docs`` is the scope. Every request of the public server is checked against it, never
against what the link was made from: a file not listed is a 404 even when it sits beside
the shared page, and a page or a link of the shared text that points outside the scope is
removed before the text leaves the server (:func:`filter_refs`), so the recipient sees
neither private ids nor private paths.

The password is a gate on the link, not an account: anyone who knows both may read. It
is hashed with stdlib ``scrypt`` (the ``hasher`` seam takes argon2 or anything with
``hash``/``verify``), and a correct one earns an HMAC cookie keyed by that hash, so
changing the password or revoking the link ends every open session.

Tokens come from :func:`secrets.token_urlsafe` with 128 bits, as heed's review pages do.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Protocol

from annals.store import DocStore, check_id, kind_of

SHARES = "shares"
TOKEN_BYTES = 16  # 128 bits, the same as heed's review page ids
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
#: duration suffixes accepted by :func:`parse_expires` (``7d``, ``12h``, ``2w``, ``30m``)
_DURATION_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
_DURATION_RE = re.compile(r"^(\d+)\s*([mhdw])$", re.I)
#: an annals id (doc or group) as :func:`annals.store.mk_id` makes them
ANNALS_ID = r"\d{8}-\d{6}-[a-z0-9]+(?:-[a-z0-9]+)*"
_ANNALS_ID_RE = re.compile(rf"(?<![\w-])(?P<id>{ANNALS_ID})(?![\w-])")
#: path segments that name a document (or group) in any annals url
_ID_IN_URL_RE = re.compile(
    rf"/(?P<seg>d|g|raw|thumb|docs|groups)/(?P<id>{ANNALS_ID})(?![\w-])"
)
REMOVED_LINK = "(link not shared)"
REMOVED_ID = "(not shared)"


def now_utc() -> datetime:
    """The current time, UTC, second precision (the clock every default reads)."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def new_token() -> str:
    """A fresh link token: 128 random bits, url-safe."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def check_token(token: str) -> str:
    """Raise ``ValueError`` on anything that could not be a token (a path, a dot, ...)."""
    if not isinstance(token, str) or not TOKEN_RE.match(token):
        raise ValueError("not a share token")
    return token


# -- passwords ----------------------------------------------------------------------


class PasswordHasher(Protocol):
    """What a share needs to gate a link on a password."""

    def hash(self, password: str) -> str: ...

    def verify(self, hashed: str, password: str) -> bool: ...


@dataclass(frozen=True)
class ScryptHasher:
    """Stdlib ``hashlib.scrypt``, stored as ``scrypt$n$r$p$salt$hash`` (base64).

    The default needs no dependency; ``n=2**14, r=8`` costs ~16 MB and tens of ms per
    check, which the attempt limit of the share server bounds.
    """

    n: int = 2**14
    r: int = 8
    p: int = 1
    salt_bytes: int = 16
    dklen: int = 32

    def _derive(self, password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=self.dklen,
            maxmem=2 * 128 * r * n + 2**20,
        )

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(self.salt_bytes)
        dk = self._derive(password, salt, self.n, self.r, self.p)
        b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
        return f"scrypt${self.n}${self.r}${self.p}${b64(salt)}${b64(dk)}"

    def verify(self, hashed: str, password: str) -> bool:
        try:
            scheme, n, r, p, salt, dk = hashed.split("$")
            if scheme != "scrypt":
                return False
            expected = base64.b64decode(dk)
            got = self._derive(password, base64.b64decode(salt), int(n), int(r), int(p))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(got, expected)


# -- expiry -------------------------------------------------------------------------


def parse_expires(value, *, now: datetime | None = None) -> str | None:
    """An expiry as an ISO UTC timestamp, or ``None`` for never.

    Accepts a duration (``30m``, ``12h``, ``7d``, ``2w``), a date (``2026-11-01``: the
    END of that day, UTC, so the link works through the day named), an ISO timestamp (a
    naive one is UTC), or a ``datetime``. A moment already past is refused.

    >>> parse_expires("2d", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    '2026-01-03T00:00:00+00:00'
    >>> parse_expires("2026-01-05", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    '2026-01-05T23:59:59+00:00'
    """
    now = now or now_utc()
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        when = value
    else:
        s = str(value).strip()
        m = _DURATION_RE.match(s)
        if m:
            n, unit = int(m.group(1)), _DURATION_UNITS[m.group(2).lower()]
            when = now + timedelta(**{unit: n})
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            when = datetime.fromisoformat(s).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        else:
            try:
                when = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(
                    f"not an expiry: {value!r}; give a duration (7d, 12h), a date "
                    "(2026-11-01) or an ISO timestamp"
                ) from None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc).replace(microsecond=0)
    if when <= now:
        raise ValueError(f"expiry {when.isoformat()} is already past")
    return when.isoformat()


def is_expired(record: dict, *, now: datetime | None = None) -> bool:
    """True when the record has an expiry and it is reached (a bad one counts as reached)."""
    exp = record.get("expires")
    if exp is None:
        return False
    try:
        when = datetime.fromisoformat(exp)
    except (TypeError, ValueError):
        return True  # fail closed
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (now or now_utc()) >= when


# -- references in a shared text ----------------------------------------------------

_MD_LINK_RE = re.compile(
    r"(?P<bang>!?)\[(?P<text>(?:[^\[\]\n]|\[[^\]\n]*\])*)\]"
    r"\((?P<url><[^>\n]*>|[^)\s]+)(?P<title>\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)"
)
_MD_REFDEF_RE = re.compile(
    r"^(?P<lead> {0,3}\[[^\]\n]+\]:[ \t]*)(?P<url><[^>\n]*>|\S+)(?P<rest>.*)$", re.M
)
_MD_AUTOLINK_RE = re.compile(r"<(?P<url>(?:https?:)?/[^>\s]*)>")
_HTML_ATTR_RE = re.compile(
    r"(?P<attr>\b(?:src|href|poster|data|action|srcset|xlink:href)\s*=\s*)"
    r"(?:\"(?P<u1>[^\"]*)\"|'(?P<u2>[^']*)'|(?P<u3>[^\s>\"']+))",
    re.I,
)
_BARE_URL_RE = re.compile(
    rf"(?:https?://|/)[^\s<>()\"'\]]*?/(?:d|g|raw|thumb|docs|groups)/{ANNALS_ID}[^\s<>()\"'\]]*"
)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


def resolve_rel(url: str, from_dir: str = "") -> str | None:
    """A relative url as a file path inside the document, or ``None`` if it is not one.

    >>> resolve_rel("img/a.png?x=1#y", "notes/")
    'notes/img/a.png'
    >>> resolve_rel("../../etc/passwd") is None, resolve_rel("https://x.org/a") is None
    (True, True)
    """
    from urllib.parse import unquote

    if not url or url.startswith(("#", "/", "\\")) or _SCHEME_RE.match(url):
        return None
    path = unquote(url.split("#")[0].split("?")[0])
    out: list[str] = []
    for part in (from_dir + path).split("/"):
        if part == "..":
            if not out:
                return None  # climbs out of the document
            out.pop()
        elif part and part != ".":
            out.append(part)
    return "/".join(out) or None


def _decider(
    *,
    from_dir: str,
    files: set[str],
    shared: Callable[[str], str | None],
) -> Callable[[str], str | None]:
    """``url -> new url`` (often the same) or ``None`` (remove it)."""

    def decide(url: str) -> str | None:
        url = url.strip()
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1]
        if not url or url.startswith("#"):
            return url
        m = _ID_IN_URL_RE.search(url)
        if m:  # a link to an annals page, any host: in scope, or gone
            return shared(m.group("id"))
        if url.lower().startswith(("javascript:", "vbscript:")):
            return None
        if _SCHEME_RE.match(url) or url.startswith("//"):
            return url  # elsewhere on the web: not ours to hide
        if url.startswith(("/", "\\")):
            return None  # a path on the owner's host: never meaningful to a recipient
        rel = resolve_rel(url, from_dir)
        return url if rel is not None and rel in files else None

    return decide


def references(text: str, kind: str, *, from_dir: str = "") -> dict:
    """What a page points at: files of its document, and annals pages (by id).

    ``{"files": [rel, ...], "ids": [annals id, ...]}``, each in first-seen order; it
    feeds the Share dialog, which offers them to the owner.
    """
    files: list[str] = []
    ids: list[str] = []

    def seen(url: str) -> str:
        url = url.strip().strip("<>")
        m = _ID_IN_URL_RE.search(url)
        if m and m.group("id") not in ids:
            ids.append(m.group("id"))
        rel = None if m else resolve_rel(url, from_dir)
        if rel and rel not in files:
            files.append(rel)
        return url

    if kind == "md":
        for m in _MD_LINK_RE.finditer(text):
            seen(m.group("url"))
        for m in _MD_REFDEF_RE.finditer(text):
            seen(m.group("url"))
    for m in _HTML_ATTR_RE.finditer(text):
        for url in _srcset_urls(m):
            seen(url)
    for m in _BARE_URL_RE.finditer(text):
        seen(m.group(0))
    return {"files": files, "ids": ids}


def _attr_url(m: re.Match) -> str:
    return next(
        g for g in (m.group("u1"), m.group("u2"), m.group("u3")) if g is not None
    )


def _srcset_urls(m: re.Match) -> list[str]:
    value = _attr_url(m)
    if m.group("attr").strip().lower().startswith("srcset"):
        return [c.strip().split()[0] for c in value.split(",") if c.strip()]
    return [value]


def filter_refs(
    text: str,
    kind: str,
    *,
    files: Iterable[str],
    shared: Callable[[str], str | None],
    from_dir: str = "",
) -> str:
    """``text`` with every reference outside the share removed (or rewritten).

    ``files`` are the document's files the share includes; ``shared(id)`` maps an annals
    id to where the recipient opens it (in scope) or ``None`` (not shared). A markdown
    image out of scope disappears, a link keeps its words; an html attribute goes; a bare
    annals url becomes "(link not shared)" and a bare annals id "(not shared)". The text
    of the page itself is the owner's: only references are touched.
    """
    decide = _decider(from_dir=from_dir, files=set(files), shared=shared)

    def md_link(m: re.Match) -> str:
        new = decide(m.group("url"))
        if new is None:
            return "" if m.group("bang") else m.group("text")
        return f"{m.group('bang')}[{m.group('text')}]({new}{m.group('title') or ''})"

    def md_refdef(m: re.Match) -> str:
        new = decide(m.group("url"))
        return f"{m.group('lead')}{new if new is not None else '#'}"

    def md_autolink(m: re.Match) -> str:
        new = decide(m.group("url"))
        return f"<{new}>" if new else REMOVED_LINK

    def html_attr(m: re.Match) -> str:
        urls = _srcset_urls(m)
        news = [decide(u) for u in urls]
        if any(n is None for n in news):
            return "data-annals-removed"
        if len(urls) == 1:
            return f'{m.group("attr")}"{news[0]}"'
        return m.group(0)  # a srcset whose every url is in scope stays as written

    if kind == "md":
        text = _MD_LINK_RE.sub(md_link, text)
        text = _MD_REFDEF_RE.sub(md_refdef, text)
        text = _MD_AUTOLINK_RE.sub(md_autolink, text)
    text = _HTML_ATTR_RE.sub(html_attr, text)
    text = _BARE_URL_RE.sub(lambda m: decide(m.group(0)) or REMOVED_LINK, text)
    return _ANNALS_ID_RE.sub(
        lambda m: m.group(0) if shared(m.group("id")) else REMOVED_ID, text
    )


# -- the store of shares ------------------------------------------------------------


def share_url(base: str | None, token: str) -> str | None:
    """The link a recipient opens, or ``None`` when no share server is configured."""
    return f"{base.rstrip('/')}/{token}/" if base else None


#: what the owner sees of a record: everything but the hash
def public_record(record: dict) -> dict:
    """A record without its password hash (``protected`` says whether it has one)."""
    out = {k: v for k, v in record.items() if k != "password"}
    out["protected"] = bool(record.get("password"))
    return out


class Shares:
    """Create, read, list and revoke shares of a :class:`DocStore`'s documents.

    ``hasher`` hashes link passwords (stdlib scrypt by default); ``clock`` returns the
    current UTC ``datetime`` (tests pin it).
    """

    def __init__(
        self,
        store: DocStore,
        *,
        hasher: PasswordHasher | None = None,
        clock: Callable[[], datetime] = now_utc,
    ):
        self.store = store
        self.hasher = hasher or ScryptHasher()
        self.clock = clock

    # -- what can be shared --

    def resources(self, doc_id: str) -> dict:
        """What the Share dialog offers for a document: its files, and the pages it links.

        ``{"main", "files": [{"rel", "kind", "size", "referenced"}], "pages": [{"id",
        "title", "kind"}]}``. ``referenced`` marks the files the page itself shows or
        links; ``pages`` are the other annals documents its text links to.
        """
        meta = self.store.meta(doc_id)
        refs = {"files": [], "ids": []}
        if meta["kind"] in ("md", "html"):
            try:
                text = self.store.read_text(doc_id)
                refs = references(text, meta["kind"], from_dir=dir_of(meta["main"]))
            except (KeyError, OSError, ValueError, UnicodeDecodeError):
                pass
        sizes = meta.get("sizes", {})
        files = [
            {
                "rel": f,
                "kind": kind_of(f),
                "size": sizes.get(f),
                "referenced": f in refs["files"],
                "main": f == meta["main"],
            }
            for f in meta.get("files", [])
        ]
        pages = []
        for i in refs["ids"]:
            if i == doc_id:
                continue
            try:
                m = self.store.meta(i)
            except (KeyError, ValueError):
                continue  # a group, or a document since deleted
            if not m.get("in_trash"):
                pages.append({"id": i, "title": m.get("title"), "kind": m.get("kind")})
        return {
            "id": doc_id,
            "title": meta.get("title"),
            "main": meta["main"],
            "files": files,
            "pages": pages,
        }

    def _doc_scope(
        self, doc_id: str, include: list[str] | None, exclude: list[str]
    ) -> dict[str, list[str]]:
        meta = self.store.meta(doc_id)
        if meta.get("in_trash"):
            raise ValueError(f"{doc_id} is in the bin; restore it before sharing it")
        all_files = list(meta.get("files", []))
        linked: list[str] = []
        if include is None:
            chosen = all_files
        else:
            unknown = []
            chosen = []
            for x in include:
                if x in all_files:
                    chosen.append(x)
                elif re.fullmatch(ANNALS_ID, x):
                    linked.append(x)
                else:
                    unknown.append(x)
            if unknown:
                raise ValueError(
                    f"not files of {doc_id}: {unknown[:5]}; its files: {all_files[:20]}"
                )
        if meta["main"] in exclude:
            raise ValueError(f"{meta['main']} is the page itself; it is always shared")
        chosen = [
            f
            for f in all_files
            if (f in chosen or f == meta["main"]) and f not in exclude
        ]
        docs = {doc_id: chosen}
        for i in linked:
            m = self.store.meta(i)
            if m.get("in_trash"):
                raise ValueError(f"linked page {i} is in the bin")
            docs[i] = list(m.get("files", []))
        return docs

    def _group_scope(
        self, gid: str, include: list[str] | None, exclude: list[str]
    ) -> dict[str, list[str]]:
        group = self.store.group(gid)
        docs: dict[str, list[str]] = {}
        for i in group["docs"]:
            if include is not None and i not in include:
                continue
            if i in exclude:
                continue
            try:
                m = self.store.meta(i)
            except (KeyError, ValueError):
                continue
            if not m.get("in_trash"):
                docs[i] = list(m.get("files", []))
        unknown = [i for i in (include or []) if i not in group["docs"]]
        if unknown:
            raise ValueError(f"not documents of group {gid}: {unknown[:5]}")
        if not docs:
            raise ValueError(f"group {gid} has nothing to share")
        return docs

    # -- create / read / list / revoke --

    def create(
        self,
        ref: str,
        *,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] = (),
        password: str | None = None,
        expires=None,
        title: str | None = None,
    ) -> dict:
        """Share a document or a group (``ref`` is its id); return the record (no hash).

        A document is shared with all its files unless ``include`` names some (the page
        itself always goes); ``include`` may also name annals pages the document links
        to, which then open inside the share. A group is shared with all its documents
        unless ``include`` names some. ``exclude`` removes files (or a group's documents).
        ``expires`` is anything :func:`parse_expires` reads; ``password`` gates the link.
        """
        check_id(ref)
        include = None if include is None else [x for x in include if x]
        exclude = [x for x in exclude if x]
        try:
            self.store.meta(ref)
            kind = "doc"
        except KeyError:
            kind = "group"
        if kind == "doc":
            docs = self._doc_scope(ref, include, exclude)
            default_title = self.store.meta(ref).get("title")
        else:
            docs = self._group_scope(ref, include, exclude)
            default_title = self.store.group(ref).get("title")
        if password is not None and not password:
            raise ValueError("an empty password gates nothing; omit it instead")
        now = self.clock()
        token = new_token()
        record = {
            "token": token,
            "title": title or default_title or ref,
            "created": now.isoformat(),
            "root": {"kind": kind, "id": ref},
            "docs": docs,
            "expires": parse_expires(expires, now=now),
            "password": self.hasher.hash(password) if password else None,
            "revoked": None,
        }
        self._write(record)
        return public_record(record)

    def _write(self, record: dict) -> None:
        self.store.target.write_text(
            f"{SHARES}/{record['token']}.json", json.dumps(record, indent=1)
        )

    def record(self, token: str) -> dict | None:
        """The stored record (hash included), revoked or not; ``None`` if there is none."""
        try:
            check_token(token)
            rec = json.loads(self.store.target.read_text(f"{SHARES}/{token}.json"))
        except (ValueError, KeyError, OSError, RuntimeError):
            return None
        if not isinstance(rec, dict) or rec.get("token") != token:
            return None  # damaged, or filed under another name: grants nothing
        if not isinstance(rec.get("docs"), dict) or not isinstance(
            rec.get("root"), dict
        ):
            return None
        return rec

    def status(self, token: str) -> tuple[str, dict | None]:
        """``("ok" | "expired" | "missing", record)``; a revoked link is ``missing``."""
        rec = self.record(token)
        if rec is None or rec.get("revoked"):
            return "missing", None
        if is_expired(rec, now=self.clock()):
            return "expired", rec
        return "ok", rec

    def list(self, *, all: bool = False) -> list[dict]:
        """Every share, newest first, without hashes; ``all`` adds revoked and expired."""
        now = self.clock()
        out = []
        for name in self.store.target.list_files(SHARES):
            if not name.endswith(".json"):
                continue
            rec = self.record(name[: -len(".json")])
            if rec is None:
                continue
            rec = public_record(rec)
            rec["active"] = not rec.get("revoked") and not is_expired(rec, now=now)
            if all or rec["active"]:
                out.append(rec)
        return sorted(out, key=lambda r: r.get("created", ""), reverse=True)

    def revoke(self, token: str) -> dict:
        """End a link now (idempotent). The record stays, as a tombstone, for the list."""
        rec = self.record(token)
        if rec is None:
            raise KeyError(token)
        if not rec.get("revoked"):
            rec["revoked"] = self.clock().isoformat()
            rec["password"] = None  # nothing left to guess
            self._write(rec)
        return public_record(rec)

    # -- the password gate --

    def check_password(self, record: dict, password: str) -> bool:
        """Whether ``password`` opens ``record`` (constant time inside the hasher)."""
        hashed = record.get("password")
        return bool(hashed) and self.hasher.verify(hashed, password)

    def unlock_value(self, record: dict) -> str:
        """The cookie value a correct password earns: ``<issued epoch>.<hmac>``."""
        issued = int(self.clock().timestamp())
        return f"{issued}.{_unlock_mac(record, issued)}"

    def unlocked(self, record: dict, value: str | None, *, max_age_s: int) -> bool:
        """Whether a cookie value is a live unlock of this record (no password: always)."""
        if not record.get("password"):
            return True
        if not value or "." not in value:
            return False
        issued_s, _, mac = value.partition(".")
        try:
            issued = int(issued_s)
        except ValueError:
            return False
        now = int(self.clock().timestamp())
        if not (now - max_age_s <= issued <= now + 60):
            return False
        return hmac.compare_digest(mac, _unlock_mac(record, issued))


def _unlock_mac(record: dict, issued: int) -> str:
    # Keyed by the password hash: it holds a random salt and never leaves the server, and
    # a new password (or a revoke, which clears it) invalidates every cookie at once.
    key = (record.get("password") or "").encode("utf-8")
    msg = f"{record['token']}:{issued}".encode("ascii")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def dir_of(rel: str) -> str:
    """The directory part of a relative path, with its trailing slash (``""`` at the top)."""
    i = rel.rfind("/")
    return "" if i < 0 else rel[: i + 1]
