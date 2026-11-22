"""The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This module is the single source of truth for what a annals can do. The CLI
(:mod:`annals.__main__`, via ``cw``), the MCP server (``py2mcp`` over string refs to these
names) and the shipped skill all describe the same functions, so there is nothing to keep
in parity. Nothing here prints or exits; the surfaces do that.
"""

from __future__ import annotations

import json
import os
from contextlib import suppress
import socket
from pathlib import Path

from annals.catalog import owner_tags, with_owner_tags
from annals.config import (
    Settings,
    default_data_dir,
    link_target,
    load_settings,
    named_targets,
    write_config,
)
from annals.docfilter import DocFilter, parse_meta
from annals.store import (
    META,
    SIDECAR_MEDIA_KINDS,
    DocStore,
    check_artifact_url,
    check_id,
    clean_title,
    is_sidecar_of,
    kind_of,
    split_version,
    without_provenance,
)
from annals.sessions import session_url_from_env
from annals.target import SshTarget, check_rel, parse_target

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
    with suppress(ValueError):  # a bridge id that makes no valid link is left out
        if url := session_url_from_env():
            src["session_url"] = check_artifact_url(url)
    return src


def _document_meta(store: DocStore, ref: str) -> dict:
    """The meta of the document ``ref`` names (id or link); a group or a missing id is a plain error."""
    kind, name = _parse_ref(ref)
    if kind == "group":
        raise ValueError("this names a group, not a document")
    try:
        return store.meta(name)
    except (KeyError, ValueError):
        raise ValueError(f"no such document: {name}") from None


def _checked_output(output: str | None) -> Path | None:
    """``output`` as a path (``~`` expanded), refused before any work if it cannot be written."""
    if not output:
        return None
    dest = Path(output).expanduser()
    if dest.is_dir() or not dest.parent.is_dir():
        raise ValueError(
            f"cannot write {output}: it is a folder, or its folder does not exist"
        )
    return dest


def _file_opener(store: DocStore, scratch: Path):
    """``(doc_id, rel) -> Path`` of a document's file: in place for a local store (refusing a link out of the document's folder, as the page's raw route does), else the document is fetched once into ``scratch``."""
    fetched: dict[str, Path] = {}

    def open_path(doc_id: str, rel: str) -> Path:
        check_rel(rel)
        doc_rel = store.doc_rel(doc_id)
        doc_dir = store.target.local_path(doc_rel)
        if (
            doc_dir is not None
        ):  # a local store: in place, but never out of the document's folder
            here = store.target.local_path(f"{doc_rel}/{rel}")
            if here is None or not here.is_relative_to(doc_dir) or not here.is_file():
                raise FileNotFoundError(f"{rel}: not a file of this document")
            return here
        if doc_id not in fetched:
            dst = scratch / doc_id
            store.target.get_tree(doc_rel, dst)
            fetched[doc_id] = dst
        return fetched[doc_id] / rel

    return open_path


def _resolve_selection(
    store: DocStore, ref: str, *, also=None
) -> tuple[str, list[dict]]:
    """A title and the meta of what ``ref`` names: a group's documents, or a document (``also``: more documents).

    ``ref`` is a group's or a document's id or link; a bare id may be either. Raises a
    ``KeyError``/``ValueError`` for what does not exist, in words of "no such document or group".
    """
    kind, name = _parse_ref(ref)
    try:
        if kind == "doc":
            raise KeyError(name)  # named as a document: no group to look for
        g, metas = store.group_docs(name)
        title = g.get("title") or g["id"]
    except (KeyError, ValueError):
        if kind == "group":
            raise ValueError(f"no such group: {name}") from None
        try:
            meta = store.meta(name)  # a bare id may be a document's
        except (KeyError, ValueError):
            raise ValueError(f"no such document or group: {name}") from None
        title, metas = meta.get("title") or meta["id"], [meta]
    if also:
        if kind == "group":
            raise ValueError("--also adds documents to a document, not to a group")
        extra = [store.meta(_parse_ref(i)[1]) for i in _as_list(also)]
        metas = list({m["id"]: m for m in [*metas, *extra]}.values())
        title = f"{len(metas)} documents"
    return title, metas


def _as_list(x) -> list[str]:
    items = [x] if isinstance(x, str) else list(x)
    if not items:
        raise ValueError("nothing given: pass at least one path or id")
    return items


#: the suffixes whose text the link check reads (prose an author writes by hand)
LINK_CHECKED_SUFFIXES = frozenset({".md", ".markdown", ".txt"})


def _link_warning(label: str, text: str) -> str | None:
    """The unlinked-mention warning for one document's text, prefixed with its ``label``."""
    from annals.linkcheck import unlinked_warning

    w = unlinked_warning(text)
    return f"{label}: {w}" if w else None


def _with_sidecars(paths: list[str]) -> list[list[str]]:
    """The paths as documents: an audio or video file takes its timed text along.

    ``talk.mp3 talk.vtt talk.chapters.vtt notes.md`` is two documents, the audio (with its
    transcript and chapters, which its page plays with it) and the notes.

    >>> _with_sidecars(["a/talk.mp3", "a/talk.vtt", "notes.md", "a/talk.chapters.vtt"])
    [['a/talk.mp3', 'a/talk.vtt', 'a/talk.chapters.vtt'], ['notes.md']]
    """
    media = [p for p in paths if p != "-" and kind_of(p) in SIDECAR_MEDIA_KINDS]
    claimed: dict[str, list[str]] = {m: [] for m in media}
    taken: set[str] = set()
    for q in paths:  # first, which files are whose timed text, wherever they are listed
        owner = next(
            (
                m
                for m in media
                if q != m and q != "-" and is_sidecar_of(str(Path(q)), str(Path(m)))
            ),
            None,
        )
        if owner is not None and q not in taken:
            claimed[owner].append(q)
            taken.add(q)
    return [[p, *claimed.get(p, [])] for p in paths if p not in taken]


def _link_warning_for_file(path: Path) -> str | None:
    """The unlinked-mention warning for a markdown or text file; None for anything else."""
    if path.suffix.lower() not in LINK_CHECKED_SUFFIXES or not path.is_file():
        return None
    try:
        return _link_warning(path.name, path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def publish(
    paths: list[str],
    *,
    title: str | None = None,
    tags: str = "",
    group: str | None = None,
    add_to: str | None = None,
    session: str | None = None,
    session_url: str | None = None,
    all_files: bool = False,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
    replace: str | None = None,
    artifact: str | None = None,
    no_link_check: bool = False,
    no_pdf: bool = False,
    meta: list[str] | None = None,
) -> dict:
    """Publish one document and print its link; several paths become several documents.

    An audio or video file takes its timed text along as one document: ``talk.mp3
    talk.vtt talk.chapters.vtt`` (or ``talk.cues.json``) is one audio document whose page
    shows the transcript and chapters (``annals.store.SIDECAR_SUFFIXES``).

    ``paths``: files of any kind (markdown, html, images, video, audio, pdf, text), a
    directory (one document: an ``index.html`` or single page with its assets, else a
    gallery of everything in it), or ``-`` for stdin (markdown). ``tags`` is comma separated. ``group``
    names a group to create from the published documents; the reply then carries
    ``group_url`` too. ``add_to`` appends them to an existing group instead (its id, as
    printed in a group link), so a second batch lands under the link the owner already has. ``session`` records who published (the source shown on the page), and ``session_url``
    the claude.ai link that opens that session; by default the link of the Claude Code session
    this runs in (``CLAUDE_CODE_BRIDGE_SESSION_ID``), ``none`` for no link. The document's page
    shows each session that made it, linked, under its title; a share or a room never does
    (:mod:`annals.sessions`). A directory skips
    hidden files and caches (``.*``, ``__pycache__``, ``*.pyc``) unless ``all_files``.
    ``to`` publishes to a named target of the config file (``[targets.NAME]``, see
    ``annals configure --to``) instead of the default one. ``replace`` (a document's link or
    id) publishes ONE path as a new version of that document: the link stays the same, the
    page shows the new version and offers the earlier ones. That is how a living page (a
    guide, a status page) keeps one link. ``artifact`` (a claude.ai artifact link) is the
    interactive version of the page: the document's page shows an "Open the interactive
    version" button. Publish the Artifact first, then the same page here with its link.
    A markdown or text document that mentions an issue or a Slack/email/chat message
    without linking to it gets a warning on stderr (:mod:`annals.linkcheck`); it is
    published either way. ``no_link_check`` turns that check off.

    An html page gets its own Download PDF button, inside the page, so it survives "open
    full page", raw links and shares, and ``<stem>.pdf`` printed beside it (headless
    Chromium, the ``pdf`` extra; without it the button opens the print dialog). A page that
    already has its PDF says so with ``<link rel="alternate" type="application/pdf"
    href="...">``; one with its own button marks it ``data-annals-pdf``; ``no_pdf`` (or
    ``data-annals-pdf="off"`` on ``<html>``/``<body>``) leaves the page as it is
    (:mod:`annals.pagepdf`).

    ``meta`` (``--meta key=value [key=value ...]``) records what the document belongs to, next
    to ``host``, ``cwd`` and ``session`` in its ``source``: by convention ``corpus`` (the
    repository or body of work), ``repo``, ``issue`` (the issue it answers), ``item`` (a
    desk item) and ``kind`` (report, brief, overview, render); other keys are kept as given.
    ``ls --session/--meta`` finds them again. The CLI's ``--json`` prints the result below
    (``id``, ``title``, ``url``, and with a group ``group_id`` and ``group_url``; several
    paths give ``docs``) as JSON and nothing else on stdout; that shape is a contract
    (``misc/docs/design.md``).
    """
    settings = load_settings(target=target, base_url=base_url, to=to)
    if artifact is not None:
        artifact = check_artifact_url(artifact)
        if len(_with_sidecars(_as_list(paths))) > 1:
            raise ValueError("--artifact takes one path: the page it is the version of")
    store = _store(settings)
    if group and add_to:
        raise ValueError(
            "pass --group (a new group) or --add-to (an existing one), not both"
        )
    if group:  # refused before anything is published: a retry must not publish twice
        group = clean_title(group)
    if add_to:
        try:
            store.group(add_to)
        except (KeyError, ValueError):
            raise ValueError(f"no such group: {add_to}")
    tag_list = [t for t in tags.split(",") if t.strip()]
    source = _default_source()
    source.update(parse_meta(meta))
    if session:
        source["session"] = session
    if session_url == "none":
        source.pop("session_url", None)
    elif session_url:
        source["session_url"] = check_artifact_url(session_url)
    if settings.room:  # an outside audience reads it: where it came from stays here
        source, artifact = {}, None
    docs = []
    link_warnings = []
    units = _with_sidecars(_as_list(paths))
    replace_id = None
    if replace:
        if len(units) > 1:
            raise ValueError(
                "--replace takes one path: the new version of one document"
            )
        kind, replace_id = _parse_ref(replace)
        if kind == "group":
            raise ValueError("--replace names a document, not a group")
    for p, *sidecars in units:
        if p == "-":
            import sys

            text = sys.stdin.read()
            if not no_link_check:
                link_warnings.append(_link_warning("stdin", text))
            meta = store.publish(
                title=title,
                tags=tag_list,
                source=source,
                text=text,
                replace=replace_id,
                artifact=artifact,
                pdf=not no_pdf,
            )
        else:
            if not no_link_check:
                link_warnings.append(_link_warning_for_file(Path(p)))
            meta = store.publish(
                Path(p),
                *(Path(q) for q in sidecars),
                title=title if len(units) == 1 else None,
                tags=tag_list,
                source=source,
                replace=replace_id,
                artifact=artifact,
                pdf=not no_pdf,
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
    warnings = [w for w in link_warnings if w]
    if not settings.configured:
        warnings.insert(
            0,
            (
                f"no annals config: published to the local {settings.target} and linked to a local "
                f"server. To publish where the owner reads, run `annals configure --target "
                f"host:/path --base-url https://.../annals` (see `annals configure`)."
            ),
        )
    if warnings:
        result["warning"] = "\nannals: warning: ".join(warnings)
    if group or add_to:
        ids = [d["id"] for d in docs]
        try:
            g = (
                store.add_to_group(add_to, ids)
                if add_to
                else store.make_group(group, ids)
            )
        except (
            RuntimeError
        ) as e:  # the group is busy: the documents are published, say which
            note = f"published {', '.join(ids)} but not grouped ({e})"
            result["warning"] = (
                result["warning"] + "\nannals: warning: " if "warning" in result else ""
            ) + note
            return result
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
    since: str | None = None,
    session: str | None = None,
    tag: str | None = None,
    meta: list[str] | None = None,
) -> dict:
    """List documents (newest first), optionally filtered by words or showing the bin.

    ``to`` lists a named target instead of the default one. The rest are exact filters,
    all of which must hold, for tools that poll: ``since`` (an ISO date or time, or an age
    like ``6h`` or ``2d``: published or replaced at or after it), ``session`` (the publishing session's
    name, whole, case-sensitive), ``tag`` (one tag, whole: the owner's own tags, set by ``annals tag``, win over the publisher's) and ``meta`` (``key=value``,
    several allowed, against the document's ``source``: ``corpus=annals``). A row is
    ``{id, title, kind, tags, created, updated, source, url}``; with ``--json`` that is the contract
    (``misc/docs/design.md``), and ``total`` counts the matches before ``limit``.
    """
    settings = load_settings(target=target, base_url=base_url, to=to)
    store = _store(settings)
    wanted = DocFilter.of(since=since, session=session, tag=tag, meta=meta)
    docs = wanted.apply(
        with_owner_tags(
            store.search(q, trash=trash) if q else store.list(trash=trash),
            owner_tags(store),
        )
    )
    return {
        "docs": [
            {
                "id": m["id"],
                "title": m["title"],
                "kind": m["kind"],
                "tags": m.get("tags", []),
                "created": m.get("created"),
                "updated": m.get("updated"),
                "source": m.get("source", {}),
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
    """A document's metadata, link, the groups it is in, and the annals links in its text.

    ``doc_id`` may be the document's link, on any annals this machine is configured for: the
    link finds its own place (``to`` names one explicitly). A group's link gives the group
    and its documents' links. ``links`` are the links to other annals documents and groups
    found in the document's text files, on any annals this machine can read: follow them
    with ``annals show`` or ``annals aggregate``. To read the text, use ``annals aggregate <link>``.
    """
    settings = _read_settings(doc_id, target=target, to=to, base_url=base_url)
    store = _store(settings)
    kind, ref = _parse_ref(doc_id)
    if kind == "group":  # a group's link: the group, with its documents' links
        g = store.group(ref)
        return {
            **g,
            "url": _group_url(settings, g["id"]),
            "doc_urls": [_doc_url(settings, i) for i in g["docs"]],
        }
    meta = with_owner_tags([store.meta(ref)], owner_tags(store))[0]
    meta["url"] = _doc_url(settings, ref)
    meta["groups"] = [  # a version is in the groups its document is in
        {**g, "url": _group_url(settings, g["id"])}
        for g in store.groups_of(meta.get("version_of") or ref)
    ]
    meta["links"] = [u for u in _annals_links(store, meta) if u != meta["url"]]
    return meta


def _read_settings(
    ref: str,
    *,
    target: str | None = None,
    to: str | None = None,
    base_url: str | None = None,
) -> Settings:
    """The readable settings a read of ``ref`` uses: the place given, else the one its link names.

    An explicit ``target`` or ``to`` wins; otherwise a link finds its own annals among the
    configured ones (:func:`annals.config.link_target`). A bare id, or a link on a host this
    machine is not configured for, is looked for in every annals this machine can read, the
    default first (:func:`_settings_holding`): ids are unique across annals.

    Only reads route by link. Commands that change an annals (``share``, ``tag``,
    ``trash``, ``copy``'s destination) take ``--to`` explicitly, so a pasted link never
    redirects a write.
    """
    if target or to:
        return _readable(load_settings(target=target, base_url=base_url, to=to))
    from urllib.parse import urlsplit

    if urlsplit(ref.strip()).scheme in ("http", "https"):
        try:
            return _readable(load_settings(base_url=base_url, to=link_target(ref)))
        except ValueError:
            pass  # a link on a host this machine does not know: look for its id
    return _settings_holding(_parse_ref(ref)[1], base_url=base_url)


def _settings_holding(name: str, *, base_url: str | None = None) -> Settings:
    """The readable annals that holds ``name``: the default first, then each named target.

    Ids are unique across annals, so a bare id (one a conversation copied out of a link,
    say) is found wherever this machine can read it. Outboxes are skipped. Found nowhere:
    a ``ValueError`` naming every place looked in.
    """
    places: list = [None, *named_targets()]
    looked: list[str] = []
    for place in places:
        try:
            settings = _readable(load_settings(base_url=base_url, to=place))
        except (ValueError, RuntimeError):
            continue  # an outbox, or a table that is not a readable place
        if place is None and not settings.configured:
            return settings  # nothing configured: the local default, as always
        looked.append(settings.base_url)
        if _store(settings).holds(name):
            return settings
    if not looked:  # no annals here can be read: say why, as the default does
        return _readable(load_settings(base_url=base_url))
    raise ValueError(
        f"no such document or group: {name} (looked in {', '.join(looked)})"
    )


#: the suffixes whose text :func:`show` reads for the annals links a document makes
LINKS_READ_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".html", ".htm"})
#: :func:`show` reads at most this many of a document's text files for links ...
LINKS_MAX_FILES = 20
#: ... and none larger than this (bytes, from the document's meta)
LINKS_MAX_FILE_BYTES = 1_000_000


def _annals_links(store: DocStore, meta: dict) -> list[str]:
    """The links to annals documents and groups in ``meta``'s text files, on an annals this machine can read.

    Best effort, and cheap: the document's directory is found once, at most
    :data:`LINKS_MAX_FILES` files no larger than :data:`LINKS_MAX_FILE_BYTES` are read, and
    a file that cannot be read is skipped (``show`` still answers). Links whose only place
    here is an outbox are left out, since they cannot be read.
    """
    from annals.share import annals_urls

    sizes = meta.get("sizes") or {}
    rels = [
        rel
        for rel in meta.get("files", [])
        if Path(rel).suffix.lower() in LINKS_READ_SUFFIXES
        and sizes.get(rel, 0) <= LINKS_MAX_FILE_BYTES
    ][:LINKS_MAX_FILES]
    if not rels:
        return []
    try:
        doc_rel = store.doc_rel(meta["id"])
    except Exception:  # noqa: BLE001 -- links are extra; never fail show for them
        return []
    readable: dict = {}

    def can_read(url: str) -> bool:
        try:
            place = link_target(url)
        except ValueError:
            return False  # an annals on a host this machine does not know
        if place not in readable:
            readable[place] = not load_settings(to=place).outbox
        return readable[place]

    found: list[str] = []
    for rel in rels:
        try:
            text = store.target.read_text(f"{doc_rel}/{rel}")
        except Exception:  # noqa: BLE001 -- ssh failures raise RuntimeError; skip the file
            continue
        for url in annals_urls(text):
            if url not in found and can_read(url):
                found.append(url)
    return found


def _readable(settings: Settings) -> Settings:
    """``settings``, refused when its target is an outbox: another machine pulls and empties it."""
    if settings.outbox:
        raise RuntimeError(
            f"{settings.target} is an outbox (another machine pulls it), so the annals "
            "cannot be read from here; read it on a machine whose target is the store"
        )
    return settings


def trash(
    doc_ids: list[str], *, target: str | None = None, to: str | None = None
) -> dict:
    """Move documents to the recycle bin (restorable)."""
    store = _store(load_settings(target=target, to=to))
    return {"trashed": [store.trash(i)["id"] for i in _as_list(doc_ids)]}


def purge(
    doc_ids: list[str], *, target: str | None = None, to: str | None = None
) -> dict:
    """Delete documents that are in the bin for good (not restorable). One that is not in the bin is refused."""
    from annals.catalog import mk_catalog, purge_document

    store = _store(load_settings(target=target, to=to))
    ids = _as_list(doc_ids)
    in_bin = {m["id"] for m in store.list(trash=True)}
    if missing := [
        i for i in ids if i not in in_bin
    ]:  # nothing is deleted unless every id can be
        raise ValueError(
            f"not in the trash, so not purged (nothing was deleted): {', '.join(missing)}; trash it first"
        )
    catalog = mk_catalog(store)
    return {"purged": [purge_document(store, catalog, i)["id"] for i in ids]}


def tag(
    doc_id: str,
    tags: str,
    *,
    target: str | None = None,
    to: str | None = None,
) -> dict:
    """Set a document's tags (comma separated; "" clears them), as the page's tag editor does.

    The tags are the owner's overlay, kept apart from the document and shown by ``ls`` and
    ``show`` in place of the publisher's. They live where the documents do, so this refuses an
    outbox or a remote target. ``doc_id`` may be the document's link. Returns ``{id, tags}``.
    """
    from annals.catalog import mk_catalog
    from annals.sources import PUBLISHED, mk_key
    from annals.target import LocalTarget

    settings = load_settings(target=target, to=to)
    store = _store(settings)
    if settings.outbox or not isinstance(store.target, LocalTarget):
        raise ValueError(
            "the owner's tags are kept where the documents are: this target is not local (or is an outbox)"
        )
    kind, ref = _parse_ref(doc_id)
    if kind == "group":
        raise ValueError("annals tag names a document, not a group")
    store.meta(
        ref
    )  # a document that does not exist raises here, before anything is written
    row = mk_catalog(store).set_tags(
        mk_key(PUBLISHED, ref), [t for t in tags.split(",") if t.strip()]
    )
    return {"id": ref, "tags": row["tags"]}


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
    add_to: str | None = None,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
) -> dict:
    """Make a group (one URL for a set of documents) from existing document ids.

    With ``add_to`` (a group id) the documents are added to that group instead, and ``title``
    is ignored. The documents must exist and not be in the bin; the title is cleaned (see
    :func:`annals.store.clean_title`).
    """
    settings = load_settings(target=target, base_url=base_url, to=to)
    store = _store(settings)
    g = (
        store.add_to_group(add_to, _as_list(doc_ids))
        if add_to
        else store.make_group(title, _as_list(doc_ids))
    )
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
    format: str = "md",
    output: str | None = None,
    demote: int = 1,
    order: str = "numbered",
    no_toc: bool = False,
    keep_wraps: bool = False,
    target: str | None = None,
    to: str | None = None,
) -> str | dict:
    """The files of a group (or one document) as ONE markdown, html or pdf file (nothing is stored).

    ``group_id`` is a group's or a document's id or link. ``format``: ``md`` (printed, or
    written to ``output``), ``html`` (a web page, the same) or ``pdf`` (needs ``output``).
    Markdown, html, text, PDF and image files go in; what cannot (audio, video, other
    files, a damaged PDF) is listed on stderr, with the reason, and left out. The markdown
    has the group's title, a table of contents, then one ``##`` section per file named after
    its path (a folder document's files under its title). ``order``: ``numbered`` puts paths
    that start with a number first, numerically, the rest in the group's order; ``given``
    keeps the group's order. ``demote`` pushes each file's headings that many levels down
    (``0``: as written). Hard-wrapped lines are joined unless ``keep_wraps``; ``no_toc``
    leaves out the table of contents. Redirect to save text, or name the file:
    ``annals aggregate <id> --format pdf --output bundle.pdf``. A PDF or html needs
    ``pip install 'annals[pdf]'``; a missing library says so.
    """
    import functools
    import sys
    import tempfile

    from annals.aggregate import numbered_first
    from annals.combine import FORMATS, Source, combine

    orders = {"numbered": numbered_first, "given": None}
    if order not in orders:
        raise ValueError(f"order must be one of {', '.join(orders)}, not {order!r}")
    if format not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}, not {format!r}")
    if format == "pdf" and not output:
        raise ValueError("a PDF is a binary file: name it with --output FILE")
    store = _store(_read_settings(group_id, target=target, to=to))
    title, metas = _resolve_selection(store, group_id)
    with tempfile.TemporaryDirectory(prefix="annals-aggregate-") as scratch:
        open_path = _file_opener(store, Path(scratch))

        sources = [
            Source(
                meta=m,
                files=list(m.get("files", [])),
                read_text=functools.partial(store.read_text, m["id"]),
                open_path=functools.partial(open_path, m["id"]),
            )
            for m in metas
        ]
        result = combine(
            sources,
            format,
            title=title,
            demote=demote,
            order=orders[order],
            toc=not no_toc,
            unwrap=not keep_wraps,
        )
    for s in result.skipped[:20]:
        print(f"annals: left out {s.label}: {s.reason}", file=sys.stderr)
    if len(result.skipped) > 20:
        print(f"annals: and {len(result.skipped) - 20} more left out", file=sys.stderr)
    if output:
        out = Path(output).expanduser()
        out.write_bytes(result.data)
        return {
            "path": str(out),
            "format": format,
            "sections": result.sections,
            "bytes": len(result.data),
            "skipped": len(result.skipped),
        }
    return result.data.decode("utf-8")


def export(
    doc_id: str,
    *,
    format: str = "pdf",
    file: str | None = None,
    output: str | None = None,
    target: str | None = None,
    to: str | None = None,
) -> str | dict:
    """One markdown file of a document as a ``.md`` or a titled ``.pdf``, as the page's Export gives it.

    ``file`` names another markdown file of a folder document (default: the main one). A PDF
    (images inside; needs the ``annals[pdf]`` extra) is a binary file, so name it with
    ``--output FILE``; ``md`` prints the text or writes it to ``output``. For several documents
    as one file, with a table of contents, use ``annals aggregate``.
    """
    import tempfile

    from annals.config import MAX_INLINE_TEXT_BYTES
    from annals.render import PDF_MAX_TEXT_BYTES, markdown_to_pdf

    FORMATS = ("md", "pdf")  # the server's page of its own (html) is a link, not a file
    if format not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}, not {format!r}")
    if format == "pdf" and not output:
        raise ValueError("a PDF is a binary file: name it with --output FILE")
    settings = _read_settings(doc_id, target=target, to=to)
    store = _store(settings)
    dest = _checked_output(output)
    meta = _document_meta(store, doc_id)
    rel = file or meta["main"]
    if rel not in meta["files"] or kind_of(rel) != "md":
        raise ValueError(f"no markdown file to export: {rel}")
    if (meta.get("sizes") or {}).get(rel, 0) > MAX_INLINE_TEXT_BYTES:
        raise ValueError("this file is too large to export")
    text = store.read_text(meta["id"], rel)
    if format == "md":
        if dest is None:
            return text
        dest.write_text(text, encoding="utf-8")
        return {"output": str(dest), "bytes": len(text.encode("utf-8"))}
    if len(text.encode("utf-8")) > PDF_MAX_TEXT_BYTES:
        raise ValueError("this page is too large to make a PDF of")
    with tempfile.TemporaryDirectory(prefix="annals-export-") as scratch:
        open_path = _file_opener(store, Path(scratch))
        pdf = markdown_to_pdf(
            text,
            title=meta.get("title") or meta["id"],
            rel=rel,
            files=meta["files"],
            open_file=lambda r: open_path(meta["id"], r),
            file_url=lambda r: (
                None
            ),  # a PDF made here links to nothing: the raw route's address is the server's
            created=meta.get("created", ""),
        )
    dest.write_bytes(pdf)
    return {"output": str(dest), "bytes": len(pdf)}


def shareable(doc_id: str, *, target: str | None = None, to: str | None = None) -> dict:
    """What the Share dialog offers for a document: its files, and the other annals documents its text links to.

    ``{main, files: [{rel, kind, size, referenced}], pages: [{id, title, kind}]}``: the
    choices ``annals share`` takes for what a link may show.
    """
    settings = _read_settings(doc_id, target=target, to=to)
    store = _store(settings)
    return _shares(settings).resources(_document_meta(store, doc_id)["id"])


def references(
    ref: str,
    *,
    form: str = "grouped",
    also: list[str] | None = None,
    target: str | None = None,
    to: str | None = None,
) -> str:
    """The references of a document or a group, as its page's References action gives them.

    ``ref`` is a group's or a document's id or link. ``form``: ``grouped`` (each document's
    references section as it is), ``deduped`` (every entry once, numbers removed) or ``urls``
    (one address per line, nothing else: what a notebook takes as pasted sources). Documents
    with no references section are left out; none at all is an error. ``also`` (more document
    ids) takes the references of those documents together, as a pick on the page does.
    """
    from annals import references as refs

    if form not in refs.FORMS:
        raise ValueError(f"form must be one of {', '.join(refs.FORMS)}, not {form!r}")
    store = _store(_read_settings(ref, target=target, to=to))
    title, docs = _resolve_selection(store, ref, also=also)
    found = refs.collect(
        [m for m in docs if not m.get("in_trash")],
        read=store.read_text,
        title=title,
        form=form,
    )
    if not found["text"]:
        raise ValueError(f"no references section in {title!r}")
    return found["text"]


def configure(
    *,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
    outbox: bool = False,
    share_base_url: str | None = None,
    room: bool = False,
) -> dict:
    """Write the publisher config (where to publish, what link to print) and show it.

    Example: ``annals configure --target tw:/root/.local/share/annals --base-url https://apps.example.com/annals``.
    ``--to NAME`` saves the target and base url as a named target (``annals publish --to NAME``)
    and leaves the default alone. ``--outbox`` marks the target as an outbox: a directory
    the server pulls and empties (it cannot be written to from here), so replacements are
    left for the server to apply; it is kept by later changes (``ANNALS_OUTBOX=0`` or an
    edit of the file turns it off). ``--share-base-url`` is where share links point when
    the share server is not at ``<base-url>/shared`` (a platform running it as its own
    public app). ``--room`` marks a target an outside audience reads (a client's room): what
    is published or copied to it carries no provenance; kept by later changes, like
    ``--outbox``. With no arguments, shows the resolved settings without writing.
    """
    writing = bool(target or base_url or outbox or share_base_url or room)
    if to and writing:
        # Resolve a partly-given named target against what is already saved under it.
        try:
            settings = load_settings(
                target=target,
                base_url=base_url,
                to=to,
                outbox=outbox or None,
                share_base_url=share_base_url,
                room=room or None,
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
                # its own share address, never the default section's (or the environment's)
                share_base_url=share_base_url or f"{base_url.rstrip('/')}/shared",
                room=room,
            )
    else:
        current = load_settings(to=to)  # what a partial change applies to
        settings = load_settings(
            target=target or (current.target if writing else None),
            base_url=base_url,
            to=to,
            outbox=(outbox or current.outbox) if writing else None,
            share_base_url=share_base_url,
            room=(room or current.room) if writing else None,
        )
    out = settings.as_dict()
    if writing:
        out["config_path"] = str(write_config(settings, to=to))
    out["local_data_dir"] = str(default_data_dir())
    return out


def _parse_ref(ref: str) -> tuple[str, str]:
    """``("group"|"doc"|"id", id)`` from a link (``.../g/<id>``, ``.../d/<id>``) or a bare id.

    A link's query and fragment are dropped (a file view is ``.../d/<id>?f=<file>``).

    >>> _parse_ref("https://x.com/annals/d/abc?f=a.md#top")
    ('doc', 'abc')
    >>> _parse_ref("abc")
    ('id', 'abc')
    """
    from urllib.parse import urlsplit

    parts = urlsplit(ref.strip()).path.rstrip("/").split("/")
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


def _binned(store: DocStore, doc_id: str) -> bool:
    try:
        return bool(store.meta(doc_id).get("in_trash"))
    except (KeyError, ValueError):
        return True  # missing: nothing to copy


def _copy_doc(
    src: DocStore, dst: DocStore, doc_id: str, *, redact: bool = False
) -> dict:
    import tempfile

    if split_version(doc_id)[1] is not None:
        raise ValueError(
            f"{doc_id} is a version; copy the document (it keeps its versions)"
        )
    meta = src.meta(doc_id)
    if redact and meta.get("in_trash"):
        raise ValueError(
            f"{doc_id} is in the bin; restore it before copying it to a room"
        )
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
        if redact:  # every meta of it, its versions' too, before anything leaves here
            for mp in (Path(td) / "doc").rglob(META):
                m = json.loads(mp.read_text(encoding="utf-8"))
                mp.write_text(json.dumps(without_provenance(m)), encoding="utf-8")
            if dst.target.exists(
                f"docs/{doc_id}"
            ):  # no earlier copy's files left behind
                dst.target.remove_tree(f"docs/{doc_id}")
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
            if dst_settings.room:  # what the owner binned stays out of a room
                g = {**g, "docs": [i for i in g["docs"] if not _binned(src, i)]}
            for doc_id in g["docs"]:
                m = _copy_doc(src, dst, doc_id, redact=dst_settings.room)
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
            m = _copy_doc(src, dst, ident, redact=dst_settings.room)
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
    from annals.share import share_links, share_url

    return {
        "id": rec["token"],
        "title": rec.get("title"),
        "url": share_url(settings.share_base_url, rec["token"]),
        "links": share_links(settings.share_base_url, rec["token"]),
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

    Returns three forms of the one link (the CLI prints the first on stdout, the others
    on stderr): ``url``, the page, whose text is in the html (a
    person, NotebookLM or any fetcher reads it without running script); ``markdown``, the
    whole share as one text, for an agent; ``pdf``, the same with its images. All three end
    with the link's expiry or revocation.

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
        "markdown": out["links"].get("markdown"),
        "pdf": out["links"].get("pdf"),
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
    overviews: str | None = None,
) -> None:
    """Serve the annals page and API (needs ``pip install 'annals[server]'``).

    Auth comes from the environment: ``ANNALS_WHOAMI_URL`` + ``ANNALS_ALLOWED_USERS`` to sit
    behind an existing login, ``ANNALS_BASIC_USER`` + ``ANNALS_BASIC_PASSWORD`` for HTTP Basic,
    nothing for an open server on localhost. A host reachable beyond this machine with no auth
    configured is refused unless ``allow_open`` (``--allow-open``) says something else gates it.
    ``overviews`` (``--overviews '*'``, or reader names separated by commas) offers the Listen
    button to those the login lets in (unset: ``ANNALS_OVERVIEWS`` decides, and unset it is
    off; ``--overviews ''`` forces it off). It spends money, needs ``ANNALS_OVERVIEW_COMMAND``
    and a worker (``annals listen-work`` on a timer), and a server with no login serves it
    only on this machine.
    """
    from annals.api import serve as _serve

    _serve(
        host=host,
        port=port,
        data_dir=data_dir,
        base_path=base_path,
        allow_open=allow_open,
        overviews=overviews,
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


def _overviews_here(*, target, to):
    """The store and the request files, or an error saying this is the wrong machine."""
    from annals.overview import Requests
    from annals.target import LocalTarget

    settings = load_settings(target=target, to=to)
    store = _store(settings)
    if settings.outbox or not isinstance(store.target, LocalTarget):
        raise ValueError(
            "spoken overviews run where the documents are: this target is not local"
        )
    return store, Requests(store.target.root)


def listen(
    doc_id: str,
    *,
    minutes: int = 5,
    force: bool = False,
    also: list[str] | None = None,
    target: str | None = None,
    to: str | None = None,
) -> dict:
    """Ask for a spoken overview of a document, as its page's Listen button does. Spends money.

    ``also`` (more document ids) asks for ONE overview of all of them together, as the page
    does for a pick: their text is put in one document (made when the worker starts the job),
    and the same documents at the same versions reuse it. ``force`` then does not apply.
    """
    from annals import overview
    from annals.config import MAX_AGGREGATE_BYTES

    store, requests = _overviews_here(target=target, to=to)
    if not also:
        return overview.request(store, requests, doc_id, minutes=minutes, force=force)
    if force:
        raise ValueError(
            "--force asks again for one document's overview; it does not apply to --also"
        )
    ids = list(dict.fromkeys(_parse_ref(i)[1] for i in [doc_id, *_as_list(also)]))
    docs = [store.meta(i) for i in ids]
    if binned := [m["id"] for m in docs if m.get("in_trash")]:
        raise ValueError(f"in the bin, so not combined: {', '.join(binned)}")
    if len(docs) == 1:  # the same document twice: the ordinary overview, reused
        return overview.request(store, requests, ids[0], minutes=minutes)
    return overview.request_combined(
        store,
        requests,
        docs,
        title=f"{len(docs)} documents together",
        minutes=minutes,
        max_bytes=MAX_AGGREGATE_BYTES,
    )


def overview_state(
    doc_id: str, *, target: str | None = None, to: str | None = None
) -> dict:
    """Where a document's spoken overview stands (not asked for, queued, made, failed), without asking for one.

    Poll this after ``annals listen``. For a combined overview (``listen --also``) give the
    combined document's id once the worker has made it; until then ``listen`` returns the state.
    """
    from annals import overview

    store, requests = _overviews_here(target=target, to=to)
    return overview.state_of(store, requests, store.meta(_parse_ref(doc_id)[1]))


def listen_work(
    *, command: str = "", target: str | None = None, to: str | None = None
) -> dict:
    """Fulfil the queued overview requests, one at a time (a timer runs this on the server).

    ``command`` makes one overview, with {source}, {minutes}, {out} and {url} filled in; by default,
    ``$ANNALS_OVERVIEW_COMMAND``.
    """
    from annals import overview

    store, requests = _overviews_here(target=target, to=to)
    settings = load_settings(target=target, to=to)
    return {
        "results": overview.work(
            store,
            requests,
            command=command or None,
            doc_url=lambda doc_id: _doc_url(settings, doc_id),
        )
    }


def listen_down(
    reason: str = "",
    *,
    link: str = "",
    clear: bool = False,
    target: str | None = None,
    to: str | None = None,
) -> dict:
    """Say why spoken overviews cannot be made, and where that is being fixed; or clear it.

    With nothing given, shows the current state. The Audio tab then shows the reason and the
    link instead of a Try again that cannot work, e.g.
    ``annals listen-down "the server's login expired" --link <issue url>``. The worker finds
    out by itself too, and clears it on the next success; ``--clear`` clears it now and
    queues every request that waited.
    """
    from annals import overview

    _, requests = _overviews_here(target=target, to=to)
    if clear:
        return {"down": None, "queued": overview.mark_up(requests)}
    if reason or link:
        overview.mark_down(requests, reason, link=link or None)
    return {"down": overview.maker_down(requests)}


_dispatch_funcs[:] = [
    publish,
    ls,
    show,
    trash,
    restore,
    purge,
    tag,
    group,
    groups,
    aggregate,
    export,
    references,
    shareable,
    copy,
    share,
    shares,
    unshare,
    configure,
    serve,
    page_shell,
    listen,
    overview_state,
    listen_work,
    listen_down,
]


#: what a function does to the world, least to most: a surface serves the levels its caller
#: allows. ``read`` changes nothing; ``write`` changes the store or a setting and can be undone
#: or repeated; ``file`` writes a path on the machine that runs it; ``destructive`` cannot be
#: undone; ``spend`` costs money or queues work that does; ``server`` is run by a server or a
#: timer, never by a caller.
EFFECTS = {
    "publish": "write",
    "ls": "read",
    "show": "read",
    "trash": "write",
    "restore": "write",
    "purge": "destructive",
    "tag": "write",
    "group": "write",
    "groups": "read",
    "aggregate": "file",
    "references": "read",
    "export": "file",
    "shareable": "read",
    "copy": "write",
    "share": "write",
    "shares": "read",
    "unshare": "write",
    "configure": "write",
    "serve": "server",
    "page_shell": "server",
    "listen": "spend",
    "overview_state": "read",
    "listen_work": "server",
    "listen_down": "spend",
}
#: what an agent or a tool is offered unless its host asks for more (MCP reads this)
DFLT_EFFECTS = frozenset({"read", "write"})


def tools_with(effects=DFLT_EFFECTS) -> list:
    """The operations whose effect is in ``effects``, in the CLI's order: the list a caller-facing surface serves.

    >>> [f.__name__ for f in tools_with({"read"})]
    ['ls', 'show', 'groups', 'references', 'shareable', 'shares', 'overview_state']
    """
    return [f for f in _dispatch_funcs if EFFECTS[f.__name__] in effects]
