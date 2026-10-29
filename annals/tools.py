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
from annals.store import DocStore, check_artifact_url, check_id, split_version
from annals.target import SshTarget, parse_target

_dispatch_funcs: list = []  # filled at the bottom; the SSOT list every surface reads


def _store(settings: Settings) -> DocStore:
    return DocStore(parse_target(settings.target), settle=not settings.outbox)


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
    replace: str | None = None,
    artifact: str | None = None,
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
    ``annals configure --to``) instead of the default one. ``replace`` (a document's link or
    id) publishes ONE path as a new version of that document: the link stays the same, the
    page shows the new version and offers the earlier ones. That is how a living page (a
    guide, a status page) keeps one link. ``artifact`` (a claude.ai artifact link) is the
    interactive version of the page: the document's page shows an "Open the interactive
    version" button. Publish the Artifact first, then the same page here with its link.
    """
    settings = load_settings(target=target, base_url=base_url, to=to)
    if artifact is not None:
        artifact = check_artifact_url(artifact)
        if len(_as_list(paths)) > 1:
            raise ValueError("--artifact takes one path: the page it is the version of")
    store = _store(settings)
    tag_list = [t for t in tags.split(",") if t.strip()]
    source = _default_source()
    if session:
        source["session"] = session
    docs = []
    paths = _as_list(paths)
    replace_id = None
    if replace:
        if len(paths) > 1:
            raise ValueError(
                "--replace takes one path: the new version of one document"
            )
        kind, replace_id = _parse_ref(replace)
        if kind == "group":
            raise ValueError("--replace names a document, not a group")
    for p in paths:
        if p == "-":
            import sys

            text = sys.stdin.read()
            meta = store.publish(
                title=title,
                tags=tag_list,
                source=source,
                text=text,
                replace=replace_id,
                artifact=artifact,
            )
        else:
            meta = store.publish(
                Path(p),
                title=title if len(paths) == 1 else None,
                tags=tag_list,
                source=source,
                replace=replace_id,
                artifact=artifact,
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


def aggregate(
    group_id: str,
    *,
    demote: int = 1,
    order: str = "numbered",
    no_toc: bool = False,
    keep_wraps: bool = False,
    target: str | None = None,
    to: str | None = None,
) -> str:
    """Every markdown file of a group as ONE markdown document, printed (nothing is stored).

    ``group_id`` is a group's id or link. The document has the group's title, a table of
    contents, then one ``##`` section per file named after its path (a folder document's
    files under its title). ``order``: ``numbered`` puts paths that start with a number
    first, numerically, the rest in the group's order; ``given`` keeps the group's order.
    ``demote`` pushes each file's headings that many levels down (``0``: as written).
    Hard-wrapped lines are joined unless ``keep_wraps``; ``no_toc`` leaves out the table
    of contents. Redirect
    to save it: ``annals aggregate <id> > bundle.md``.
    """
    from annals.aggregate import aggregate_markdown, doc_markdown_files, numbered_first

    orders = {"numbered": numbered_first, "given": None}
    if order not in orders:
        raise ValueError(f"order must be one of {', '.join(orders)}, not {order!r}")
    store = _store(load_settings(target=target, to=to))
    g, metas = store.group_docs(_parse_ref(group_id)[1])
    files = list(
        doc_markdown_files(
            ((m, m.get("files", [])) for m in metas), read=store.read_text
        )
    )
    if not files:
        raise ValueError(f"group {g['id']} has no markdown files")
    return aggregate_markdown(
        files,
        title=g.get("title") or g["id"],
        order=orders[order],
        demote=demote,
        toc=not no_toc,
        unwrap=not keep_wraps,
    )


def configure(
    *,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
    outbox: bool = False,
    share_base_url: str | None = None,
) -> dict:
    """Write the publisher config (where to publish, what link to print) and show it.

    Example: ``annals configure --target tw:/root/.local/share/annals --base-url https://apps.example.com/annals``.
    ``--to NAME`` saves the target and base url as a named target (``annals publish --to NAME``)
    and leaves the default alone. ``--outbox`` marks the target as an outbox: a directory
    the server pulls and empties (it cannot be written to from here), so replacements are
    left for the server to apply; it is kept by later changes (``ANNALS_OUTBOX=0`` or an
    edit of the file turns it off). ``--share-base-url`` is where share links point when
    the share server is not at ``<base-url>/shared`` (a platform running it as its own
    public app). With no arguments, shows the resolved settings without writing.
    """
    writing = bool(target or base_url or outbox or share_base_url)
    if to and writing:
        # Resolve a partly-given named target against what is already saved under it.
        try:
            settings = load_settings(
                target=target,
                base_url=base_url,
                to=to,
                outbox=outbox or None,
                share_base_url=share_base_url,
            )
        except ValueError:
            if not (target and base_url):
                raise ValueError(
                    f"a new named target needs both --target and --base-url ({to!r} is not saved yet)"
                ) from None
            settings = load_settings(
                target=target,
                base_url=base_url,
                outbox=outbox,
                share_base_url=share_base_url,
            )
    else:
        current = load_settings(to=to)  # what a partial change applies to
        settings = load_settings(
            target=target or (current.target if writing else None),
            base_url=base_url,
            to=to,
            outbox=(outbox or current.outbox) if writing else None,
            share_base_url=share_base_url,
        )
    out = settings.as_dict()
    if writing:
        out["config_path"] = str(write_config(settings, to=to))
    out["local_data_dir"] = str(default_data_dir())
    return out


def _parse_ref(ref: str) -> tuple[str, str]:
    """``("group"|"doc"|"id", id)`` from a link (``.../g/<id>``, ``.../d/<id>``) or a bare id."""
    parts = ref.strip().rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2] in ("g", "d"):
        return ("group" if parts[-2] == "g" else "doc"), parts[-1]
    return "id", parts[-1]


def _place_key(spec: str, *, resolve_home: bool = False) -> tuple:
    """``("ssh", host, root)`` or ``("local", root)``: what makes two target specs one place.

    Roots are normalised (``..``, repeated or trailing slashes). A ``~/`` root on an ssh
    target is the remote home, which only the remote knows; ``resolve_home`` asks it (one
    ssh call), otherwise the ``~`` stays literal.
    """
    import posixpath

    target = parse_target(spec)
    if isinstance(target, SshTarget):
        root = target.root
        if root == "~" or root.startswith("~/"):
            if resolve_home:
                home = target._ssh('printf %s "$HOME"').strip()
                root = home + root[1:]
        return ("ssh", target.host, posixpath.normpath(root))
    if hasattr(target, "root"):
        return ("local", str(Path(target.root).expanduser().resolve()))
    return ("other", spec.rstrip("/"))


def _same_place(a: str, b: str) -> bool:
    """True when two target specs name the same directory, or the same directory on the same ssh host.

    A local path and an ssh target are never the same place, nor are two hosts with equal roots.
    ``host:~/x`` and ``host:/home/u/x`` are compared by asking the host for its home, only when
    that is the one thing that could make them equal.
    """
    ka, kb = _place_key(a), _place_key(b)
    if ka == kb:
        return True
    if ka[0] == kb[0] == "ssh" and ka[1] == kb[1] and ("~" in (ka[2][:1], kb[2][:1])):
        try:
            return _place_key(a, resolve_home=True) == _place_key(b, resolve_home=True)
        except (
            Exception
        ):  # remote unreachable: say "different"; the copy itself will fail loudly
            return False
    return False


def _copy_doc(src: DocStore, dst: DocStore, doc_id: str) -> dict:
    import tempfile

    if split_version(doc_id)[1] is not None:
        raise ValueError(
            f"{doc_id} is a version; copy the document (it keeps its versions)"
        )
    meta = src.meta(doc_id)
    rel = src.doc_rel(doc_id)
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


def _shares(settings: Settings):
    """The share records where the documents live. An outbox is emptied by another
    machine, so a link made there would point at documents it no longer holds."""
    from annals.share import Shares

    if settings.outbox:
        raise ValueError(
            f"{settings.target} is an outbox (another machine pulls it), so it cannot "
            f"share: make the link with the Share button at {settings.base_url}, or run "
            "`annals share` where the documents live (or pass --to <target>)."
        )
    return Shares(_store(settings))


def _split(x) -> list[str]:
    if x is None:
        return []
    items = x.split(",") if isinstance(x, str) else list(x)
    return [i.strip() for i in items if i and i.strip()]


def _share_out(settings: Settings, rec: dict) -> dict:
    from annals.share import share_url

    return {
        "id": rec["token"],
        "title": rec.get("title"),
        "url": share_url(settings.share_base_url, rec["token"]),
        "root": rec["root"],
        "files": {d: len(fs) for d, fs in rec.get("docs", {}).items()},
        "expires": rec.get("expires"),
        "protected": rec.get("protected", False),
        "revoked": rec.get("revoked"),
        "created": rec.get("created"),
    }


def share(
    ref: str,
    *,
    password: str | None = None,
    expires: str = "7d",
    include: str | None = None,
    exclude: str | None = None,
    title: str | None = None,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
) -> dict:
    """Make a public link to ONE document (or group) and print it; nothing else is reachable.

    ``ref`` is a document or group id, or its link. The link opens without a login, shows
    only that page and the files chosen, and can be revoked (``annals unshare``).
    ``include``: comma separated files of the document to share (the page itself always
    is), or ids of other annals pages it links to; by default every file of the document
    (for a group: every document; ``include`` then picks documents). ``exclude`` drops
    files. ``expires`` (7 days unless told): ``12h``, ``30d``, ``2w``, a date (``2026-11-01``,
    through that day, UTC), an ISO time, or ``never``. ``password`` gates the link (stored hashed; ``-`` reads it from
    stdin, so it stays out of the shell history).
    """
    settings = load_settings(target=target, base_url=base_url, to=to)
    if password == "-":
        import sys

        password = sys.stdin.readline().rstrip("\n")
    rec = _shares(settings).create(
        _parse_ref(ref)[1],
        include=_split(include) or None,
        exclude=_split(exclude),
        password=password,
        expires=expires,
        title=title,
    )
    out = _share_out(settings, rec)
    notes = [f"expires {out['expires']}" if out["expires"] else "never expires"]
    if out["protected"]:
        notes.append("password-protected")
    n = sum(out["files"].values())
    notes.append(f"{n} file{'s' if n != 1 else ''} shared")
    result = {
        "url": out["url"],
        "id": out["id"],
        "title": out["title"],
        "note": ", ".join(notes),
    }
    from urllib.parse import urlsplit

    local = urlsplit(settings.base_url).hostname in ("127.0.0.1", "localhost", "::1")
    if settings.share_base_url == f"{settings.base_url}/shared" and not local:
        result["warning"] = (
            "this link assumes the annals server serves shares at <base_url>/shared, "
            "as `annals serve` does; inside an app platform the share server runs as its "
            "own public app: set its address with `annals configure --share-base-url ...`"
        )
    return result


def shares(
    *,
    all: bool = False,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
) -> dict:
    """List share links, newest first (``all``: revoked and expired ones too)."""
    settings = load_settings(target=target, base_url=base_url, to=to)
    recs = _shares(settings).list(all=all)
    return {"shares": [_share_out(settings, r) for r in recs]}


def unshare(
    links: list[str],
    *,
    target: str | None = None,
    to: str | None = None,
) -> dict:
    """Revoke share links (their token or full link): they stop working at once."""
    settings = load_settings(target=target, to=to)
    s = _shares(settings)
    tokens = [x.strip().rstrip("/").split("/")[-1] for x in _as_list(links)]
    return {"revoked": [s.revoke(t)["token"] for t in tokens]}


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    data_dir: str | None = None,
    base_path: str = "/annals",
    allow_open: bool = False,
) -> None:
    """Serve the annals page and API (needs ``pip install 'annals[server]'``).

    Auth comes from the environment: ``ANNALS_WHOAMI_URL`` + ``ANNALS_ALLOWED_USERS`` to sit
    behind an existing login, ``ANNALS_BASIC_USER`` + ``ANNALS_BASIC_PASSWORD`` for HTTP Basic,
    nothing for an open server on localhost. A host reachable beyond this machine with no auth
    configured is refused unless ``allow_open`` (``--allow-open``) says something else gates it.
    """
    from annals.api import serve as _serve

    _serve(
        host=host,
        port=port,
        data_dir=data_dir,
        base_path=base_path,
        allow_open=allow_open,
    )


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
    aggregate,
    copy,
    share,
    shares,
    unshare,
    configure,
    serve,
    page_shell,
]
