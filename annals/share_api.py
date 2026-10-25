"""The public share server: what a recipient of a share link can reach, and nothing else.

:func:`mk_share_api` is a FastAPI app with no login of its own, meant to be mounted where
the owner's auth gate does not reach (``annals serve`` mounts it at ``{base}/shared``; an
enlace platform runs it as a separate ``public`` app). Its only key is the link's token
(:mod:`annals.share`); every request re-reads the share record and is checked against it,
so a revoke, an expiry or a changed password takes effect on the next request::

    GET  /{token}/                  the page (or the password form); /{token}/d/{id} too
    POST /{token}/unlock            a password, form-encoded; a cookie scoped to the link
    GET  /{token}/share             the share: title, root, its documents
    GET  /{token}/docs/{id}         one shared document: its included files, its text
    GET  /{token}/raw/{id}/{path}   an included file (byte ranges); a page's text filtered
    GET  /{token}/thumb/{id}/{path} an included image, small
    GET  /ui/{name}                 the page's script and style (an allowlist)

Unknown, revoked and out-of-scope all answer 404; an expired link 410; a locked one 401.
Every response is ``noindex`` and ``no-referrer`` (as heed's review pages are), JSON and
pages are ``no-store``, and the page runs under a CSP that allows only its own script.
The page is annals' own ``app.js`` in share mode, so a shared report looks like the
owner's view of it, without the owner's controls.
"""

from __future__ import annotations

import functools
import html
import json
import secrets
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs

import anyio
import anyio.to_thread
from caplinks import RateLimiter, SlidingWindowLimiter  # noqa: F401  (re-exported)
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from annals.api import (
    RAW_SANDBOX_CSP,
    UI_DIR,
    ThumbServer,
    Thumbnailer,
    default_thumbnailer,
    media_type_of,
    raw_response,
    doc_file_path,
    doctype_guard,
)
from annals.export import export_response, file_url_builder, trusted_base
from annals.config import APP_NAME, MAX_INLINE_TEXT_BYTES, default_data_dir
from annals.share import Shares, dir_of, filter_refs
from annals.sources import with_thumb
from annals.store import PAGE_KINDS, TEXT_KINDS, DocStore, kind_of

#: on every response: never indexed, never leak the url onward (heed.review's set)
PRIVATE_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
NO_STORE = {"Cache-Control": "no-store"}
#: shared files revalidate on every view, so the per-request check always runs
SHARED_FILE_CACHE = "private, no-cache"
#: the page's assets a recipient may load (the owner's other assets stay unlisted)
SHARE_UI_FILES = frozenset({"app.js", "style.css", "marked.min.js", "purify.min.js"})
COOKIE_NAME = "annals_share"
DFLT_UNLOCK_MAX_AGE_S = 7 * 24 * 3600
#: password attempts one client may make on one link in each window
DFLT_MAX_ATTEMPTS = 10
#: wrong passwords one link takes, from everyone together, in each window; past it the
#: link refuses every try until the window moves (it bounds a distributed guess)
DFLT_MAX_LINK_FAILURES = 100
DFLT_ATTEMPT_WINDOW_S = 300.0
#: peers whose X-Forwarded-For is believed (a reverse proxy on the same machine)
DFLT_TRUSTED_PROXIES = ("127.0.0.1", "::1")
MAX_FORM_BYTES = 4096
#: a shared page is filtered whole in memory before it is sent; larger ones are refused
MAX_SHARED_PAGE_BYTES = 20_000_000


def _csp(nonce: str) -> str:
    return (
        f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
        "media-src 'self'; frame-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )


def _head(title: str, ui: str) -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        '<meta name="referrer" content="no-referrer">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f"<title>{html.escape(title)}</title>\n"
        f'<link rel="stylesheet" href="{html.escape(ui)}/style.css">\n</head>\n'
    )


def _message_page(title: str, message: str, ui: str, *, status: int) -> HTMLResponse:
    body = (
        _head(title, ui) + '<body><div class="wrap"><div class="empty share-gate">'
        f"<h2>{html.escape(title)}</h2><p>{html.escape(message)}</p></div></div></body></html>"
    )
    headers = {**NO_STORE, "Content-Security-Policy": _csp(secrets.token_urlsafe(8))}
    return HTMLResponse(body, status_code=status, headers=headers)


def _password_page(
    title: str, action: str, nxt: str, ui: str, *, error: str = "", status: int = 401
) -> HTMLResponse:
    err = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
    body = (
        _head(title, ui)
        + '<body><div class="wrap"><form class="empty share-gate" method="post" '
        f'action="{html.escape(action)}">'
        f"<h2>{html.escape(title)}</h2><p>This link is protected by a password.</p>{err}"
        '<label>Password <input type="password" name="password" required autofocus '
        'autocomplete="off"></label>'
        f'<input type="hidden" name="next" value="{html.escape(nxt)}">'
        '<button class="btn primary" type="submit">Open</button></form></div></body></html>'
    )
    headers = {**NO_STORE, "Content-Security-Policy": _csp(secrets.token_urlsafe(8))}
    return HTMLResponse(body, status_code=status, headers=headers)


def mk_share_api(
    *,
    data_dir: Path | str | None = None,
    store: DocStore | None = None,
    shares: Shares | None = None,
    thumbnailer: Thumbnailer | None | bool = True,
    rate_limiter: RateLimiter | None = None,
    link_failure_limiter: RateLimiter | None = None,
    trusted_proxies: tuple[str, ...] = DFLT_TRUSTED_PROXIES,
    private_hosts: tuple[str, ...] = (),
    unlock_max_age_s: int = DFLT_UNLOCK_MAX_AGE_S,
    cookie_secure: bool | None = None,
    title: str = APP_NAME,
) -> FastAPI:
    """The public share server over a data root; see the module docstring.

    Every argument has a working default: the local data dir, Pillow thumbnails when
    installed, a week-long unlock cookie (never past the link's expiry), and ``Secure``
    cookies whenever the request came over https (``cookie_secure`` forces it).

    Password attempts are limited twice, in memory per process unless given shared
    limiters (any ``allow(key)`` object, such as heed's Redis one): ``rate_limiter``
    counts every try of one client on one link, so a guesser locks out only itself;
    ``link_failure_limiter`` counts the wrong passwords a link takes from everyone, to
    bound a guess spread over many addresses. The client is the peer, or the address a
    ``trusted_proxies`` peer forwards. ``private_hosts`` are the owner's hosts: an
    absolute link to one of them is removed from shared text (the host a request
    arrives on always counts).
    """
    store = store or (shares.store if shares else None)
    store = store or DocStore(Path(data_dir) if data_dir else default_data_dir())
    shares = shares or Shares(store)
    limiter = rate_limiter or SlidingWindowLimiter(
        max_per_window=DFLT_MAX_ATTEMPTS, window_s=DFLT_ATTEMPT_WINDOW_S
    )
    link_failures = link_failure_limiter or SlidingWindowLimiter(
        max_per_window=DFLT_MAX_LINK_FAILURES, window_s=DFLT_ATTEMPT_WINDOW_S
    )
    locked: dict[str, float] = {}  # token -> monotonic time its lock ends
    trusted = set(trusted_proxies)
    if thumbnailer is True:
        thumbnailer = default_thumbnailer()
    thumbs = ThumbServer(store, thumbnailer)
    app = FastAPI(
        title=f"{title} share", docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.middleware("http")
    async def _private_headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in PRIVATE_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    def _root(request: Request) -> str:
        return request.scope.get("root_path", "").rstrip("/")

    def _link(request: Request, token: str) -> str:
        return f"{_root(request)}/{token}"

    def _open(token: str, request: Request) -> dict:
        """The live record, or the HTTP error a JSON or file request gets."""
        state, rec = shares.status(token)
        if state == "missing":
            raise HTTPException(404, "no such link")
        if state == "expired":
            raise HTTPException(410, "this link has expired")
        if not shares.unlocked(
            rec, request.cookies.get(COOKIE_NAME), max_age_s=unlock_max_age_s
        ):
            raise HTTPException(401, "this link needs its password")
        return rec

    def _shared_files(rec: dict, doc_id: str) -> tuple[dict, list[str]]:
        """The document's meta and the files of it the share includes (or a 404)."""
        if doc_id not in rec["docs"]:
            raise HTTPException(404, "no such document in this share")
        try:
            meta = store.meta(doc_id)
        except (KeyError, ValueError):
            raise HTTPException(404, "no such document in this share")
        if meta.get("in_trash"):
            raise HTTPException(404, "no such document in this share")
        allowed = set(rec["docs"][doc_id] or [])
        return meta, [f for f in meta.get("files", []) if f in allowed]

    def _shared_to(rec: dict, request: Request) -> Callable[[str], str | None]:
        link = _link(request, rec["token"])

        def shared(annals_id: str) -> str | None:
            if annals_id in rec["docs"]:
                return f"{link}/d/{annals_id}"
            if rec["root"].get("kind") == "group" and annals_id == rec["root"].get(
                "id"
            ):
                return f"{link}/"
            return None

        return shared

    def _client(request: Request) -> str:
        peer = request.client.host if request.client else "?"
        if peer not in trusted:
            return peer
        hops = [
            h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")
        ]
        return next((h for h in reversed(hops) if h and h not in trusted), peer)

    def _filtered(
        rec: dict, request: Request, doc_id: str, rel: str, files: list[str], text: str
    ) -> str:
        hosts = {request.headers.get("host", "")}
        hosts |= {
            h.strip() for h in request.headers.get("x-forwarded-host", "").split(",")
        }
        return filter_refs(
            text,
            kind_of(rel),
            files=files,
            shared=_shared_to(rec, request),
            from_dir=dir_of(rel),
            private_hosts=(hosts | set(private_hosts)) - {""},
        )

    # -- the page --------------------------------------------------------------------

    def _page(token: str, request: Request) -> Response:
        ui = f"{_root(request)}/ui"
        state, rec = shares.status(token)
        if state == "missing":
            return _message_page(
                "Link not found",
                "This link does not exist, or the owner has turned it off.",
                ui,
                status=404,
            )
        if state == "expired":
            return _message_page(
                "Link expired", "This link has expired.", ui, status=410
            )
        link = _link(request, token)
        if not shares.unlocked(
            rec, request.cookies.get(COOKIE_NAME), max_age_s=unlock_max_age_s
        ):
            nxt = request.url.path + (
                f"?{request.url.query}" if request.url.query else ""
            )
            return _password_page(rec.get("title") or title, f"{link}/unlock", nxt, ui)
        nonce = secrets.token_urlsafe(12)
        cfg = {
            "base": link,
            "api": link,
            "ui": ui,
            "title": rec.get("title") or title,
            "share": {"root": rec["root"], "expires": rec.get("expires")},
        }
        cfg_js = json.dumps(cfg).replace("<", "\\u003c")
        body = (
            _head(cfg["title"], ui)
            + '<body>\n<div id="app" aria-live="polite"><p class="muted">Loading…</p></div>\n'
            f'<script nonce="{nonce}">window.ANNALS = {cfg_js};</script>\n'
            f'<script src="{html.escape(ui)}/app.js"></script>\n</body>\n</html>\n'
        )
        return HTMLResponse(
            body, headers={**NO_STORE, "Content-Security-Policy": _csp(nonce)}
        )

    @app.get("/{token}", include_in_schema=False)
    def to_slash(token: str, request: Request) -> RedirectResponse:
        return RedirectResponse(f"{_link(request, token)}/", status_code=307)

    @app.get("/{token}/", include_in_schema=False)
    def page(token: str, request: Request) -> Response:
        return _page(token, request)

    @app.get("/{token}/d/{doc_id}", include_in_schema=False)
    def doc_page(token: str, doc_id: str, request: Request) -> Response:
        return _page(token, request)

    @app.post("/{token}/unlock", include_in_schema=False)
    async def unlock(token: str, request: Request) -> Response:
        ui = f"{_root(request)}/ui"
        state, rec = shares.status(token)
        if state != "ok":
            return _page(token, request)
        link = _link(request, token)
        body = await request.body()
        form = parse_qs(body[:MAX_FORM_BYTES].decode("utf-8", "replace"))
        password = (form.get("password") or [""])[0]
        nxt = (form.get("next") or [""])[0]
        if not (nxt == link or nxt.startswith(link + "/")):
            nxt = f"{link}/"
        name = rec.get("title") or title
        if not rec.get("password"):
            return RedirectResponse(nxt, status_code=303)
        if locked.get(token, 0) > time.monotonic() or not limiter.allow(
            f"{token}:{_client(request)}"
        ):
            return _password_page(
                name,
                f"{link}/unlock",
                nxt,
                ui,
                error="Too many attempts. Wait a few minutes and try again.",
                status=429,
            )
        if not shares.check_password(rec, password):
            if not link_failures.allow(token):
                locked[token] = time.monotonic() + DFLT_ATTEMPT_WINDOW_S
            return _password_page(
                name, f"{link}/unlock", nxt, ui, error="That password is not right."
            )
        max_age = shares.links.unlock_max_age(rec, max_age_s=unlock_max_age_s)
        secure = cookie_secure
        if secure is None:
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            secure = proto.split(",")[0].strip() == "https"
        response = RedirectResponse(nxt, status_code=303, headers=NO_STORE)
        response.set_cookie(
            COOKIE_NAME,
            shares.unlock_value(rec),
            max_age=max_age,
            path=link,
            httponly=True,
            samesite="lax",
            secure=secure,
        )
        return response

    # -- the data the page reads --------------------------------------------------------

    @app.get("/{token}/share")
    def share_info(token: str, request: Request) -> JSONResponse:
        """The share as the recipient sees it: its title, root, and documents."""
        rec = _open(token, request)
        docs = []
        for doc_id in rec["docs"]:
            try:
                meta, files = _shared_files(rec, doc_id)
            except HTTPException:
                continue  # trashed or deleted since: it simply is not there
            docs.append(_public_meta(meta, files, list_only=True))
        out = {
            "title": rec.get("title"),
            "root": rec["root"],
            "expires": rec.get("expires"),
            "created": rec.get("created"),
            "docs": docs,
        }
        return JSONResponse(out, headers=NO_STORE)

    @app.get("/{token}/docs/{doc_id}")
    def shared_doc(token: str, doc_id: str, request: Request) -> JSONResponse:
        """One shared document: only its included files, and its text filtered."""
        rec = _open(token, request)
        meta, files = _shared_files(rec, doc_id)
        out = _public_meta(meta, files)
        main_size = (meta.get("sizes") or {}).get(meta["main"], 0)
        if (
            out["kind"] in TEXT_KINDS
            and meta["main"] in files
            and main_size <= MAX_INLINE_TEXT_BYTES
        ):
            try:
                text = store.read_text(doc_id)
            except (KeyError, OSError, ValueError):
                raise HTTPException(404, "no readable text for this document")
            out["text"] = _filtered(rec, request, doc_id, meta["main"], files, text)
        return JSONResponse(out, headers=NO_STORE)

    def _shared_path(token: str, doc_id: str, rel: str, request: Request):
        rec = _open(token, request)
        _, files = _shared_files(rec, doc_id)
        if rel not in files:
            raise HTTPException(404, "no such file in this share")
        return rec, files, doc_file_path(store, doc_id, rel)

    @app.get("/{token}/raw/{doc_id}/{rel:path}")
    def shared_raw(token: str, doc_id: str, rel: str, request: Request) -> Response:
        """An included file as itself (byte ranges); a page's references filtered."""
        rec, files, path = _shared_path(token, doc_id, rel, request)
        if _is_text(rel):
            # text is always sent filtered, never as the bytes on disk (a link or an id
            # in it may name what is not shared): too big to filter is too big to share
            if path.stat().st_size > MAX_SHARED_PAGE_BYTES:
                raise HTTPException(413, "this page is too large to share")
            text = path.read_text(encoding="utf-8", errors="replace")
            body = _filtered(rec, request, doc_id, rel, files, text).encode("utf-8")
            if kind_of(rel) == "html":
                body = doctype_guard(body)
            media_type = media_type_of(rel)
            if "charset" not in media_type:
                media_type += "; charset=utf-8"
            headers = {
                "Cache-Control": SHARED_FILE_CACHE,
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": RAW_SANDBOX_CSP,
            }
            return Response(body, media_type=media_type, headers=headers)
        return raw_response(path, rel, cache=SHARED_FILE_CACHE)

    @app.get("/{token}/export/{doc_id}")
    async def shared_export(
        token: str,
        doc_id: str,
        request: Request,
        format: str = "pdf",
        file: str = "",
        base: str = "",
    ) -> Response:
        """The shared page as a ``.md`` or ``.pdf``: its filtered text, its included files."""
        rec = _open(token, request)
        meta, files = _shared_files(rec, doc_id)
        rel = file or meta["main"]
        if rel not in files or kind_of(rel) != "md":
            raise HTTPException(404, "no markdown file to export in this share")
        path = doc_file_path(store, doc_id, rel)
        if path.stat().st_size > MAX_SHARED_PAGE_BYTES:
            raise HTTPException(413, "this page is too large to export")
        text = _filtered(
            rec,
            request,
            doc_id,
            rel,
            files,
            await anyio.to_thread.run_sync(
                functools.partial(path.read_text, encoding="utf-8", errors="replace")
            ),
        )
        link = trusted_base(request, base)
        return await anyio.to_thread.run_sync(
            functools.partial(
                export_response,
                format,
                title=meta.get("title") or doc_id,
                text=text,
                rel=rel,
                files=files,
                open_file=functools.partial(doc_file_path, store, doc_id),
                file_url=file_url_builder(link, doc_id),
                created=meta.get("created", ""),
            )
        )

    @app.get("/{token}/thumb/{doc_id}/{rel:path}")
    async def shared_thumb(
        token: str, doc_id: str, rel: str, request: Request, w: int = 320
    ) -> Response:
        """An included image, small (the gallery of a shared folder)."""
        import anyio

        _, _, path = await anyio.to_thread.run_sync(
            _shared_path, token, doc_id, rel, request
        )
        return await thumbs.respond(
            path,
            doc_id,
            rel,
            w,
            fallback=lambda: shared_raw(token, doc_id, rel, request),
            cache=SHARED_FILE_CACHE,
        )

    @app.get("/ui/{name}")
    def ui_asset(name: str) -> Response:
        """The page's script and style; nothing else of the owner's page is served here."""
        if name not in SHARE_UI_FILES or not (UI_DIR / name).is_file():
            raise HTTPException(404)
        media = "text/css" if name.endswith(".css") else "text/javascript"
        return Response(
            (UI_DIR / name).read_bytes(),
            media_type=media,
            headers={"Cache-Control": "no-cache"},
        )

    app.state.shares = shares
    return app


def _is_text(rel: str) -> bool:
    """Whether a file is text a reference could hide in (markdown, html, text, svg)."""
    return kind_of(rel) in PAGE_KINDS | TEXT_KINDS or rel.lower().endswith(".svg")


#: the fields of a document's meta a recipient may see (no source host or cwd, no tags)
_PUBLIC_META_KEYS = ("id", "title", "kind", "main", "created")


def _public_meta(meta: dict, files: list[str], *, list_only: bool = False) -> dict:
    out = {k: meta.get(k) for k in _PUBLIC_META_KEYS}
    sizes = {f: (meta.get("sizes") or {}).get(f, 0) for f in files}
    out["size"] = sum(sizes.values())
    out["files"] = files
    with_thumb(out)
    if out.get("thumb") not in files:
        out["thumb"] = None
    if out["kind"] != "folder" and meta.get("main") not in files:
        out["kind"] = "folder"  # its page is not shared: show what is, as a folder
    if list_only:
        out["n_files"] = len(files)
        out.pop("files")
        return out
    out["sizes"] = sizes
    out["file_kinds"] = {f: kind_of(f) for f in files}
    return out
