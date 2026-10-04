"""The HTTP surface: a JSON API over a :class:`annals.store.DocStore`, plus the page.

Two factories, one implementation:

* :func:`mk_api` is the API alone, rooted at ``/``: list, search, read, trash, restore,
  purge, groups, raw files (``/raw/{id}/{path}``, with byte ranges so video seeks) and the
  page's assets (``/ui/...``). A host platform mounts it under its own prefix and gates it
  with its own login; that is how annals runs as an enlace app (``/api/annals``), with
  the page shell from :func:`page_html` as the app's frontend.
* :func:`mk_app` is the standalone server ``annals serve`` runs: the API at
  ``{base}/api``, the page at ``{base}/``, ``{base}/d/{id}``, ``{base}/g/{gid}``,
  ``{base}/trash`` (one html shell; the browser routes), and an auth gate around it all
  (see :mod:`annals.auth`).

The reader's actions are the three the recycle bin needs. Publishing is not an HTTP
operation here: it is a file write (see :mod:`annals.target`), which keeps this surface
small and the documents' lifecycle independent of whatever serves them.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from annals.auth import Authorizer, authorizer_from_env, no_auth
from annals.config import APP_NAME, DFLT_SERVE_PORT, ENV_DATA_DIR, MAX_INLINE_TEXT_BYTES, default_data_dir
from annals.store import DOCS, TRASH, DocStore, TEXT_KINDS, kind_of
from annals.target import check_rel

UI_DIR = Path(__file__).parent / "data" / "ui"
DFLT_BASE_PATH = f"/{APP_NAME}"
NO_STORE = {"Cache-Control": "no-store"}
# A document never changes after it is published (a new publish is a new id), so its
# files can be cached by the reader's browser; "private" keeps shared caches out of it.
RAW_CACHE = "private, max-age=86400"
# Every raw file is served under a sandbox policy, so a file that a browser renders as a
# document (html, svg, any +xml, whatever the host's mime table says) cannot read the
# platform's cookies or call any app's API on this shared origin. Harmless for media used
# by <img>/<video>. PDF alone is exempt: its built-in viewer refuses a sandboxed document.
NO_SANDBOX_TYPES = frozenset({"application/pdf"})
RAW_SANDBOX_CSP = "sandbox allow-scripts allow-popups allow-forms allow-modals allow-downloads"
# Types a browser would otherwise download or mis-render; served as text so a viewer can
# show them (markdown and friends are text to a reader).
#: thumbnail widths served; a request snaps up to the nearest, so the cache stays bounded
THUMB_WIDTHS = (160, 320, 640)
THUMB_CACHE = "cache/thumbs"
#: rasters Pillow can shrink; anything else (svg) is served as itself
THUMBNAILABLE = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif"})
TEXT_TYPE_OVERRIDES = {".md": "text/markdown; charset=utf-8", ".markdown": "text/markdown; charset=utf-8"}


class _RevalidatingStatic(StaticFiles):
    """The page's assets: always revalidated, so a package upgrade reaches the browser."""

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


Thumbnailer = Callable[[Path, Path, int], bool]


#: at most this many thumbnails are made at once: the worker threads are the platform's
THUMB_CONCURRENCY = 2
#: refuse to decode images larger than this (pixels, after a JPEG's reduced-size draft)
THUMB_MAX_PIXELS = 60_000_000
#: when a thumbnail cannot be made, the original is sent only if it is at most this big
THUMB_FALLBACK_MAX_BYTES = 5_000_000
_TOO_BIG_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160"><rect width="160" height="160" fill="#888" '
    'opacity=".25"/><text x="80" y="76" text-anchor="middle" font-family="sans-serif" '
    'font-size="14" fill="#666">large image</text><text x="80" y="96" text-anchor="middle" font-family="sans-serif" '
    'font-size="12" fill="#666">tap to open</text></svg>'
)


def pillow_thumbnailer(src: Path, dst: Path, width: int) -> bool:
    """Shrink ``src`` to ``width`` pixels wide as webp at ``dst``; ``False`` if it cannot.

    Bounded, because it runs on threads every app shares: a JPEG is decoded at reduced
    size (``draft``) before anything else, nothing over ``THUMB_MAX_PIXELS`` is decoded
    after that, and it shrinks before rotating so the full-size image is never copied.
    The caller bounds how many run at once (see ``mk_api``).
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return False
    if dst.is_file():  # made by another request while this one waited
        return True
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)  # the cap below decides
            with Image.open(src) as im:
                im.draft("RGB", (width, width * 4))  # JPEG: decode at 1/2..1/8 scale
                if im.width * im.height > THUMB_MAX_PIXELS:
                    return False
                im.thumbnail((width, width * 4))
                im = ImageOps.exif_transpose(im)
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA")
                dst.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=dst.parent, suffix=".tmp")
                try:
                    with os.fdopen(fd, "wb") as f:
                        im.save(f, "WEBP", quality=80, method=4)
                    os.replace(tmp, dst)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
        return True
    except (OSError, ValueError, Image.DecompressionBombError):
        return False


def _default_thumbnailer() -> Thumbnailer | None:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return None
    return pillow_thumbnailer


def _list_meta(meta: dict) -> dict:
    """A listing row: the meta without its per-file tables (a folder can hold thousands)."""
    row = _with_thumb(dict(meta))
    row["n_files"] = len(row.pop("files", []) or [])
    row.pop("sizes", None)
    return row


def _media_type(rel: str) -> str:
    override = TEXT_TYPE_OVERRIDES.get(Path(rel).suffix.lower())
    return override or mimetypes.guess_type(rel)[0] or "application/octet-stream"


def _with_thumb(meta: dict) -> dict:
    """Add ``thumb`` (the first image, main file first) and fix pre-media kinds.

    Documents published before media kinds existed say ``file`` for an image or a video;
    their kind is recomputed from the main file so they show inline too.
    """
    if meta.get("kind") == "file" and meta.get("main"):
        meta["kind"] = kind_of(meta["main"])
    files = [meta["main"]] + meta.get("files", []) if meta.get("main") else meta.get("files", [])
    meta["thumb"] = next((f for f in files if kind_of(f) == "image"), None)
    return meta


def mk_api(
    *,
    data_dir: Path | str | None = None,
    store: DocStore | None = None,
    thumbnailer: Thumbnailer | None | bool = True,
    title: str = APP_NAME,
) -> FastAPI:
    """The JSON API, raw files and page assets, rooted at ``/``, with no auth of its own.

    Mount it behind a login (enlace_auth does this for an enlace app), or use
    :func:`mk_app`, which adds the gate. Every argument has a working default.
    ``thumbnailer`` shrinks gallery images: Pillow when it is installed (``True``), any
    ``(src, dst, width) -> bool`` callable, or ``None`` to always serve the original.
    """
    store = store or DocStore(Path(data_dir) if data_dir else default_data_dir())
    if thumbnailer is True:
        thumbnailer = _default_thumbnailer()
    api = FastAPI(title=f"{title} api", docs_url=None, redoc_url=None, openapi_url=None)
    # No swagger: its /docs route would shadow ours.

    @api.get("/health")
    def health() -> dict:
        """Cheap liveness probe (also says which data dir is served)."""
        return {"ok": True, "target": store.target.describe()}

    @api.get("/docs")
    def list_docs(q: str = "", trash: bool = False) -> dict:
        """All documents (or the bin), newest first; ``q`` filters by words."""
        docs = store.search(q, trash=trash) if q else store.list(trash=trash)
        return {"docs": [_list_meta(m) for m in docs]}

    @api.get("/docs/{doc_id}")
    def get_doc(doc_id: str) -> dict:
        """One document's meta, each file's kind, and its text inline when markdown or text."""
        meta = _with_thumb(_meta_or_404(store, doc_id))
        meta["file_kinds"] = {f: kind_of(f) for f in meta.get("files", [])}
        if meta["kind"] in TEXT_KINDS and meta.get("size", 0) <= MAX_INLINE_TEXT_BYTES:
            meta["text"] = store.read_text(doc_id)
        return meta

    @api.post("/docs/{doc_id}/trash")
    def trash_doc(doc_id: str) -> dict:
        """Move a document to the recycle bin."""
        _meta_or_404(store, doc_id)
        return store.trash(doc_id)

    @api.post("/docs/{doc_id}/restore")
    def restore_doc(doc_id: str) -> dict:
        """Bring a document back from the bin."""
        _meta_or_404(store, doc_id)
        return store.restore(doc_id)

    @api.delete("/docs/{doc_id}")
    def purge_doc(doc_id: str) -> dict:
        """Delete forever; only allowed for a document already in the bin."""
        _meta_or_404(store, doc_id)
        try:
            store.purge(doc_id)
        except PermissionError as e:
            raise HTTPException(409, str(e))
        root = _local_root()
        if root is not None:
            shutil.rmtree(root / THUMB_CACHE / doc_id, ignore_errors=True)
        return {"ok": True, "id": doc_id}

    @api.get("/groups")
    def list_groups() -> dict:
        """Every group, newest first."""
        return {"groups": store.list_groups()}

    @api.get("/groups/{gid}")
    def get_group(gid: str) -> dict:
        """A group with the meta of each document it names (missing ones are skipped)."""
        try:
            group = store.group(gid)
        except (KeyError, ValueError):
            raise HTTPException(404, "no such group")
        docs = []
        for i in group["docs"]:
            try:
                docs.append(_list_meta(store.meta(i)))
            except (KeyError, ValueError):
                continue
        return {**group, "items": docs}

    def _local_root() -> Path | None:
        return store.target.local_path(".")

    def _file_path(doc_id: str, rel: str) -> Path:
        """The file on disk, or a 404: it must be listed in the meta AND stay inside the
        document's directory (meta.json is written by the publisher, so it is not trusted
        to keep paths in bounds)."""
        meta = _meta_or_404(store, doc_id)
        if rel not in meta["files"]:
            raise HTTPException(404, "no such file in document")
        try:
            check_rel(rel)
        except ValueError:
            raise HTTPException(404, "no such file in document")
        doc_rel = f"{TRASH if meta['in_trash'] else DOCS}/{doc_id}"
        doc_dir = store.target.local_path(doc_rel)
        path = store.target.local_path(f"{doc_rel}/{rel}")
        if doc_dir is None:
            raise HTTPException(501, "raw files are served from a local data dir only")
        if path is None or not path.is_relative_to(doc_dir) or not path.is_file():
            raise HTTPException(404, "file missing on disk")
        return path

    @api.get("/raw/{doc_id}/{rel:path}")
    def raw_file(doc_id: str, rel: str) -> Response:
        """A document's file as itself, streamed, with byte ranges (video and audio seek).

        ``FileResponse`` answers ``Range`` with ``206 Partial Content`` and never loads the
        file into memory, which is what a ``<video>`` element needs (Safari will not play
        without ranges).
        """
        path = _file_path(doc_id, rel)
        media_type = _media_type(rel)
        headers = {"Cache-Control": RAW_CACHE, "X-Content-Type-Options": "nosniff"}
        if media_type.split(";")[0] not in NO_SANDBOX_TYPES:
            headers["Content-Security-Policy"] = RAW_SANDBOX_CSP
        return FileResponse(path, media_type=media_type, headers=headers)

    # Waiting for a thumbnail slot must not hold one of the threads every app shares, so
    # the endpoint is async and only the work itself goes to a thread, two at a time.
    thumb_limiter = anyio.CapacityLimiter(THUMB_CONCURRENCY)

    @api.get("/thumb/{doc_id}/{rel:path}")
    async def thumb_file(doc_id: str, rel: str, w: int = 320) -> Response:
        """A small webp of an image, made once and cached.

        When none can be made, the original is sent if it is small, else a placeholder:
        a phone never downloads a 60 MB photo for a 160 px tile.
        """
        path = await anyio.to_thread.run_sync(_file_path, doc_id, rel)
        width = next((x for x in THUMB_WIDTHS if x >= w), THUMB_WIDTHS[-1])
        if thumbnailer and Path(rel).suffix.lower() in THUMBNAILABLE:
            key = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:20]
            cached = _local_root() / THUMB_CACHE / doc_id / f"{key}.w{width}.webp"
            made = cached.is_file() or await anyio.to_thread.run_sync(
                thumbnailer, path, cached, width, limiter=thumb_limiter
            )
            if made:
                return FileResponse(cached, media_type="image/webp", headers={"Cache-Control": RAW_CACHE})
            if path.stat().st_size > THUMB_FALLBACK_MAX_BYTES:
                return Response(_TOO_BIG_SVG, media_type="image/svg+xml", headers={"Cache-Control": RAW_CACHE})
        return raw_file(doc_id, rel)

    if UI_DIR.is_dir():  # never fail a host's import over a missing asset dir
        api.mount("/ui", _RevalidatingStatic(directory=str(UI_DIR)), name="ui")
    api.state.store = store
    return api


def page_html(*, base: str = DFLT_BASE_PATH, api: str | None = None, title: str = APP_NAME) -> str:
    """The page shell: where the page lives (``base``) and where its API is (``api``).

    A host that serves the API under another prefix (enlace: ``/api/annals``) writes this
    once as its frontend: ``annals page-shell --api /api/annals > frontend/index.html``.
    The shell only names the two paths and loads the assets from the API, so the page
    itself upgrades with the package, never with the shell.
    """
    base = "/" + base.strip("/")
    api = "/" + (api or base + "/api").strip("/")
    shell = (UI_DIR / "index.html").read_text(encoding="utf-8")
    return shell.replace("{{BASE}}", base).replace("{{API}}", api).replace("{{TITLE}}", title)


def _wants_html(request: Request) -> bool:
    return request.method == "GET" and "text/html" in request.headers.get("accept", "")


class _AuthGate:
    """Pure ASGI middleware: ask the authorizer, deny like enlace_auth does."""

    def __init__(self, app, authorizer: Authorizer):
        self.app = app
        self.authorizer = authorizer

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        who = self.authorizer(request)
        if who is None:
            await self._deny(request)(scope, receive, send)
            return
        scope.setdefault("state", {})["annals_user"] = who
        await self.app(scope, receive, send)

    def _deny(self, request: Request):
        login_url = getattr(self.authorizer, "login_url", None)
        if login_url and _wants_html(request):
            nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"{login_url}?login_required=1&next={quote(nxt, safe='')}", status_code=303)
        headers = {"WWW-Authenticate": f'Basic realm="{APP_NAME}"'} if login_url is None and self.authorizer is not no_auth else {}
        return JSONResponse({"detail": "Not authenticated", "auth": "user"}, status_code=401, headers=headers)


def mk_app(
    *,
    data_dir: Path | str | None = None,
    store: DocStore | None = None,
    authorizer: Authorizer | None = None,
    base_path: str = DFLT_BASE_PATH,
    title: str = APP_NAME,
) -> FastAPI:
    """The standalone server: page + API under ``base_path``, behind ``authorizer``.

    Every argument has a working default (the local data dir; auth from the environment,
    which is none on a bare machine, so bind to localhost).
    """
    store = store or DocStore(Path(data_dir) if data_dir else default_data_dir())
    authorizer = authorizer or authorizer_from_env()
    base = "/" + base_path.strip("/")
    app = FastAPI(title=title, docs_url=None, redoc_url=None, openapi_url=None)
    shell = page_html(base=base, title=title)

    @app.get(base + "/", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/d/{doc_id}", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/g/{gid}", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/trash", response_class=HTMLResponse, include_in_schema=False)
    def page(doc_id: str = "", gid: str = "") -> HTMLResponse:
        return HTMLResponse(shell, headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    @app.get(base, include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        return RedirectResponse(base + "/", status_code=307)

    app.mount(base + "/api", mk_api(store=store, title=title))
    app.state.store = store
    app.state.base_path = base
    app.add_middleware(_AuthGate, authorizer=authorizer)  # pure ASGI, never BaseHTTPMiddleware
    return app


def _meta_or_404(store: DocStore, doc_id: str) -> dict:
    try:
        return store.meta(doc_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "no such document")


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = DFLT_SERVE_PORT,
    data_dir: str | None = None,
    base_path: str = DFLT_BASE_PATH,
) -> None:
    """Run the standalone server with uvicorn (``pip install 'annals[server]'``)."""
    import uvicorn

    app = mk_app(data_dir=data_dir or os.environ.get(ENV_DATA_DIR), base_path=base_path)
    uvicorn.run(app, host=host, port=port, log_level="info")
