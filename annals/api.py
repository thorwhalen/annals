"""The HTTP surface: a JSON API over a :class:`annals.store.DocStore` and other sources, plus the page.

Two factories, one implementation:

* :func:`mk_api` is the API alone, rooted at ``/``: list, search, read, trash, restore,
  purge, groups, raw files (``/raw/{id}/{path}``, with byte ranges so video seeks) and the
  page's assets (``/ui/...``). Beside the documents, ``/items`` lists every source's items
  as one collection (published documents plus folders read in place, such as the crowsnest
  ledgers; see :mod:`annals.sources`) with full-text search, and ``PATCH /items/{key}``
  sets the owner's tags, which live apart from the items (see :mod:`annals.tags`). A host platform mounts it under its own prefix and gates it
  with its own login; that is how annals runs as an enlace app (``/api/annals``), with
  the page shell from :func:`page_html` as the app's frontend.
* :func:`mk_app` is the standalone server ``annals serve`` runs: the API at
  ``{base}/api``, the page at ``{base}/``, ``{base}/d/{id}``, ``{base}/g/{gid}``,
  ``{base}/trash``, ``{base}/all``, ``{base}/s/{source}``, ``{base}/i/{source}/{id}`` (one
  html shell; the browser routes), and an auth gate around it all
  (see :mod:`annals.auth`).

The reader's actions are the three the recycle bin needs, plus tagging. Publishing is not an HTTP
operation here: it is a file write (see :mod:`annals.target`), which keeps this surface
small and the documents' lifecycle independent of whatever serves them.
"""

from __future__ import annotations

import functools
import hashlib
import mimetypes
import ipaddress
import os
import re
import shutil
import tempfile
import warnings
from pathlib import Path
from collections.abc import Mapping, MutableMapping
from typing import Callable
from urllib.parse import quote, urlsplit

import anyio
import anyio.to_thread
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

from annals import overview
from annals.auth import Authorizer, authorizer_from_env, no_auth
from annals.overview import Requests
from annals.target import LocalTarget
from annals.config import (
    APP_NAME,
    DFLT_SERVE_PORT,
    ENV_DATA_DIR,
    ENV_SHARE_BASE_URL,
    ENV_SOURCES,
    MAX_INLINE_TEXT_BYTES,
    default_data_dir,
)
from annals.catalog import Catalog, mk_catalog
from annals.export import (
    aggregate_response,
    file_url_builder,
    run_export,
    trusted_base,
)
from annals.sources import (
    PUBLISHED,
    PublishedSource,
    Source,
    as_source,
    list_meta,
    mk_key,
    parse_sources_spec,
    with_thumb,
)
from annals.share import DFLT_EXPIRES, Shares, share_url
from annals.store import (
    DocStore,
    TEXT_KINDS,
    check_artifact_url,
    kind_of,
    split_version,
)
from annals.tags import TAGS_DIR, TAGS_FILE, JsonTagStore
from annals.tables import add_table_tools, tables_version
from annals.target import check_rel

UI_DIR = Path(__file__).parent / "data" / "ui"
DFLT_BASE_PATH = f"/{APP_NAME}"
NO_STORE = {"Cache-Control": "no-store"}
# A version of a document never changes once written, so its files can be cached by the
# reader's browser; "private" keeps shared caches out of it. The current version's files
# change when the document is replaced, so those are revalidated (cheap: a 304).
RAW_CACHE = "private, max-age=86400"
CURRENT_CACHE = "private, no-cache"
#: the doctype guard: a page without a doctype would render in quirks mode, so it is
#: served after this skeleton (the parts the page lacks), as an artifact host does
DOCTYPE = "<!doctype html>"
CHARSET_META = '<meta charset="utf-8">'
VIEWPORT_META = '<meta name="viewport" content="width=device-width, initial-scale=1">'
#: how much of an html file is searched for a doctype, a charset and a viewport
HTML_HEAD_BYTES = 4096
_DOCTYPE_RE = re.compile(rb"^(\xef\xbb\xbf)?\s*(<!--.*?-->\s*)*<!doctype", re.I | re.S)
# Every raw file is served under a sandbox policy, so a file that a browser renders as a
# document (html, svg, any +xml, whatever the host's mime table says) cannot read the
# platform's cookies or call any app's API on this shared origin. Harmless for media used
# by <img>/<video>. PDF alone is exempt: its built-in viewer refuses a sandboxed document.
NO_SANDBOX_TYPES = frozenset({"application/pdf"})
RAW_SANDBOX_CSP = (
    "sandbox allow-scripts allow-popups allow-forms allow-modals allow-downloads"
)
# Types a browser would otherwise download or mis-render; served as text so a viewer can
# show them (markdown and friends are text to a reader).
#: thumbnail widths served; a request snaps up to the nearest, so the cache stays bounded
THUMB_WIDTHS = (160, 320, 640)
THUMB_CACHE = "cache/thumbs"
#: rasters Pillow can shrink; anything else (svg) is served as itself
THUMBNAILABLE = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif"})
TEXT_TYPE_OVERRIDES = {
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
}


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
            warnings.simplefilter(
                "ignore", Image.DecompressionBombWarning
            )  # the cap below decides
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


def default_thumbnailer() -> Thumbnailer | None:
    """Pillow's thumbnailer when Pillow is installed, else ``None`` (originals are served)."""
    try:
        import PIL  # noqa: F401
    except ImportError:
        return None
    return pillow_thumbnailer


def _require_same_origin(request: Request) -> None:
    """Refuse a state-changing request a browser sent from another site (CSRF).

    Browsers label every fetch with ``Sec-Fetch-Site`` and, on cross-origin posts, an
    ``Origin``; a page on another site cannot forge or drop either. Requests carrying
    neither (curl, the CLI, tests) are not browser-driven and pass.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        if site not in ("same-origin", "none"):
            raise HTTPException(403, "cross-site request refused")
        return
    origin = request.headers.get("origin")
    if origin is None:
        return
    forwarded = request.headers.get("x-forwarded-host", "").split(",")[0]
    hosts = {
        h.strip().lower()
        for h in (request.headers.get("host", ""), forwarded)
        if h.strip()
    }
    if origin == "null" or urlsplit(origin).netloc.lower() not in hosts:
        raise HTTPException(403, "cross-origin request refused")


def media_type_of(rel: str) -> str:
    """The media type a file is served as (markdown as text, unknown as octet-stream)."""
    override = TEXT_TYPE_OVERRIDES.get(Path(rel).suffix.lower())
    return override or mimetypes.guess_type(rel)[0] or "application/octet-stream"


def mk_api(
    *,
    data_dir: Path | str | None = None,
    store: DocStore | None = None,
    thumbnailer: Thumbnailer | None | bool = True,
    sources: Mapping[str, Source | Path | str] | None = None,
    tags: MutableMapping[str, list[str]] | None = None,
    share_base_url: str | None = None,
    overviews: bool = False,
    title: str = APP_NAME,
) -> FastAPI:
    """The JSON API, raw files and page assets, rooted at ``/``, with no auth of its own.

    Mount it behind a login (enlace_auth does this for an enlace app), or use
    :func:`mk_app`, which adds the gate. Every argument has a working default.
    ``thumbnailer`` shrinks gallery images: Pillow when it is installed (``True``), any
    ``(src, dst, width) -> bool`` callable, or ``None`` to always serve the original.
    ``sources`` adds named sources listed beside the published documents: a folder path
    (read in place, never written) or any :class:`annals.sources.Source`; by default, the
    folders named in ``ANNALS_SOURCES``. ``tags`` is where the owner's tags live, any
    ``MutableMapping`` from item key to tag list; by default one JSON file under the data
    root (``tags/tags.json``), or a dict when the data root is not on this machine.
    ``share_base_url`` is where the public share server (:mod:`annals.share_api`) answers,
    so a new share comes back with its link (by default ``ANNALS_SHARE_BASE_URL``; with
    neither, shares are made but carry no link, since nothing public serves them here).
    ``overviews`` offers a spoken overview of a document on its page (off by default, since
    making one spends money); it needs a local data root and a worker, see
    :mod:`annals.overview`.
    """
    store = store or DocStore(Path(data_dir) if data_dir else default_data_dir())
    if overviews and not isinstance(store.target, LocalTarget):
        raise ValueError("overviews need a data root on this machine")
    requests = Requests(store.target.root) if overviews else None
    shares = Shares(store)
    share_base = (
        share_base_url
        if share_base_url is not None
        else os.environ.get(ENV_SHARE_BASE_URL)
    )
    if thumbnailer is True:
        thumbnailer = default_thumbnailer()
    catalog = mk_catalog(store, sources=sources, tags=tags)
    api = FastAPI(title=f"{title} api", docs_url=None, redoc_url=None, openapi_url=None)
    # No swagger: its /docs route would shadow ours.

    def _owner_tags(meta: dict) -> dict:
        """A document's tags as the owner left them (the publisher's until the owner edits)."""
        own = catalog.tags.get(mk_key(PUBLISHED, meta["id"]))
        if own is not None:
            meta["tags"] = list(own)
        return meta

    @api.get("/health")
    def health() -> dict:
        """Cheap liveness probe (also says which data dir is served)."""
        return {"ok": True, "target": store.target.describe()}

    @api.get("/docs")
    def list_docs(q: str = "", trash: bool = False) -> dict:
        """All documents (or the bin), newest first; ``q`` filters by words."""
        docs = store.search(q, trash=trash) if q else store.list(trash=trash)
        return {"docs": [_owner_tags(list_meta(m)) for m in docs]}

    @api.get("/docs/{doc_id}")
    def get_doc(doc_id: str) -> dict:
        """One document's meta, each file's kind, and its text inline when markdown or text."""
        meta = _owner_tags(with_thumb(_meta_or_404(store, doc_id)))
        if "version_of" in meta:  # a version's page lists its siblings
            try:
                current = store.meta(meta["version_of"])
                meta["versions"] = current.get("versions", [])
                meta["current_version"] = current.get("version")
            except (KeyError, ValueError):
                pass
        if "artifact" in meta:  # a meta written by another publisher is checked again
            try:
                check_artifact_url(str(meta["artifact"]))
            except ValueError:
                del meta["artifact"]
        meta["file_kinds"] = {f: kind_of(f) for f in meta.get("files", [])}
        if requests and overview.eligible(meta):
            meta["listen"] = overview.state_of(store, requests, meta)
        if meta["kind"] in TEXT_KINDS and meta.get("size", 0) <= MAX_INLINE_TEXT_BYTES:
            try:
                meta["text"] = store.read_text(doc_id)
            except (
                KeyError,
                OSError,
                ValueError,
            ):  # missing, unreadable or outside the root
                raise HTTPException(404, "no readable text for this document")
        return meta

    def _spoken(doc_id: str) -> dict:
        if not requests:
            raise HTTPException(404, "overviews are not offered here")
        return _meta_or_404(store, doc_id)

    @api.get("/docs/{doc_id}/overview")
    def get_overview(doc_id: str) -> dict:
        """The state of a document's spoken overview; a page polls this while one is made."""
        return overview.state_of(store, requests, _spoken(doc_id))

    @api.post("/docs/{doc_id}/overview", dependencies=[Depends(_require_same_origin)])
    def request_overview(doc_id: str, body: dict = Body(default={})) -> dict:
        """Ask for a spoken overview ``{"minutes": 3|5|7, "force"?: true}``. This spends money.

        A current overview is returned as it is, unless ``force``.
        """
        _spoken(doc_id)
        try:
            return overview.request(
                store, requests, doc_id,
                minutes=body.get("minutes", overview.DFLT_MINUTES), force=body.get("force") is True,
            )  # fmt: skip
        except ValueError as e:
            raise HTTPException(400, str(e))

    @api.post("/docs/{doc_id}/trash", dependencies=[Depends(_require_same_origin)])
    def trash_doc(doc_id: str) -> dict:
        """Move a document to the recycle bin."""
        _meta_or_404(store, doc_id)
        return store.trash(doc_id)

    @api.post("/docs/{doc_id}/restore", dependencies=[Depends(_require_same_origin)])
    def restore_doc(doc_id: str) -> dict:
        """Bring a document back from the bin."""
        _meta_or_404(store, doc_id)
        return store.restore(doc_id)

    @api.delete("/docs/{doc_id}", dependencies=[Depends(_require_same_origin)])
    def purge_doc(doc_id: str) -> dict:
        """Delete forever; only allowed for a document already in the bin."""
        _meta_or_404(store, doc_id)
        try:
            store.purge(doc_id)
        except PermissionError as e:
            raise HTTPException(409, str(e))
        catalog.forget(mk_key(PUBLISHED, doc_id))
        root = store.target.local_path(".")
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
                docs.append(_owner_tags(list_meta(store.meta(i))))
            except (KeyError, ValueError):
                continue
        return {**group, "items": docs}

    @api.get("/groups/{gid}/aggregate")
    async def aggregate_group(
        gid: str, download: bool = False, demote: int = 1
    ) -> Response:
        """Every markdown file of a group's documents as one ``.md``, made per request.

        Shown as plain text, or saved as ``<title>.md`` with ``?download=1``. Documents in
        the bin are left out. See :mod:`annals.aggregate` for the layout.
        """

        def make() -> Response:
            try:
                group, docs = store.group_docs(gid)
            except (KeyError, ValueError):
                raise HTTPException(404, "no such group")
            return aggregate_response(
                ((m, m.get("files", [])) for m in docs),
                read=store.read_text,
                title=group.get("title") or gid,
                download=download,
                demote=demote,
            )

        return await anyio.to_thread.run_sync(make)

    # -- shares: public links to one document or group (the owner's side) -------------
    # The recipient's side is annals.share_api, mounted where this API's login does not
    # reach. Here the owner makes, lists and revokes them; a password arrives in the clear
    # over the owner's own session and only its hash is stored.

    def _with_link(rec: dict) -> dict:
        rec["url"] = share_url(share_base, rec["token"])
        return rec

    @api.get("/shares")
    def list_shares(all: bool = False, ref: str = "") -> dict:
        """Live shares, newest first (``all``: revoked and expired too; ``ref``: of one id)."""
        recs = [
            r for r in shares.list(all=all) if not ref or r["root"].get("id") == ref
        ]
        return {"shares": [_with_link(r) for r in recs], "linkable": bool(share_base)}

    @api.post("/shares", dependencies=[Depends(_require_same_origin)])
    def create_share(body: dict = Body(...)) -> dict:
        """Share ``{"ref": id, "include"?, "exclude"?, "password"?, "expires"?, "title"?}``.

        ``expires`` defaults to 7 days; ``"never"`` (or ``null``) makes a lasting link.
        """
        known = {"ref", "include", "exclude", "password", "expires", "title"}
        if set(body) - known or not isinstance(body.get("ref"), str):
            raise HTTPException(
                422,
                f"send {{'ref': <doc or group id>}} plus any of {sorted(known - {'ref'})}",
            )
        for k in ("include", "exclude"):
            if body.get(k) is not None and not (
                isinstance(body[k], list) and all(isinstance(x, str) for x in body[k])
            ):
                raise HTTPException(422, f"{k} must be a list of strings")
        for k in ("password", "expires", "title"):
            if body.get(k) is not None and not isinstance(body[k], str):
                raise HTTPException(422, f"{k} must be a string")
        try:
            rec = shares.create(
                body["ref"],
                include=body.get("include"),
                exclude=body.get("exclude") or (),
                password=body.get("password") or None,
                expires=body["expires"] if "expires" in body else DFLT_EXPIRES,
                title=body.get("title") or None,
            )
        except KeyError:
            raise HTTPException(404, "no such document or group")
        except ValueError as e:
            raise HTTPException(422, str(e))
        return _with_link(rec)

    @api.delete("/shares/{token}", dependencies=[Depends(_require_same_origin)])
    def revoke_share(token: str) -> dict:
        """Turn a link off now; its record stays, revoked, in ``/shares?all=1``."""
        try:
            return _with_link(shares.revoke(token))
        except KeyError:
            raise HTTPException(404, "no such share")

    @api.get("/docs/{doc_id}/shareable")
    def shareable(doc_id: str) -> dict:
        """What the Share dialog offers: the document's files, and the pages it links."""
        _meta_or_404(store, doc_id)
        try:
            return shares.resources(doc_id)
        except (KeyError, ValueError):
            raise HTTPException(404, "no such document")

    # -- every source's items: one list, full-text search, the owner's tags ---------
    # The page reaches these through @zodal/store-http's provider: GET /items?q= answers
    # {data, total}; GET and PATCH /items/{key} one item. A key is "<source>:<id>".

    @api.get("/sources")
    def list_sources() -> dict:
        """The sources listed, in order (``published`` first)."""
        return {"sources": catalog.sources_info()}

    @api.get("/items")
    def list_items(q: str = "", source: str = "", trash: bool = False) -> dict:
        """Items newest first, from every source or one, matching every word of ``q``."""
        try:
            rows = catalog.rows(q, source=source or None, trash=trash)
        except KeyError as e:
            raise HTTPException(404, str(e.args[0]) if e.args else "no such source")
        return {"data": rows, "total": len(rows)}

    @api.get("/items/{key:path}")
    def get_item(key: str) -> dict:
        """One item: its row, plus its text when it is markdown or text."""
        return _item_or_404(catalog, key)

    @api.patch("/items/{key:path}", dependencies=[Depends(_require_same_origin)])
    def patch_item(key: str, patch: dict = Body(...)) -> dict:
        """Change an item's tags, the one thing the owner edits: ``{"tags": [...]}``."""
        extra = set(patch) - {"tags"}
        if extra or not isinstance(patch.get("tags"), list):
            raise HTTPException(
                422, 'send {"tags": [...]}; tags are the only editable field'
            )
        _item_or_404(catalog, key)
        try:
            return catalog.set_tags(key, patch["tags"])
        except ValueError as e:
            raise HTTPException(422, str(e))

    @api.get("/tags")
    def list_tags() -> dict:
        """Every tag in use, with how many items carry it."""
        return {"tags": catalog.tag_counts()}

    @api.get("/files/{source}/{rel:path}")
    def source_file(source: str, rel: str, download: bool = False) -> Response:
        """A file of a folder source as itself (sandboxed like every raw file).

        ``?download=1`` makes the browser save it instead of showing it.
        """
        src = catalog.sources.get(source)
        file_path = getattr(src, "file_path", None)
        if file_path is None:
            raise HTTPException(404, "no such source")
        try:
            path = file_path(rel)
        except KeyError:
            raise HTTPException(404, "no such file")
        # these files change in place (a ledger grows), so revalidate every time
        return raw_response(path, rel, cache="private, no-cache", download=download)

    @api.get("/raw/{doc_id}/{rel:path}")
    def raw_file(
        doc_id: str,
        rel: str,
        if_none_match: str | None = Header(None),
        download: bool = False,
    ) -> Response:
        """A document's file as itself, streamed, with byte ranges (video and audio seek).

        ``FileResponse`` answers ``Range`` with ``206 Partial Content`` and never loads the
        file into memory, which is what a ``<video>`` element needs (Safari will not play
        without ranges). ``?download=1`` answers with ``Content-Disposition: attachment``,
        so every kind of media, a PDF included, can be saved from its viewer.
        """
        path = doc_file_path(store, doc_id, rel)
        cache = RAW_CACHE if _is_version(doc_id) else CURRENT_CACHE
        if download:
            return raw_response(path, rel, cache=cache, download=True)
        if kind_of(rel) == "html":
            return _html_response(path, rel, cache=cache, request_etag=if_none_match)
        return raw_response(path, rel, cache=cache)

    @api.get("/export/{doc_id}")
    async def export_doc(
        doc_id: str,
        request: Request,
        format: str = "pdf",
        file: str = "",
        base: str = "",
    ) -> Response:
        """A markdown document as a ``.md`` or a titled ``.pdf`` download (images inside).

        ``file`` names another markdown file of a folder document (default: the main
        one); ``base`` is the page's own url prefix, for the links to media in the PDF.
        """
        meta = _meta_or_404(store, doc_id)
        rel = file or meta["main"]
        if rel not in meta["files"] or kind_of(rel) != "md":
            raise HTTPException(404, "no markdown file to export")
        if (meta.get("sizes") or {}).get(rel, 0) > MAX_INLINE_TEXT_BYTES:
            raise HTTPException(413, "this file is too large to export")
        try:
            text = await anyio.to_thread.run_sync(store.read_text, doc_id, rel)
        except (KeyError, OSError, ValueError):
            raise HTTPException(404, "no readable text for this document")
        return await run_export(
            format,
            title=meta.get("title") or doc_id,
            text=text,
            rel=rel,
            files=meta["files"],
            open_file=functools.partial(doc_file_path, store, doc_id),
            file_url=file_url_builder(trusted_base(request, base), doc_id),
            created=meta.get("created", ""),
        )

    thumbs = ThumbServer(store, thumbnailer)

    @api.get("/thumb/{doc_id}/{rel:path}")
    async def thumb_file(doc_id: str, rel: str, w: int = 320) -> Response:
        """A small webp of an image, made once and cached (see :class:`ThumbServer`)."""
        path = await anyio.to_thread.run_sync(doc_file_path, store, doc_id, rel)
        return await thumbs.respond(
            path, doc_id, rel, w, fallback=lambda: raw_file(doc_id, rel, None)
        )

    if UI_DIR.is_dir():  # never fail a host's import over a missing asset dir
        api.mount("/ui", _RevalidatingStatic(directory=str(UI_DIR)), name="ui")
    api.state.store = store
    api.state.catalog = catalog
    api.state.shares = shares
    return api


def doc_file_path(store: DocStore, doc_id: str, rel: str) -> Path:
    """A document's file on disk, or a 404.

    It must be listed in the meta AND stay inside the document's directory (meta.json is
    written by the publisher, so it is not trusted to keep paths in bounds).
    """
    meta = _meta_or_404(store, doc_id, settle=False)  # hot path: the page settled it
    if rel not in meta["files"]:
        raise HTTPException(404, "no such file in document")
    try:
        check_rel(rel)
    except ValueError:
        raise HTTPException(404, "no such file in document")
    try:
        doc_rel = store.doc_rel(doc_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "no such document")
    doc_dir = store.target.local_path(doc_rel)
    path = store.target.local_path(f"{doc_rel}/{rel}")
    if doc_dir is None:
        raise HTTPException(501, "raw files are served from a local data dir only")
    if path is None or not path.is_relative_to(doc_dir) or not path.is_file():
        raise HTTPException(404, "file missing on disk")
    return path


class ThumbServer:
    """Small webp thumbnails of a store's images, made once and cached under the data root.

    When none can be made, the original is sent if it is small (``fallback``), else a
    placeholder: a phone never downloads a 60 MB photo for a 160 px tile. Waiting for a
    slot must not hold one of the threads every app shares, so :meth:`respond` is async and
    only the work goes to a thread, ``THUMB_CONCURRENCY`` at a time.
    """

    def __init__(self, store: DocStore, thumbnailer: Thumbnailer | None):
        self.store = store
        self.thumbnailer = thumbnailer
        self.limiter = anyio.CapacityLimiter(THUMB_CONCURRENCY)

    async def respond(
        self,
        path: Path,
        doc_id: str,
        rel: str,
        w: int,
        *,
        fallback: Callable[[], Response],
        cache: str | None = None,
    ) -> Response:
        """The thumbnail of ``path`` (``rel`` of ``doc_id``) at the width snapped from ``w``."""
        width = next((x for x in THUMB_WIDTHS if x >= w), THUMB_WIDTHS[-1])
        root = self.store.target.local_path(".")
        if self.thumbnailer and root and Path(rel).suffix.lower() in THUMBNAILABLE:
            # a replace reuses file names, so the thumbnail is the file's at this version
            meta = await anyio.to_thread.run_sync(
                functools.partial(self.store.meta, doc_id, settle=False)
            )
            stamp = meta.get("updated", "")
            key = hashlib.sha1(f"{rel}|{stamp}".encode("utf-8")).hexdigest()[:20]
            cached = root / THUMB_CACHE / doc_id / f"{key}.w{width}.webp"
            made = cached.is_file() or await anyio.to_thread.run_sync(
                self.thumbnailer, path, cached, width, limiter=self.limiter
            )
            cache = cache or (RAW_CACHE if _is_version(doc_id) else CURRENT_CACHE)
            if made:
                return FileResponse(
                    cached,
                    media_type="image/webp",
                    headers={"Cache-Control": cache},
                )
            if path.stat().st_size > THUMB_FALLBACK_MAX_BYTES:
                return Response(
                    _TOO_BIG_SVG,
                    media_type="image/svg+xml",
                    headers={"Cache-Control": cache},
                )
        return fallback()


def _item_or_404(catalog: Catalog, key: str) -> dict:
    try:
        return catalog.item(key)
    except (KeyError, ValueError, OSError):
        raise HTTPException(404, "no such item")


def _is_version(doc_id: str) -> bool:
    try:
        return split_version(doc_id)[1] is not None
    except ValueError:
        return False


def doctype_guard(html: bytes) -> bytes:
    """``html`` as a standards-mode page: the doctype, charset and viewport it lacks, first.

    A page that already starts with a doctype (after a BOM, blanks or comments) is returned
    as it is. Prepending is valid html: the parser takes a doctype before ``<html>``, and
    ``<meta>`` before ``<html>`` goes into the head it opens.
    """
    if _DOCTYPE_RE.match(html):
        return html
    head = html[:HTML_HEAD_BYTES].lower()
    missing = [DOCTYPE]
    if b"charset" not in head:
        missing.append(CHARSET_META)
    if b'name="viewport"' not in head and b"name=viewport" not in head:
        missing.append(VIEWPORT_META)
    bom = b"\xef\xbb\xbf"
    body = html[len(bom) :] if html.startswith(bom) else html
    return ("\n".join(missing) + "\n").encode("utf-8") + body


def _html_response(
    path: Path, rel: str, *, cache: str, request_etag: str | None = None
) -> Response:
    """An html file through :func:`doctype_guard`, under the sandbox policy.

    Carries an ETag from the file's size and mtime, so a revalidation is a 304.
    """
    st = path.stat()
    etag = f'"{st.st_size:x}-{st.st_mtime_ns:x}-{tables_version()}"'
    headers = {
        "Cache-Control": cache,
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": RAW_SANDBOX_CSP,
    }
    if request_etag and etag in {t.strip() for t in request_etag.split(",")}:
        return Response(status_code=304, headers=headers)
    return Response(
        add_table_tools(doctype_guard(path.read_bytes())),
        media_type=media_type_of(rel),
        headers=headers,
    )


def raw_response(
    path: Path, rel: str, *, cache: str = RAW_CACHE, download: bool = False
) -> Response:
    """A file as itself, streamed, with byte ranges, under the sandbox policy (not PDF).

    With ``download`` it carries ``Content-Disposition: attachment`` (named after the file).
    """
    media_type = media_type_of(rel)
    headers = {"Cache-Control": cache, "X-Content-Type-Options": "nosniff"}
    if media_type.split(";")[0] not in NO_SANDBOX_TYPES:
        headers["Content-Security-Policy"] = RAW_SANDBOX_CSP
    if download:
        return FileResponse(
            path,
            media_type=media_type,
            headers=headers,
            filename=Path(rel).name,
            content_disposition_type="attachment",
        )
    return FileResponse(path, media_type=media_type, headers=headers)


def page_html(
    *, base: str = DFLT_BASE_PATH, api: str | None = None, title: str = APP_NAME
) -> str:
    """The page shell: where the page lives (``base``) and where its API is (``api``).

    A host that serves the API under another prefix (enlace: ``/api/annals``) writes this
    once as its frontend: ``annals page-shell --api /api/annals > frontend/index.html``.
    The shell only names the two paths and loads the assets from the API, so the page
    itself upgrades with the package, never with the shell.
    """
    base = "/" + base.strip("/")
    api = "/" + (api or base + "/api").strip("/")
    shell = (UI_DIR / "index.html").read_text(encoding="utf-8")
    return (
        shell.replace("{{BASE}}", base)
        .replace("{{API}}", api)
        .replace("{{TITLE}}", title)
    )


def _wants_html(request: Request) -> bool:
    return request.method == "GET" and "text/html" in request.headers.get("accept", "")


class _AuthGate:
    """Pure ASGI middleware: ask the authorizer, deny like enlace_auth does.

    Paths under a ``public`` prefix (the share server) pass ungated: their own token is
    their gate.
    """

    def __init__(self, app, authorizer: Authorizer, public: tuple[str, ...] = ()):
        self.app = app
        self.authorizer = authorizer
        self.public = tuple(p.rstrip("/") + "/" for p in public)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith(self.public):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        # authorizers may block on the network: keep them off the event loop
        who = await anyio.to_thread.run_sync(self.authorizer, request)
        if who is None:
            await self._deny(request)(scope, receive, send)
            return
        scope.setdefault("state", {})["annals_user"] = who
        await self.app(scope, receive, send)

    def _deny(self, request: Request):
        login_url = getattr(self.authorizer, "login_url", None)
        if login_url and _wants_html(request):
            nxt = request.url.path + (
                f"?{request.url.query}" if request.url.query else ""
            )
            return RedirectResponse(
                f"{login_url}?login_required=1&next={quote(nxt, safe='')}",
                status_code=303,
            )
        headers = (
            {"WWW-Authenticate": f'Basic realm="{APP_NAME}"'}
            if login_url is None and self.authorizer is not no_auth
            else {}
        )
        return JSONResponse(
            {"detail": "Not authenticated", "auth": "user"},
            status_code=401,
            headers=headers,
        )


def mk_app(
    *,
    data_dir: Path | str | None = None,
    store: DocStore | None = None,
    authorizer: Authorizer | None = None,
    base_path: str = DFLT_BASE_PATH,
    sources: Mapping[str, Source | Path | str] | None = None,
    tags: MutableMapping[str, list[str]] | None = None,
    overviews: bool = False,
    title: str = APP_NAME,
) -> FastAPI:
    """The standalone server: page + API under ``base_path``, behind ``authorizer``.

    Every argument has a working default (the local data dir; auth from the environment,
    which is none on a bare machine, so bind to localhost). ``sources`` and ``tags`` are
    :func:`mk_api`'s, and so is ``overviews``. Share links are served, ungated, at ``{base_path}/shared/<token>/``
    (:func:`annals.share_api.mk_share_api`).
    """
    from annals.share_api import mk_share_api

    store = store or DocStore(Path(data_dir) if data_dir else default_data_dir())
    authorizer = authorizer or authorizer_from_env()
    base = "/" + base_path.strip("/")
    app = FastAPI(title=title, docs_url=None, redoc_url=None, openapi_url=None)
    shell = page_html(base=base, title=title)

    @app.get(base + "/", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/d/{doc_id}", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/g/{gid}", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/trash", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/shares", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/all", response_class=HTMLResponse, include_in_schema=False)
    @app.get(base + "/s/{source}", response_class=HTMLResponse, include_in_schema=False)
    @app.get(
        base + "/i/{key:path}", response_class=HTMLResponse, include_in_schema=False
    )
    def page(
        doc_id: str = "", gid: str = "", source: str = "", key: str = ""
    ) -> HTMLResponse:
        return HTMLResponse(shell, headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    @app.get(base, include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        return RedirectResponse(base + "/", status_code=307)

    shared = base + "/shared"
    owner_api = mk_api(
        store=store,
        sources=sources,
        tags=tags,
        share_base_url=shared,
        title=title,
        overviews=overviews,
    )
    app.mount(base + "/api", owner_api)
    app.mount(shared, mk_share_api(shares=owner_api.state.shares, title=title))
    app.state.store = store
    app.state.base_path = base
    app.add_middleware(
        _AuthGate, authorizer=authorizer, public=(shared,)
    )  # pure ASGI, never BaseHTTPMiddleware
    return app


def _meta_or_404(store: DocStore, doc_id: str, *, settle: bool = True) -> dict:
    try:
        return store.meta(doc_id, settle=settle)
    except (KeyError, ValueError):
        raise HTTPException(404, "no such document")


def _is_loopback(host: str) -> bool:
    """True for ``localhost`` and any loopback address (``127.0.0.1``, ``::1``)."""
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]").partition("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = DFLT_SERVE_PORT,
    data_dir: str | None = None,
    base_path: str = DFLT_BASE_PATH,
    allow_open: bool = False,
) -> None:
    """Run the standalone server with uvicorn (``pip install 'annals[server]'``).

    Refuses (``ValueError``) a non-loopback ``host`` while no auth is configured in the
    environment, because everyone reaching the port would be the owner. ``allow_open=True``
    is the explicit override, for a host that does its own gating in front.
    """
    import uvicorn

    authorizer = authorizer_from_env()
    if authorizer is no_auth and not _is_loopback(host) and not allow_open:
        raise ValueError(
            f"refused: host {host!r} is reachable beyond this machine and no auth is configured, "
            "so anyone who can reach the port would read every document. Set ANNALS_WHOAMI_URL + "
            "ANNALS_ALLOWED_USERS or ANNALS_BASIC_USER + ANNALS_BASIC_PASSWORD, bind to 127.0.0.1, "
            "or pass allow_open=True (--allow-open) if something in front of it does the gating."
        )
    app = mk_app(
        data_dir=data_dir or os.environ.get(ENV_DATA_DIR),
        base_path=base_path,
        authorizer=authorizer,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")
