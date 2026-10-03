"""The HTTP surface: a FastAPI app over a :class:`tray.store.DocStore`, plus the page.

:func:`mk_app` builds one app that serves, under one base path (default ``/tray``):

* ``{base}/``, ``{base}/d/{id}``, ``{base}/g/{gid}``, ``{base}/trash``: the page (one
  ``index.html``; the browser routes).
* ``{base}/ui/...``: the page's assets, from the package.
* ``{base}/api/...``: the JSON API the page uses: list, search, read, trash, restore,
  purge, groups, and raw files (``{base}/api/raw/{id}/{path}``) so an html document
  renders in a frame with its own assets.

Every request passes the authorizer first (see :mod:`tray.auth`). The reader's actions are
the three the recycle bin needs; publishing is not an HTTP operation here, it is a file
write (see :mod:`tray.target`), which is what keeps this surface small and the tray private.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from tray.auth import Authorizer, authorizer_from_env, no_auth
from tray.config import APP_NAME, MAX_INLINE_TEXT_BYTES, default_data_dir
from tray.store import DOCS, TRASH, DocStore, TEXT_KINDS, check_id

UI_DIR = Path(__file__).parent / "data" / "ui"
DFLT_BASE_PATH = f"/{APP_NAME}"
NO_STORE = {"Cache-Control": "no-store"}
# An html document is the agent's own code; a frame with this policy cannot read the
# tray's cookies or call its API, which is all the isolation a private tray needs.
RAW_HTML_CSP = "sandbox allow-scripts allow-popups allow-forms allow-modals allow-downloads"


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
        scope.setdefault("state", {})["tray_user"] = who
        await self.app(scope, receive, send)

    def _deny(self, request: Request):
        login_url = getattr(self.authorizer, "login_url", None)
        if login_url and _wants_html(request):
            nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"{login_url}?login_required=1&next={quote(nxt, safe='')}", status_code=303)
        headers = {"WWW-Authenticate": 'Basic realm="tray"'} if login_url is None and self.authorizer is not no_auth else {}
        return JSONResponse({"detail": "Not authenticated", "auth": "user"}, status_code=401, headers=headers)


def mk_app(
    *,
    data_dir: Path | str | None = None,
    store: DocStore | None = None,
    authorizer: Authorizer | None = None,
    base_path: str = DFLT_BASE_PATH,
    title: str = "tray",
) -> FastAPI:
    """Build the tray server. Every argument has a working default (local, no auth)."""
    store = store or DocStore(Path(data_dir) if data_dir else default_data_dir())
    authorizer = authorizer or authorizer_from_env()
    base = "/" + base_path.strip("/")

    app = FastAPI(title=title, docs_url=None, redoc_url=None, openapi_url=None)
    # No swagger: its /docs route would shadow ours.
    api = FastAPI(title=f"{title} api", docs_url=None, redoc_url=None, openapi_url=None)

    # -- JSON API ------------------------------------------------------------------

    @api.get("/health")
    def health() -> dict:
        """Cheap liveness probe (also tells the page which data dir is served)."""
        return {"ok": True, "target": store.target.describe()}

    @api.get("/docs")
    def list_docs(q: str = "", trash: bool = False) -> dict:
        """All documents (or the bin), newest first; ``q`` filters by words."""
        docs = store.search(q, trash=trash) if q else store.list(trash=trash)
        return {"docs": docs}

    @api.get("/docs/{doc_id}")
    def get_doc(doc_id: str) -> dict:
        """One document's meta, with its text inline when it is markdown or text."""
        meta = _meta_or_404(store, doc_id)
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
                docs.append(store.meta(i))
            except (KeyError, ValueError):
                continue
        return {**group, "items": docs}

    @api.get("/raw/{doc_id}/{rel:path}")
    def raw_file(doc_id: str, rel: str) -> Response:
        """A document's file as itself (html framed, assets as assets, text as text)."""
        meta = _meta_or_404(store, doc_id)
        if rel not in meta["files"]:
            raise HTTPException(404, "no such file in document")
        root = getattr(store.target, "root", None)
        if not isinstance(root, Path):
            raise HTTPException(501, "raw files are served from a local data dir only")
        path = root / (TRASH if meta["in_trash"] else DOCS) / doc_id / rel
        if not path.is_file():
            raise HTTPException(404, "file missing on disk")
        media_type = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        headers = dict(NO_STORE)
        if media_type == "text/html":
            headers["Content-Security-Policy"] = RAW_HTML_CSP
        return FileResponse(path, media_type=media_type, headers=headers)

    # -- the page --------------------------------------------------------------------

    index_html = (UI_DIR / "index.html").read_text(encoding="utf-8").replace("/tray/ui/", base + "/ui/")

    @app.get(base + "/", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/d/{doc_id}", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/g/{gid}", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/trash", response_class=HTMLResponse, include_in_schema=False)
    def page(doc_id: str = "", gid: str = "") -> HTMLResponse:
        return HTMLResponse(index_html, headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    @app.get(base, include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        return RedirectResponse(base + "/", status_code=307)

    app.mount(base + "/ui", StaticFiles(directory=str(UI_DIR)), name="ui")
    app.mount(base + "/api", api)
    app.state.store = store
    app.state.base_path = base
    return _wrap(app, authorizer)


def _wrap(app: FastAPI, authorizer: Authorizer) -> FastAPI:
    """Put the auth gate around the whole app, as pure ASGI (no BaseHTTPMiddleware)."""
    app.add_middleware(_AuthGate, authorizer=authorizer)
    return app


def _meta_or_404(store: DocStore, doc_id: str) -> dict:
    try:
        return store.meta(doc_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "no such document")


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    data_dir: str | None = None,
    base_path: str = DFLT_BASE_PATH,
) -> None:
    """Run the tray server with uvicorn (``pip install 'intray[server]'``)."""
    import uvicorn

    app = mk_app(data_dir=data_dir or os.environ.get("TRAY_DATA_DIR"), base_path=base_path)
    uvicorn.run(app, host=host, port=port, log_level="info")
