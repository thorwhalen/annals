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

import re
from collections.abc import Iterator, MutableMapping
from html import escape as _escape
from html.parser import HTMLParser
from datetime import datetime
from typing import Callable, Iterable

from caplinks import (  # noqa: F401  (ScryptHasher, is_expired, parse_expires: re-exported)
    DFLT_EXPIRES,
    CapabilityLinks,
    JsonRecords,
    PasswordHasher,
    ScryptHasher,
    is_expired,
    now_utc,
    parse_expires,
)

from annals.pagepdf import button_href, strip_button
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
#: an absolute link to an annals document or group page (``.../d/<id>``, ``.../g/<id>``)
_ANNALS_PAGE_URL_RE = re.compile(
    rf"https?://[^\s<>()\"'\]\[*`,|]+?/(?:d|g)/{ANNALS_ID}(?![\w-])"
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
_MD_AUTOLINK_RE = re.compile(r"<(?P<url>(?:https?:)?/[^>\s]*)>", re.I)
_HTML_ATTR_RE = re.compile(
    r"(?P<attr>\b(?:src|href|poster|data|action|formaction|srcset|imagesrcset|xlink:href|ping"
    r"|background|cite|longdesc|usemap|manifest|codebase|archive|content|srcdoc)\s*=\s*)"
    r"(?:\"(?P<u1>[^\"]*)\"|'(?P<u2>[^']*)'|(?P<u3>[^\s>]+))",
    re.I,
)
_BARE_URL_RE = re.compile(
    rf"(?:https?://|/)[^\s<>()\"'\]]*?/(?:d|g|raw|thumb|docs|groups)/{ANNALS_ID}[^\s<>()\"'\]]*"
)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
#: ``<meta http-equiv=refresh content="0;url=...">``: the one ``content`` that is a url
_REFRESH_RE = re.compile(r"^(?P<lead>\s*\d*\s*;?\s*url\s*=\s*)(?P<url>.*)$", re.I)


#: attributes whose value is a url (or a list of them), read off a parsed start tag
_URL_ATTRS = frozenset(
    "src href poster data action formaction srcset imagesrcset xlink:href ping background"
    " cite longdesc usemap manifest codebase archive".split()
)


class _StartTags(HTMLParser):
    """The start tags of an html text as ``(start, end, name, [(attr, value), ...])``.

    Offsets are into the text as given. The parser reads attributes the way a browser
    does (quoting, entities, repeated and glued attributes), which a regex cannot.
    """

    def __init__(self, text: str):
        super().__init__(convert_charrefs=False)
        self.tags: list[tuple[int, int, list]] = []
        lines = text.split("\n")
        self._line_start = [0]
        for line in lines[:-1]:
            self._line_start.append(self._line_start[-1] + len(line) + 1)
        self.feed(text)
        self.close()

    def _tag(self, attrs):
        line, col = self.getpos()
        start = self._line_start[line - 1] + col
        self.tags.append((start, start + len(self.get_starttag_text()), attrs))

    handle_starttag = handle_startendtag = lambda self, tag, attrs: self._tag(attrs)


def _filter_html_attrs(text: str, decide: Callable[[str], str | None]) -> str:
    """``text`` with the url attributes of its tags decided by ``decide`` (or removed).

    Tags are found by an html parser, so the attribute the filter judges is the attribute
    a browser follows. What the parser does not see as a tag (comments, script and style
    text, stray text) goes through the strict regex, which only ever removes more.
    """
    out: list[str] = []
    pos = 0
    for start, end, attrs in _StartTags(text).tags:
        if start < pos:
            continue
        out.append(_HTML_ATTR_RE.sub(lambda m: _regex_attr(m, decide), text[pos:start]))
        raw = text[start:end]
        out.append(_rewrite_tag(raw, attrs, decide))
        pos = end
    out.append(_HTML_ATTR_RE.sub(lambda m: _regex_attr(m, decide), text[pos:]))
    return "".join(out)


def _same_url(a: str, b: str) -> bool:
    from html import unescape

    return unescape(a).strip() == unescape(b).strip()


_CSS_ESCAPE_RE = re.compile(r"\\(?:([0-9a-f]{1,6})[ \t\n\r\f]?|(.))", re.I | re.S)
#: an absolute url written inside script text (an ``on*`` or ``data-*`` attribute)
_SCRIPT_URL_RE = re.compile(r"(?:https?:)?//[^\s'\"<>)\\]+", re.I)


def _css_unescape(css: str) -> str:
    """``css`` with its escapes decoded (``u\\72 l(`` is ``url(``), as a browser reads it."""

    def one(m: re.Match) -> str:
        if m.group(1):
            n = int(m.group(1), 16)
            return chr(n) if 0 < n <= 0x10FFFF else "\ufffd"
        return m.group(2)

    return _CSS_ESCAPE_RE.sub(one, css)


_URL_FUNCS = frozenset(
    "image-set -webkit-image-set cross-fade -webkit-cross-fade src image".split()
)
_STYLE_CLOSE_RE = re.compile(r"</style(?=[\s/>])", re.I)
_STYLE_OPEN_RE = re.compile(r"<style(?=[\s/>])[^>]*>", re.I)


def _filter_css(
    css: str, decide, *, comments: bool = True, functions: bool = True
) -> str:
    """``css`` without the urls ``decide`` refuses, in one linear pass.

    Finds ``url(...)`` (quoted or not, comments inside), the string after ``@import`` and,
    with ``functions``, the strings inside ``image-set()`` and its kin. ``comments=False``
    (for text that is only partly css) does not skip ``/* */``: it may look at more, never
    at less. Expects decoded css: see :func:`_css_clean`.
    """
    out: list[str] = []
    i, n = 0, len(css)
    stack: list[str] = []
    last = ""  # the last significant token, for ``@import "x"``

    def skip_ws(j: int) -> int:
        while j < n:
            if css[j].isspace():
                j += 1
            elif css.startswith("/*", j):
                k = css.find("*/", j + 2)
                j = n if k < 0 else k + 2
            else:
                break
        return j

    def string_end(j: int) -> int:  # css[j] is the quote
        q = css[j]
        j += 1
        while j < n and css[j] != q and css[j] != "\n":
            j += 2 if css[j] == "\\" else 1
        return min(j + 1, n)

    while i < n:
        c = css[i]
        if comments and css.startswith("/*", i):
            k = css.find("*/", i + 2)
            k = n if k < 0 else k + 2
            out.append(css[i:k])
            i = k
        elif c in "\"'":
            e = string_end(i)
            in_url = last == "@import" or (
                functions and stack and stack[-1] in _URL_FUNCS
            )
            if in_url and decide(css[i + 1 : max(i + 1, e - 1)]) is None:
                out.append(c + c)
            else:
                out.append(css[i:e])
            last, i = "str", e
        elif css[i : i + 4].lower() == "url(" and (i == 0 or not css[i - 1].isalnum()):
            j = skip_ws(i + 4)
            if j < n and css[j] in "\"'":
                e = string_end(j)
                url, k = css[j + 1 : max(j + 1, e - 1)], skip_ws(e)
            else:
                k = j
                while k < n and css[k] not in ")\"'" and not css[k].isspace():
                    k += 1
                url, k = css[j:k], skip_ws(k)
            if k < n and css[k] == ")":
                k += 1
            if decide(url) is None:
                out.append("url()")
            else:
                out.append(css[i:k])
            last, i = "url", k
        elif css[i : i + 7].lower() == "@import":
            out.append(css[i : i + 7])
            last, i = "@import", i + 7
        elif c == "(":
            m = re.search(r"[A-Za-z0-9_-]+$", css[max(0, i - 24) : i])
            stack.append(m.group(0).lower() if m else "")
            out.append(c)
            last, i = "(", i + 1
        elif c == ")":
            if stack:
                stack.pop()
            out.append(c)
            last, i = ")", i + 1
        else:
            out.append(c)
            if not c.isspace():
                last = c
            i += 1
    return "".join(out)


def _css_clean(css: str, decide, **kw) -> str:
    """The css with its refused urls removed.

    The decision is made on the css as a browser decodes it (escapes, and entities for
    svg). When the owner wrote it with no escapes the removal is in place; when escapes
    hide a refused url the whole text goes: decoded text is never written back, since a
    decoded ``\\3c`` is markup.
    """
    from html import unescape

    decoded = _css_unescape(unescape(css)) if ("\\" in css or "&" in css) else css
    if decoded == css:
        return _filter_css(css, decide, **kw)
    return "" if _filter_css(decoded, decide, **kw) != decoded else css


def _style_elements(text: str, decide) -> str:
    """``text`` with the css of every ``<style>`` element cleaned (one pass; an element
    with no end runs to the end of the text, as in a browser)."""
    out, pos = [], 0
    while (o := _STYLE_OPEN_RE.search(text, pos)) is not None:
        c = _STYLE_CLOSE_RE.search(text, o.end())
        end = c.start() if c else len(text)
        out.append(text[pos : o.end()])
        out.append(_css_clean(text[o.end() : end], decide))
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _script_refused(value: str, decide) -> bool:
    """True when script text (an event handler, a data attribute) names an absolute url
    the share may not reach."""
    value = value.replace("\\/", "/")  # json writes a slash as \\/
    return any(decide(u) is None for u in _SCRIPT_URL_RE.findall(value))


def _decide_attr(
    name: str, value: str | None, decide, *, refresh: bool = False
) -> tuple[str | None, bool]:
    """``(new value, keep)`` for one attribute of a tag (``value`` is already decoded)."""
    name = name.lower()
    if value is None:
        return value, True
    if name == "style":
        return _css_clean(value, decide), True
    if name.startswith(
        ("on", "data-")
    ):  # script text: refused only when it names a url
        return value, not _script_refused(value, decide)
    if name == "srcdoc":  # a whole document inside an attribute
        return _filter_html_attrs(value, decide), True
    if name == "content":
        if not refresh:
            return value, True  # an ordinary content="...", not a redirect
        r = _REFRESH_RE.match(value)
        new = decide(r.group("url").strip("'\" ")) if r else None
        return value, new is not None
    if name not in _URL_ATTRS:
        return value, True
    if name in ("srcset", "imagesrcset"):
        urls = [c.strip().split()[0] for c in value.split(",") if c.strip()]
    elif name == "ping":
        urls = value.split()
    else:
        urls = [value]
    news = [decide(u) for u in urls]
    if any(n is None for n in news):
        return value, False
    if len(urls) == 1 and not _same_url(news[0], urls[0]):
        return news[0], True  # an annals id mapped to where the recipient opens it
    return value, True


def _rewrite_tag(raw: str, attrs, decide) -> str:
    refresh = any(
        n.lower() == "http-equiv" and (v or "").strip().lower() == "refresh"
        for n, v in attrs
    )
    verdicts = [(n, *_decide_attr(n, v, decide, refresh=refresh)) for n, v in attrs]
    if all(keep and new == v for (n, new, keep), (_, v) in zip(verdicts, attrs)):
        return raw  # nothing changes: the owner's markup, as written
    m = re.match(r"<\s*([^\s/>]+)", raw)
    name = m.group(1) if m else ""
    parts = []
    for n, new, keep in verdicts:
        found = re.search(rf"(?<=[\s/\"'])({re.escape(n)})(?=[\s/=>])", raw, re.I)
        n = found.group(1) if found else n  # the name as the owner wrote its case
        if not keep:
            parts.append("data-annals-removed")
        elif new is None:
            parts.append(n)
        else:
            parts.append(f'{n}="{_escape(new, quote=True)}"')
    tail = "/>" if raw.rstrip().endswith("/>") else ">"
    return f"<{name}{''.join(' ' + p for p in parts)}{tail}"


def _regex_attr(m: re.Match, decide) -> str:
    if m.group("attr").strip().lower().startswith("content"):
        r = _REFRESH_RE.match(_attr_url(m))
        if not r or not re.search(r"url\s*=", r.group("lead"), re.I):
            return m.group(0)
        return (
            m.group(0)
            if decide(r.group("url").strip("'\" ")) is not None
            else "data-annals-removed"
        )
    urls = _srcset_urls(m)
    news = [decide(u) for u in urls]
    if any(n is None for n in news):
        return "data-annals-removed"
    if len(urls) == 1 and not _same_url(news[0], urls[0]):
        return f'{m.group("attr")}"{_escape(news[0], quote=True)}"'
    return m.group(0)


def annals_urls(text: str) -> list[str]:
    """The absolute links to annals document and group pages in ``text``, once each, in order.

    Any host: which annals a link belongs to is the reader's config to decide
    (:func:`annals.config.link_target`). Relative links (``../d/<id>``) are not found:
    a document's own links to its annals are absolute, as ``annals publish`` prints them.

    >>> annals_urls("see **[map](https://a.example.io/annals/d/20261119-075018-the-map-4a58)**, "
    ...             "<https://b.example.com/annals/g/20261117-163049-set?f=x> and "
    ...             "https://a.example.io/annals/d/20261119-075018-the-map-4a58 again")
    ['https://a.example.io/annals/d/20261119-075018-the-map-4a58', 'https://b.example.com/annals/g/20261117-163049-set']
    """
    return list(dict.fromkeys(m.group(0) for m in _ANNALS_PAGE_URL_RE.finditer(text)))


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


def ref_decider(
    *,
    from_dir: str,
    files: set[str],
    shared: Callable[[str], str | None],
    private_hosts: Iterable[str] = (),
) -> Callable[[str], str | None]:
    """``url -> new url`` (often the same) or ``None`` (remove it).

    The one rule of what a shared text may point at; :func:`filter_refs` applies it to
    the references it finds in text, :mod:`annals.notebook` to a rendered page's links.
    """
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
                host = _url_host(url)
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


def _url_host(url: str) -> str:
    """The host a browser would connect to for ``url``: backslashes, a scheme without
    slashes, userinfo, a port, a trailing dot and percent-escapes all read as a browser does."""
    from urllib.parse import unquote

    rest = re.sub(r"^[a-z][a-z0-9+.-]*:", "", url.replace("\\", "/"), flags=re.I)
    if _SCHEME_RE.match(url) and not url.lower().startswith(("http", "ws", "ftp")):
        rest = url.replace("\\", "/")
        rest = rest if rest.startswith("//") else "//" + rest.split(":", 1)[1]
    netloc = re.split(r"[/?#]", rest.lstrip("/"), maxsplit=1)[0]
    host = unquote(netloc.rsplit("@", 1)[-1]).lower()
    return re.sub(r":\d*$", "", host).rstrip(".")


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
    name = m.group("attr").strip().lower().rstrip("= \t")
    if name.endswith("srcset"):
        return [c.strip().split()[0] for c in value.split(",") if c.strip()]
    if name == "ping":
        return value.split()
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
    decide = ref_decider(
        from_dir=from_dir, files=set(files), shared=shared, private_hosts=private_hosts
    )
    if (pdf := button_href(text)) is not None and decide(pdf) is None:
        text = strip_button(text)  # a PDF button whose PDF is not shared: no dead chip

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

    if kind == "md":
        text = _MD_LINK_RE.sub(md_link, text)
        text = _MD_REFDEF_RE.sub(md_refdef, text)
        text = _MD_AUTOLINK_RE.sub(md_autolink, text)
    text = _filter_html_attrs(text, decide)
    text = _filter_css(text, decide, comments=False, functions=False)
    text = _style_elements(text, decide)
    text = _BARE_URL_RE.sub(lambda m: decide(m.group(0)) or REMOVED_LINK, text)
    return remove_unshared_ids(text, shared)


def remove_unshared_ids(text: str, shared: Callable[[str], str | None]) -> str:
    """``text`` with every annals id that ``shared`` does not map replaced by a marker."""
    return _ANNALS_ID_RE.sub(
        lambda m: m.group(0) if shared(m.group("id")) else REMOVED_ID, text
    )


# -- the store of shares ------------------------------------------------------------


def share_url(base: str | None, token: str) -> str | None:
    """The link a recipient opens, or ``None`` when no share server is configured."""
    return f"{base.rstrip('/')}/{token}/" if base else None


def share_links(base: str | None, token: str) -> dict[str, str]:
    """The forms of one share link: ``page`` (people, and fetchers that run no script),
    ``markdown`` (agents: the whole share as one text) and ``pdf`` (images inside, or for an
    upload); empty when no share server is configured. :mod:`annals.share_page`."""
    page = share_url(base, token)
    if page is None:
        return {}
    return {"page": page, "markdown": f"{page}share.md", "pdf": f"{page}share.pdf"}


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
        except (OSError, RuntimeError, ValueError):  # ValueError: outside the root
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
        if meta.get("in_trash"):
            raise ValueError("restore it before sharing")
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
        self,
        gid: str,
        include: list[str] | None,
        exclude: list[str],
        files_of: Callable[[dict], list[str]] | None = None,
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
                docs[i] = list(files_of(m) if files_of else m.get("files", []))
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
        files_of: Callable[[dict], list[str]] | None = None,
    ) -> dict:
        """Share a document or a group (``ref`` is its id); return the record (no hash).

        A document is shared with all its files unless ``include`` names some (the page
        itself always goes); ``include`` may also name annals pages the document links
        to, which then open inside the share. A group is shared with all its documents
        unless ``include`` names some. ``exclude`` removes files (or a group's documents).
        A linked page goes with the files it shows. ``expires`` is anything
        :func:`parse_expires` reads, 7 days by default (``"never"`` for none); ``password``
        gates the link (at least ``caplinks.MIN_PASSWORD_LEN`` characters).
        ``files_of(meta)`` narrows which files of each of a group's documents go (all of
        them by default; :func:`annals.notebook.source_scope` keeps only the pages and
        what they show).
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
            docs = self._group_scope(ref, include, exclude, files_of)
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

    def included(self, record: dict) -> list[tuple[dict, list[str]]]:
        """``(meta, files)`` for each document of a share still there, in the share's order.

        ``files`` are the document's files the share includes; a document deleted or in
        the bin since the link was made is left out.
        """
        out = []
        for doc_id, files in record["docs"].items():
            try:
                meta = self.store.meta(doc_id)
            except (KeyError, ValueError):
                continue
            if meta.get("in_trash"):
                continue
            allowed = set(files or [])
            out.append((meta, [f for f in meta.get("files", []) if f in allowed]))
        return out

    # -- the link itself, delegated to caplinks --

    def _in_sight(self, record: dict | None) -> bool:
        """Whether the store shows everything a share reaches. Over a store that hides some
        documents (:class:`annals.store.HidingStore`), a share reaching one is hidden too:
        its token would open what the store hides."""
        hides = getattr(self.store, "hides", None)
        if hides is None or not isinstance(record, dict):
            return True
        root = record.get("root") or {}
        ids = {*(record.get("docs") or {}), root.get("id")}
        return not any(hides(i) for i in ids if isinstance(i, str))

    def record(self, token: str) -> dict | None:
        """The stored record (hash included), revoked or not; ``None`` if there is none."""
        rec = self.links.record(token)
        return rec if self._in_sight(rec) else None

    def status(self, token: str) -> tuple[str, dict | None]:
        """``("ok" | "expired" | "missing", record)``; a revoked link is ``missing``."""
        state, rec = self.links.status(token)
        return (state, rec) if self._in_sight(rec) else ("missing", None)

    def list(self, *, all: bool = False) -> list[dict]:
        """Every share, newest first, without hashes; ``all`` adds revoked and expired."""
        return [r for r in self.links.list(include_inactive=all) if self._in_sight(r)]

    def revoke(self, token: str) -> dict:
        """End a link now (idempotent). The record stays, as a tombstone, for the list."""
        if not self._in_sight(self.links.record(token)):
            raise KeyError(token)
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
