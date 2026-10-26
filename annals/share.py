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

The link itself (the token, the password gate, expiry, revocation) is a
:class:`caplinks.CapabilityLinks` over these records; what is annals' own is the scope
and the filtering. The password is a gate on the link, not an account: anyone who knows
both may read. It is hashed (stdlib ``scrypt`` by default, the ``hasher`` seam takes
argon2), and a correct one earns an HMAC cookie keyed by that hash, so changing the
password or revoking the link ends every open session.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, MutableMapping
from datetime import datetime
from typing import Callable, Iterable

from caplinks import (  # noqa: F401  (ScryptHasher, is_expired, parse_expires: re-exported)
    DFLT_EXPIRES,
    CapabilityLinks,
    JsonRecords,
    PasswordHasher,
    ScryptHasher,
    check_token,
    is_expired,
    now_utc,
    parse_expires,
)

from annals.store import DocStore, check_id, kind_of

SHARES = "shares"
#: an annals id (doc or group) as :func:`annals.store.mk_id` makes them
ANNALS_ID = r"\d{8}-\d{6}-[a-z0-9]+(?:-[a-z0-9]+)*"
# no lookahead: the pattern is greedy, and an id glued to more text is not shared (removed)
_ANNALS_ID_RE = re.compile(rf"(?<!\d)(?P<id>{ANNALS_ID})")
#: path segments that name a document (or group) in any annals url
_ID_IN_URL_RE = re.compile(
    rf"/(?P<seg>d|g|raw|thumb|docs|groups)/(?P<id>{ANNALS_ID})(?![\w-])"
)
REMOVED_LINK = "(link not shared)"
REMOVED_ID = "(not shared)"


# -- references in a shared text ----------------------------------------------------

_MD_LINK_RE = re.compile(
    r"(?P<bang>!?)\[(?P<text>(?:[^\[\]\n]|\[[^\]\n]*\])*)\]"
    r"\([ \t]*(?P<url><[^>\n]*>|[^)\s]+)(?P<title>\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^)\n]*\)))?\s*\)"
)
_MD_REFDEF_RE = re.compile(
    # also inside a quote or a list item: "> [x]: url", "- [x]: url"
    r"^(?P<lead>[ \t]*(?:>[ \t]*)*(?:(?:[*+-]|\d+[.)])[ \t]+)?\[[^\]\n]+\]:[ \t]*)"
    r"(?P<url><[^>\n]*>|\S+)(?P<rest>.*)$",
    re.M,
)
_MD_AUTOLINK_RE = re.compile(r"<(?P<url>(?:https?:)?/[^>\s]*)>")
_HTML_ATTR_RE = re.compile(
    r"(?P<attr>\b(?:src|href|poster|data|action|formaction|srcset|xlink:href|ping|background"
    r"|cite|longdesc|usemap|manifest|codebase|archive|content)\s*=\s*)"
    r"(?:\"(?P<u1>[^\"]*)\"|'(?P<u2>[^']*)'|(?P<u3>[^\s>\"']+))",
    re.I,
)
_BARE_URL_RE = re.compile(
    rf"(?:https?://|/)[^\s<>()\"'\]]*?/(?:d|g|raw|thumb|docs|groups)/{ANNALS_ID}[^\s<>()\"'\]]*"
)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
_CSS_URL_RE = re.compile(r"url\(\s*(?P<q>['\"]?)(?P<url>[^'\")]*)(?P=q)\s*\)", re.I)
#: ``<meta http-equiv=refresh content="0;url=...">``: the one ``content`` that is a url
_REFRESH_RE = re.compile(r"^(?P<lead>\s*\d*\s*;?\s*url\s*=\s*)(?P<url>.*)$", re.I)


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
    private_hosts: Iterable[str] = (),
) -> Callable[[str], str | None]:
    """``url -> new url`` (often the same) or ``None`` (remove it)."""
    from html import unescape
    from urllib.parse import urlsplit

    hosts = {h.lower() for h in private_hosts if h}

    def decide(url: str) -> str | None:
        url = unescape(url).strip()
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
            try:
                host = urlsplit(url).netloc.rsplit("@", 1)[-1].lower()
            except ValueError:
                return None
            if host in hosts:
                return None  # the owner's own host: some other private page
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
    private_hosts: Iterable[str] = (),
) -> str:
    """``text`` with every reference outside the share removed (or rewritten).

    ``files`` are the document's files the share includes; ``shared(id)`` maps an annals
    id to where the recipient opens it (in scope) or ``None`` (not shared). A markdown
    image out of scope disappears, a link keeps its words; an html attribute goes; a bare
    annals url becomes "(link not shared)" and a bare annals id "(not shared)". The text
    of the page itself is the owner's: only references are touched. An absolute url on
    one of ``private_hosts`` (the owner's own) goes too, whatever its path. Every kind of
    text is filtered (markdown, html, plain text, svg): only markdown syntax is markdown's.
    Best effort by design, and the second line of defence: the share server answers 404
    for anything outside the share however the text names it.
    """
    decide = _decider(
        from_dir=from_dir, files=set(files), shared=shared, private_hosts=private_hosts
    )

    def md_link(m: re.Match) -> str:
        new = decide(m.group("url"))
        if new is None:
            return "" if m.group("bang") else m.group("text")
        return f"{m.group('bang')}[{m.group('text')}]({new}{m.group('title') or ''})"

    def md_refdef(m: re.Match) -> str:
        new = decide(m.group("url"))
        return f"{m.group('lead')}{new if new is not None else '#'}{m.group('rest')}"

    def md_autolink(m: re.Match) -> str:
        new = decide(m.group("url"))
        return f"<{new}>" if new else REMOVED_LINK

    def html_attr(m: re.Match) -> str:
        if m.group("attr").strip().lower().startswith("content"):
            r = _REFRESH_RE.match(_attr_url(m))
            if not r or not re.search(r"url\s*=", r.group("lead"), re.I):
                return m.group(0)  # an ordinary content="...", not a redirect
            new = decide(r.group("url").strip("'\" "))
            return m.group(0) if new is not None else "data-annals-removed"
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
    text = _CSS_URL_RE.sub(
        lambda m: m.group(0) if decide(m.group("url")) is not None else "url()", text
    )
    text = _BARE_URL_RE.sub(lambda m: decide(m.group(0)) or REMOVED_LINK, text)
    return _ANNALS_ID_RE.sub(
        lambda m: m.group(0) if shared(m.group("id")) else REMOVED_ID, text
    )


# -- the store of shares ------------------------------------------------------------


def share_url(base: str | None, token: str) -> str | None:
    """The link a recipient opens, or ``None`` when no share server is configured."""
    return f"{base.rstrip('/')}/{token}/" if base else None


class _TargetTexts(MutableMapping):
    """The files of ``shares/`` under the data root as a mapping of text, through the
    store's :class:`~annals.target.Target` (so it works over ssh). Reading a file that
    cannot be read is a ``KeyError``; records are never deleted (a revoke leaves a
    tombstone).
    """

    def __init__(self, target):
        self.target = target

    def __getitem__(self, name: str) -> str:
        try:
            return self.target.read_text(f"{SHARES}/{name}")
        except (OSError, RuntimeError):
            raise KeyError(name) from None

    def __setitem__(self, name: str, text: str) -> None:
        self.target.write_text(f"{SHARES}/{name}", text)

    def __delitem__(self, name: str) -> None:
        raise TypeError("share records are never deleted; revoke the link instead")

    def __iter__(self) -> Iterator[str]:
        return iter(self.target.list_files(SHARES))

    def __len__(self) -> int:
        return sum(1 for _ in self)


def _is_share_record(rec: dict) -> bool:
    """A record without its scope grants nothing: the link is then missing."""
    return isinstance(rec.get("docs"), dict) and isinstance(rec.get("root"), dict)


def _share_records(target) -> JsonRecords:
    """The share records, ``shares/<token>.json`` under the data root, as a mapping."""
    return JsonRecords(
        _TargetTexts(target), valid=_is_share_record, deletable=False, indent=1
    )


class Shares:
    """Create, read, list and revoke shares of a :class:`DocStore`'s documents.

    What a share reaches (its scope) is decided here; the link itself is ``links``, a
    :class:`caplinks.CapabilityLinks` over the records under ``shares/``. ``hasher``
    hashes link passwords (stdlib scrypt by default); ``clock`` returns the current UTC
    ``datetime`` (tests pin it).
    """

    def __init__(
        self,
        store: DocStore,
        *,
        hasher: PasswordHasher | None = None,
        clock: Callable[[], datetime] = now_utc,
    ):
        self.store = store
        self.clock = clock
        self.links = CapabilityLinks(
            _share_records(store.target), hasher=hasher, clock=clock
        )

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
            docs[i] = self._page_files(i, m)
        return docs

    def _page_files(self, doc_id: str, meta: dict) -> list[str]:
        """A linked page goes with what it shows, not with every file beside it."""
        shown = {meta["main"]}
        if meta["kind"] in ("md", "html"):
            try:
                text = self.store.read_text(doc_id)
                shown |= set(
                    references(text, meta["kind"], from_dir=dir_of(meta["main"]))[
                        "files"
                    ]
                )
            except (KeyError, OSError, ValueError, UnicodeDecodeError):
                pass
        return [f for f in meta.get("files", []) if f in shown]

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
        expires=DFLT_EXPIRES,
        title: str | None = None,
    ) -> dict:
        """Share a document or a group (``ref`` is its id); return the record (no hash).

        A document is shared with all its files unless ``include`` names some (the page
        itself always goes); ``include`` may also name annals pages the document links
        to, which then open inside the share. A group is shared with all its documents
        unless ``include`` names some. ``exclude`` removes files (or a group's documents).
        A linked page goes with the files it shows. ``expires`` is anything
        :func:`parse_expires` reads, 7 days by default (``"never"`` for none); ``password``
        gates the link (at least ``caplinks.MIN_PASSWORD_LEN`` characters).
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
        return self.links.create(
            {
                "title": title or default_title or ref,
                "root": {"kind": kind, "id": ref},
                "docs": docs,
            },
            password=password,
            expires=expires,
        )

    # -- the link itself, delegated to caplinks --

    def record(self, token: str) -> dict | None:
        """The stored record (hash included), revoked or not; ``None`` if there is none."""
        return self.links.record(token)

    def status(self, token: str) -> tuple[str, dict | None]:
        """``("ok" | "expired" | "missing", record)``; a revoked link is ``missing``."""
        return self.links.status(token)

    def list(self, *, all: bool = False) -> list[dict]:
        """Every share, newest first, without hashes; ``all`` adds revoked and expired."""
        return self.links.list(include_inactive=all)

    def revoke(self, token: str) -> dict:
        """End a link now (idempotent). The record stays, as a tombstone, for the list."""
        return self.links.revoke(token)

    def check_password(self, record: dict, password: str) -> bool:
        """Whether ``password`` opens ``record``."""
        return self.links.check_password(record, password)

    def unlock_value(self, record: dict) -> str:
        """The cookie value a correct password earns."""
        return self.links.unlock_value(record)

    def unlocked(self, record: dict, value: str | None, *, max_age_s: int) -> bool:
        """Whether a cookie value is a live unlock of this record (no password: always)."""
        return self.links.unlocked(record, value, max_age_s=max_age_s)


def dir_of(rel: str) -> str:
    """The directory part of a relative path, with its trailing slash (``""`` at the top)."""
    i = rel.rfind("/")
    return "" if i < 0 else rel[: i + 1]
