"""The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This module is the single source of truth for what a tray can do. The CLI
(:mod:`tray.__main__`, via ``cw``), the MCP server (``py2mcp`` over string refs to these
names) and the shipped skill all describe the same functions, so there is nothing to keep
in parity. Nothing here prints or exits; the surfaces do that.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

from tray.config import Settings, default_data_dir, load_settings, write_config
from tray.store import DocStore
from tray.target import parse_target

_dispatch_funcs: list = []  # filled at the bottom; the SSOT list every surface reads


def _store(settings: Settings) -> DocStore:
    return DocStore(parse_target(settings.target))


def _doc_url(settings: Settings, doc_id: str) -> str:
    return f"{settings.base_url}/d/{doc_id}"


def _group_url(settings: Settings, gid: str) -> str:
    return f"{settings.base_url}/g/{gid}"


def _default_source() -> dict:
    src = {"host": socket.gethostname(), "cwd": os.getcwd()}
    for key in ("TRAY_SESSION", "CROWSNEST_SESSION", "CLAUDE_SESSION_NAME"):
        if os.environ.get(key):
            src["session"] = os.environ[key]
            break
    return src


def _as_list(x) -> list[str]:
    items = [x] if isinstance(x, str) else list(x)
    if not items:
        raise ValueError("nothing given: pass at least one path or id")
    return items


def publish(
    paths: list[str],
    *,
    title: str | None = None,
    tags: str = "",
    group: str | None = None,
    session: str | None = None,
    target: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Publish one document and print its link; several paths become several documents.

    ``paths``: markdown or html files, a directory (an html artifact with ``index.html``
    and its assets), or ``-`` for stdin (markdown). ``tags`` is comma separated. ``group``
    names a group to create from the published documents; the reply then carries
    ``group_url`` too. ``session`` records who published (the source shown on the page).
    """
    settings = load_settings(target=target, base_url=base_url)
    store = _store(settings)
    tag_list = [t for t in tags.split(",") if t.strip()]
    source = _default_source()
    if session:
        source["session"] = session
    docs = []
    paths = _as_list(paths)
    for p in paths:
        if p == "-":
            import sys

            text = sys.stdin.read()
            meta = store.publish(title=title, tags=tag_list, source=source, text=text)
        else:
            meta = store.publish(Path(p), title=title if len(paths) == 1 else None, tags=tag_list, source=source)
        docs.append({"id": meta["id"], "title": meta["title"], "url": _doc_url(settings, meta["id"])})
    result: dict = docs[0] if len(docs) == 1 else {"docs": docs}
    if group:
        g = store.make_group(group, [d["id"] for d in docs])
        result["group_id"] = g["id"]
        result["group_url"] = _group_url(settings, g["id"])
        result["url"] = result["group_url"] if len(docs) > 1 else result["url"]
    return result


def ls(
    q: str = "",
    *,
    trash: bool = False,
    limit: int = 50,
    target: str | None = None,
    base_url: str | None = None,
) -> dict:
    """List documents (newest first), optionally filtered by words or showing the bin."""
    settings = load_settings(target=target, base_url=base_url)
    store = _store(settings)
    docs = store.search(q, trash=trash) if q else store.list(trash=trash)
    return {
        "docs": [
            {"id": m["id"], "title": m["title"], "kind": m["kind"], "tags": m.get("tags", []),
             "created": m.get("created"), "url": _doc_url(settings, m["id"])}
            for m in docs[:limit]
        ],
        "total": len(docs),
    }


def show(doc_id: str, *, target: str | None = None, base_url: str | None = None) -> dict:
    """A document's metadata and link."""
    settings = load_settings(target=target, base_url=base_url)
    meta = _store(settings).meta(doc_id)
    meta["url"] = _doc_url(settings, doc_id)
    return meta


def trash(doc_ids: list[str], *, target: str | None = None) -> dict:
    """Move documents to the recycle bin (restorable)."""
    store = _store(load_settings(target=target))
    return {"trashed": [store.trash(i)["id"] for i in _as_list(doc_ids)]}


def restore(doc_ids: list[str], *, target: str | None = None) -> dict:
    """Bring documents back from the recycle bin."""
    store = _store(load_settings(target=target))
    return {"restored": [store.restore(i)["id"] for i in _as_list(doc_ids)]}


def group(
    title: str,
    doc_ids: list[str],
    *,
    target: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Make a group (one URL for a set of documents) from existing document ids."""
    settings = load_settings(target=target, base_url=base_url)
    g = _store(settings).make_group(title, _as_list(doc_ids))
    return {"id": g["id"], "title": g["title"], "docs": g["docs"], "url": _group_url(settings, g["id"])}


def groups(*, target: str | None = None, base_url: str | None = None) -> dict:
    """List groups, newest first."""
    settings = load_settings(target=target, base_url=base_url)
    return {
        "groups": [
            {"id": g["id"], "title": g["title"], "n": len(g["docs"]), "url": _group_url(settings, g["id"])}
            for g in _store(settings).list_groups()
        ]
    }


def configure(*, target: str | None = None, base_url: str | None = None) -> dict:
    """Write the publisher config (where to publish, what link to print) and show it.

    Example: ``tray configure --target tw:/root/.local/share/tray --base-url https://apps.example.com/tray``.
    With no arguments, shows the resolved settings without writing.
    """
    settings = load_settings(target=target, base_url=base_url)
    out = settings.as_dict()
    if target or base_url:
        out["config_path"] = str(write_config(settings))
    out["local_data_dir"] = str(default_data_dir())
    return out


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    data_dir: str | None = None,
    base_path: str = "/tray",
) -> None:
    """Serve the tray page and API (needs ``pip install 'tray[server]'``).

    Auth comes from the environment: ``TRAY_WHOAMI_URL`` + ``TRAY_ALLOWED_USERS`` to sit
    behind an existing login, ``TRAY_BASIC_USER`` + ``TRAY_BASIC_PASSWORD`` for HTTP Basic,
    nothing for an open server on localhost.
    """
    from tray.api import serve as _serve

    _serve(host=host, port=port, data_dir=data_dir, base_path=base_path)


_dispatch_funcs[:] = [publish, ls, show, trash, restore, group, groups, configure, serve]
