"""The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This module is the single source of truth for what a annals can do. The CLI
(:mod:`annals.__main__`, via ``cw``), the MCP server (``py2mcp`` over string refs to these
names) and the shipped skill all describe the same functions, so there is nothing to keep
in parity. Nothing here prints or exits; the surfaces do that.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from annals.config import Settings, default_data_dir, load_settings, write_config
from annals.store import DocStore, check_id
from annals.target import parse_target

_dispatch_funcs: list = []  # filled at the bottom; the SSOT list every surface reads


def _store(settings: Settings) -> DocStore:
    return DocStore(parse_target(settings.target))


def _doc_url(settings: Settings, doc_id: str) -> str:
    return f"{settings.base_url}/d/{doc_id}"


def _group_url(settings: Settings, gid: str) -> str:
    return f"{settings.base_url}/g/{gid}"


def _default_source() -> dict:
    src = {"host": socket.gethostname(), "cwd": os.getcwd()}
    for key in ("ANNALS_SESSION", "CROWSNEST_SESSION", "CLAUDE_SESSION_NAME"):
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
    add_to: str | None = None,
    session: str | None = None,
    all_files: bool = False,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
) -> dict:
    """Publish one document and print its link; several paths become several documents.

    ``paths``: files of any kind (markdown, html, images, video, audio, pdf, text), a
    directory (one document: an ``index.html`` or single page with its assets, else a
    gallery of everything in it), or ``-`` for stdin (markdown). ``tags`` is comma separated. ``group``
    names a group to create from the published documents; the reply then carries
    ``group_url`` too. ``add_to`` appends them to an existing group instead (its id, as
    printed in a group link), so a second batch lands under the link the owner already has. ``session`` records who published (the source shown on the page). A directory skips
    hidden files and caches (``.*``, ``__pycache__``, ``*.pyc``) unless ``all_files``.
    ``to`` publishes to a named target of the config file (``[targets.NAME]``, see
    ``annals configure --to``) instead of the default one.
    """
    settings = load_settings(target=target, base_url=base_url, to=to)
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
            meta = store.publish(
                Path(p),
                title=title if len(paths) == 1 else None,
                tags=tag_list,
                source=source,
                **({"exclude": ()} if all_files else {}),
            )
        docs.append(
            {
                "id": meta["id"],
                "title": meta["title"],
                "url": _doc_url(settings, meta["id"]),
            }
        )
    result: dict = docs[0] if len(docs) == 1 else {"docs": docs}
    if not settings.configured:
        result["warning"] = (
            f"no annals config: published to the local {settings.target} and linked to a local "
            f"server. To publish where the owner reads, run `annals configure --target "
            f"host:/path --base-url https://.../annals` (see `annals configure`)."
        )
    if group and add_to:
        raise ValueError(
            "pass --group (a new group) or --add-to (an existing one), not both"
        )
    if group or add_to:
        ids = [d["id"] for d in docs]
        g = store.add_to_group(add_to, ids) if add_to else store.make_group(group, ids)
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
    to: str | None = None,
) -> dict:
    """List documents (newest first), optionally filtered by words or showing the bin.

    ``to`` lists a named target instead of the default one.
    """
    settings = load_settings(target=target, base_url=base_url, to=to)
    store = _store(settings)
    docs = store.search(q, trash=trash) if q else store.list(trash=trash)
    return {
        "docs": [
            {
                "id": m["id"],
                "title": m["title"],
                "kind": m["kind"],
                "tags": m.get("tags", []),
                "created": m.get("created"),
                "url": _doc_url(settings, m["id"]),
            }
            for m in docs[:limit]
        ],
        "total": len(docs),
    }


def show(
    doc_id: str,
    *,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
) -> dict:
    """A document's metadata and link (``to``: on a named target)."""
    settings = load_settings(target=target, base_url=base_url, to=to)
    meta = _store(settings).meta(doc_id)
    meta["url"] = _doc_url(settings, doc_id)
    return meta


def trash(
    doc_ids: list[str], *, target: str | None = None, to: str | None = None
) -> dict:
    """Move documents to the recycle bin (restorable)."""
    store = _store(load_settings(target=target, to=to))
    return {"trashed": [store.trash(i)["id"] for i in _as_list(doc_ids)]}


def restore(
    doc_ids: list[str], *, target: str | None = None, to: str | None = None
) -> dict:
    """Bring documents back from the recycle bin."""
    store = _store(load_settings(target=target, to=to))
    return {"restored": [store.restore(i)["id"] for i in _as_list(doc_ids)]}


def group(
    title: str,
    doc_ids: list[str],
    *,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
) -> dict:
    """Make a group (one URL for a set of documents) from existing document ids."""
    settings = load_settings(target=target, base_url=base_url, to=to)
    g = _store(settings).make_group(title, _as_list(doc_ids))
    return {
        "id": g["id"],
        "title": g["title"],
        "docs": g["docs"],
        "url": _group_url(settings, g["id"]),
    }


def groups(
    *, target: str | None = None, base_url: str | None = None, to: str | None = None
) -> dict:
    """List groups, newest first."""
    settings = load_settings(target=target, base_url=base_url, to=to)
    return {
        "groups": [
            {
                "id": g["id"],
                "title": g["title"],
                "n": len(g["docs"]),
                "url": _group_url(settings, g["id"]),
            }
            for g in _store(settings).list_groups()
        ]
    }


def configure(
    *,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
) -> dict:
    """Write the publisher config (where to publish, what link to print) and show it.

    Example: ``annals configure --target tw:/root/.local/share/annals --base-url https://apps.example.com/annals``.
    ``--to NAME`` saves the target and base url as a named target (``annals publish --to NAME``)
    and leaves the default alone. With no arguments, shows the resolved settings without writing.
    """
    if to and (target or base_url):
        # Resolve a partly-given named target against what is already saved under it.
        try:
            settings = load_settings(target=target, base_url=base_url, to=to)
        except ValueError:
            if not (target and base_url):
                raise ValueError(
                    f"a new named target needs both --target and --base-url ({to!r} is not saved yet)"
                ) from None
            settings = load_settings(target=target, base_url=base_url)
    else:
        settings = load_settings(target=target, base_url=base_url, to=to)
    out = settings.as_dict()
    if target or base_url:
        out["config_path"] = str(write_config(settings, to=to))
    out["local_data_dir"] = str(default_data_dir())
    return out


def _parse_ref(ref: str) -> tuple[str, str]:
    """``("group"|"doc"|"id", id)`` from a link (``.../g/<id>``, ``.../d/<id>``) or a bare id."""
    parts = ref.strip().rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2] in ("g", "d"):
        return ("group" if parts[-2] == "g" else "doc"), parts[-1]
    return "id", parts[-1]


def _same_place(a: str, b: str) -> bool:
    """True when two target specs name the same directory (or the same ssh host:path)."""
    ta, tb = parse_target(a), parse_target(b)
    if hasattr(ta, "root") and hasattr(tb, "root"):
        return (
            Path(ta.root).expanduser().resolve() == Path(tb.root).expanduser().resolve()
        )
    return a.rstrip("/") == b.rstrip("/")


def _copy_doc(src: DocStore, dst: DocStore, doc_id: str) -> dict:
    import tempfile

    meta = src.meta(doc_id)
    rel = f"{'trash' if meta.get('in_trash') else 'docs'}/{doc_id}"
    with tempfile.TemporaryDirectory(prefix="annals-copy-") as td:
        src.target.get_tree(rel, Path(td) / "doc")
        odd = [
            str(p.relative_to(td))
            for p in (Path(td) / "doc").rglob("*")
            if p.is_symlink() or not (p.is_file() or p.is_dir())
        ]
        if odd:
            raise ValueError(f"refusing to copy {doc_id}: not regular files: {odd[:3]}")
        dst.target.put_tree(Path(td) / "doc", f"docs/{doc_id}")
    return meta


def copy(
    refs: list[str],
    *,
    to: str,
    source: str | None = None,
    target: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Copy documents or groups to a named target, keeping their ids; print the new link.

    ``refs`` are links (``https://.../annals/d/<id>``, ``.../g/<group-id>``) or bare ids; only
    the id is used, so the link may point at any instance. They are read from the default
    target (or the named target ``source``) and written to the named target ``to``. A group
    is copied with its documents and keeps its id and title. Copying again refreshes the
    copy. The source must be readable from this machine (a directory, or ``host:/path``).
    ``target``/``base_url`` override the DESTINATION's location, as in ``publish``.
    """
    src_settings = load_settings(to=source)
    dst_settings = load_settings(target=target, base_url=base_url, to=to)
    if _same_place(src_settings.target, dst_settings.target):
        raise ValueError(
            f"source and destination are the same place: {src_settings.target}"
        )
    src, dst = _store(src_settings), _store(dst_settings)
    copied: list[dict] = []
    group_out: dict | None = None
    for ref in _as_list(refs):
        kind, ident = _parse_ref(ref)
        if kind == "id":
            try:
                src.group(ident)
                kind = "group"
            except KeyError:
                kind = "doc"
        if kind == "group":
            g = src.group(ident)
            check_id(g["id"])
            for doc_id in g["docs"]:
                m = _copy_doc(src, dst, doc_id)
                copied.append(
                    {
                        "id": doc_id,
                        "title": m["title"],
                        "url": _doc_url(dst_settings, doc_id),
                    }
                )
            dst.target.write_text(f"groups/{g['id']}.json", json.dumps(g, indent=1))
            group_out = {
                "group_id": g["id"],
                "group_url": _group_url(dst_settings, g["id"]),
            }
        else:
            m = _copy_doc(src, dst, ident)
            copied.append(
                {"id": ident, "title": m["title"], "url": _doc_url(dst_settings, ident)}
            )
    if group_out:
        return {**group_out, "url": group_out["group_url"], "docs": copied}
    return copied[0] if len(copied) == 1 else {"docs": copied}


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    data_dir: str | None = None,
    base_path: str = "/annals",
) -> None:
    """Serve the annals page and API (needs ``pip install 'annals[server]'``).

    Auth comes from the environment: ``ANNALS_WHOAMI_URL`` + ``ANNALS_ALLOWED_USERS`` to sit
    behind an existing login, ``ANNALS_BASIC_USER`` + ``ANNALS_BASIC_PASSWORD`` for HTTP Basic,
    nothing for an open server on localhost.
    """
    from annals.api import serve as _serve

    _serve(host=host, port=port, data_dir=data_dir, base_path=base_path)


def page_shell(
    *, api: str = "/api/annals", base: str = "/annals", title: str = "annals"
) -> str:
    """The page's html shell, for a host that serves the API under its own prefix.

    An enlace app writes it once as its frontend:
    ``annals page-shell --api /api/annals --base /annals > frontend/index.html``.
    The shell only names the two paths; the page's code loads from the API, so it upgrades
    with the package.
    """
    from annals.api import page_html

    return page_html(base=base, api=api, title=title)


_dispatch_funcs[:] = [
    publish,
    ls,
    show,
    trash,
    restore,
    group,
    groups,
    copy,
    configure,
    serve,
    page_shell,
]
