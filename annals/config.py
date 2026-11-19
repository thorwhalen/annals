"""Settings: where documents are published and what link to print.

Two values matter to a publisher:

* ``target``: where the documents go. A directory (``~/.local/share/annals``) or an ssh
  destination (``tw:/root/.local/share/annals``). This is the data root the annals server
  reads, locally or on another machine.
* ``base_url``: the public root of the annals app, so a publish can print the link the owner
  opens (``https://apps.example.com/annals``).
* ``share_base_url``: where the public share server answers, so ``annals share`` prints the
  link a recipient opens (``<share_base_url>/<token>/``). It defaults to
  ``<base_url>/shared``, which is where ``annals serve`` mounts it; a platform that runs the
  share server as its own public app sets it (``ANNALS_SHARE_BASE_URL`` or the config file).

Resolution order, highest first: explicit keyword arguments, environment variables
(``ANNALS_TARGET``, ``ANNALS_BASE_URL``), the config file (``$ANNALS_CONFIG`` or
``$XDG_CONFIG_HOME/annals/config.toml``, default ``~/.config/annals/config.toml``), then the
local defaults (publish into the local data dir, link to a local ``annals serve``).

Named targets (``--to NAME``): a second place to publish, opted into per command. The config
file holds them as ``[targets.NAME]`` tables with the same two keys; ``annals configure --to
NAME --target ... --base-url ...`` writes one. ``to`` picks it over the environment and the
file's default, and explicit ``target``/``base_url`` arguments still win over ``to``.

A third, ``outbox``, is true for a target another machine pulls and empties (the server
fetches documents from it rather than being written to): a replacement published there
travels as it is and is applied where it lands (see :mod:`annals.store`). ``ANNALS_OUTBOX``
overrides it.

A fourth, ``room``, is true for a target an outside audience reads (a client's room, served
with ``mk_api(room=True)``): ``publish`` and ``copy`` to it write no provenance (the
publisher's host, cwd, session and ``--meta`` keys), so it never reaches that disk.

A link names its own place. :func:`link_target` reads the instance out of a document's or
group's link by matching it against every configured ``base_url`` (the default's and each
named target's), so ``annals aggregate <link>`` reads the right annals without ``--to``. The
config file stays the one list of the annals this machine can read. :func:`link_target`
itself refuses a link to any other host; the read commands then fall back to the default
annals (ids are unique across annals, so that read finds the document or says there is none).

The server side has two knobs of its own. ``ANNALS_DATA_DIR`` is the directory the API
reads. It defaults to ``~/.local/share/annals``, which is also the default publish target,
so with no configuration at all ``annals publish`` and ``annals serve`` meet in the same
place. ``ANNALS_SOURCES`` names extra folders the page lists beside the published documents,
read in place (``ledgers=~/.local/share/crowsnest/ledger``; several, comma-separated).
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, asdict
from pathlib import Path

APP_NAME = "annals"
ENV_TARGET = "ANNALS_TARGET"
ENV_BASE_URL = "ANNALS_BASE_URL"
ENV_DATA_DIR = "ANNALS_DATA_DIR"
#: where the public share server answers (a share link is ``<this>/<token>/``)
ENV_SHARE_BASE_URL = "ANNALS_SHARE_BASE_URL"
#: extra folders the page lists beside the published documents: "name=path, name2=path2"
ENV_SOURCES = "ANNALS_SOURCES"
ENV_CONFIG = "ANNALS_CONFIG"
ENV_OUTBOX = "ANNALS_OUTBOX"
_TRUE = frozenset({"1", "true", "yes", "on"})
DFLT_SERVE_PORT = 8765
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# A document's content file is read whole into the API's JSON response; this is the cap.
MAX_INLINE_TEXT_BYTES = 2_000_000
# All the markdown one combined download (annals.aggregate) may hold.
MAX_AGGREGATE_BYTES = 8_000_000
# All the files (PDFs and images included) one combined download (annals.combine) may read.
MAX_COMBINE_BYTES = 120_000_000
# How many documents' texts the published source keeps for search (least recently used out first).
DFLT_MAX_CACHED_TEXTS = 512


def default_data_dir() -> Path:
    """The local data root: ``$ANNALS_DATA_DIR`` or ``~/.local/share/annals``."""
    env = os.environ.get(ENV_DATA_DIR)
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME


def default_config_path() -> Path:
    """``$ANNALS_CONFIG``, else ``$XDG_CONFIG_HOME/annals/config.toml``."""
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / APP_NAME / "config.toml"


@dataclass(frozen=True)
class Settings:
    """Where to publish and what link to print. See the module docstring for precedence."""

    target: str
    base_url: str
    #: False when nothing (argument, env, config file) named a target: publishing then lands
    #: in the local data dir and the link points at a local server, which is rarely meant
    configured: bool = True
    #: the target is pulled and emptied by another machine; replacements apply there
    outbox: bool = False
    #: where share links point (``<this>/<token>/``); ``<base_url>/shared`` by default
    share_base_url: str = ""
    #: an outside audience reads this target: what is written to it carries no provenance
    room: bool = False

    def __post_init__(self):
        if not self.share_base_url:
            object.__setattr__(self, "share_base_url", f"{self.base_url}/shared")

    def as_dict(self) -> dict:
        """Plain dict, for the CLI and MCP surfaces."""
        return asdict(self)


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _read_config_file(path: Path) -> dict:
    section = _read_toml(path)
    section = section.get(APP_NAME, section)
    return {k: v for k, v in section.items() if isinstance(v, (str, bool))}


def named_targets(*, config_path: Path | None = None) -> dict[str, dict[str, str]]:
    """The ``[targets.NAME]`` tables of the config file: name -> {target, base_url}."""
    tables = _read_toml(config_path or default_config_path()).get("targets", {})
    return {
        name: {k: v for k, v in table.items() if isinstance(v, (str, bool))}
        for name, table in tables.items()
        if isinstance(table, dict)
    }


def load_settings(
    *,
    target: str | None = None,
    base_url: str | None = None,
    to: str | None = None,
    outbox: bool | None = None,
    share_base_url: str | None = None,
    room: bool | None = None,
    config_path: Path | None = None,
) -> Settings:
    """Resolve settings: arguments, then ``to``, env, the config file, then local defaults.

    ``to`` names a ``[targets.NAME]`` table of the config file; it replaces the environment
    and the file's default target for this call (explicit arguments still win).
    """
    if to is not None:
        if not _NAME_RE.match(to):
            raise ValueError(f"not a valid annals target name: {to!r}")
        known = named_targets(config_path=config_path)
        if to not in known or not known[to].get("target"):
            raise ValueError(
                f"unknown annals target {to!r}; known: {sorted(known) or 'none'}. "
                f"Add one with `annals configure --to {to} --target ... --base-url ...`."
            )
        named = known[to]
        target = target or named["target"]
        outbox = outbox if outbox is not None else bool(named.get("outbox", False))
        share_base_url = share_base_url or named.get("share_base_url")
        room = room if room is not None else bool(named.get("room", False))
        # Never fall through to the default's base url: links would name the wrong place.
        base_url = base_url or named.get("base_url")
        if not base_url:
            raise ValueError(
                f"annals target {to!r} has no base_url; set it with `annals configure --to {to} --base-url ...`"
            )
    file_values = _read_config_file(config_path or default_config_path())
    resolved_target = (
        target
        or os.environ.get(ENV_TARGET)
        or file_values.get("target")
        or str(default_data_dir())
    )
    resolved_base_url = (
        base_url
        or os.environ.get(ENV_BASE_URL)
        or file_values.get("base_url")
        or f"http://127.0.0.1:{DFLT_SERVE_PORT}/{APP_NAME}"
    )
    configured = bool(target or os.environ.get(ENV_TARGET) or file_values.get("target"))
    if outbox is None:
        env = os.environ.get(ENV_OUTBOX)
        outbox = (
            env.strip().lower() in _TRUE
            if env is not None
            else bool(file_values.get("outbox", False))
            and not (target or os.environ.get(ENV_TARGET))
        )
    if room is None:
        room = bool(file_values.get("room", False)) and not (
            target or os.environ.get(ENV_TARGET)
        )
    resolved_share = (
        share_base_url
        or (None if to else os.environ.get(ENV_SHARE_BASE_URL))
        or (None if to else file_values.get("share_base_url"))
        or ""
    )
    return Settings(
        target=resolved_target,
        base_url=resolved_base_url.rstrip("/"),
        configured=configured,
        outbox=outbox,
        share_base_url=str(resolved_share).rstrip("/"),
        room=room,
    )


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _url_key(url: str) -> tuple[str, str]:
    """``(host, path)`` of an http(s) url as a browser would reach it, for prefix tests.

    The host loses any userinfo, a trailing dot and its scheme's default port, and is
    lower-cased; the path is normalised (``..`` and ``.`` segments resolved, no trailing slash).

    >>> _url_key("https://u@Apps.Example.com.:443/annals/x/../d/1/")
    ('apps.example.com', '/annals/d/1')
    >>> _url_key("https://a.example.com:8443/annals")
    ('a.example.com:8443', '/annals')
    """
    import posixpath
    from urllib.parse import urlsplit

    u = urlsplit(url.strip())
    host = (u.hostname or "").rstrip(".")
    try:
        port = u.port
    except ValueError:
        port = None  # a malformed port names no configured place
    if port and port != _DEFAULT_PORTS.get(u.scheme):
        host = f"{host}:{port}"
    path = posixpath.normpath(u.path) if u.path else ""
    return host, "" if path in (".", "/") else path.rstrip("/")


def link_target(ref: str, *, config_path: Path | None = None) -> str | None:
    """The configured place a document's or group's link lives in: ``None`` (the default) or a target's name.

    ``ref`` that is not an http(s) link (a bare id) names no place, so the answer is
    ``None``: read the default. A link is matched against the default ``base_url`` and
    every ``[targets.NAME]`` one; the longest matching ``base_url`` wins, and among equals
    a readable target beats an outbox (an outbox is written to, never read). Hosts and
    paths are compared as a browser reaches them (:func:`_url_key`). A link that matches
    none raises ``ValueError`` naming the places this machine knows.

    >>> import tempfile, pathlib
    >>> cfg = pathlib.Path(tempfile.mkdtemp()) / "config.toml"
    >>> _ = cfg.write_text('''[annals]
    ... target = "/srv/annals"
    ... base_url = "https://apps.example.com/annals"
    ... [targets.team]
    ... target = "team:/var/lib/annals"
    ... base_url = "https://annals.team.example.org/annals"
    ... ''')
    >>> link_target("https://annals.team.example.org/annals/d/20261119-075018-a-4a58", config_path=cfg)
    'team'
    >>> link_target("https://APPS.example.com/annals/g/20261119-075018-b?f=x", config_path=cfg) is None
    True
    >>> link_target("20261119-075018-a-4a58", config_path=cfg) is None
    True
    """
    from urllib.parse import urlsplit

    if urlsplit(ref.strip()).scheme not in ("http", "https"):
        return None
    host, path = _url_key(ref)
    default = load_settings(config_path=config_path)
    places: list[tuple[str | None, str, bool]] = [
        (None, default.base_url, default.outbox)
    ]
    for name, table in named_targets(config_path=config_path).items():
        if table.get("target") and isinstance(table.get("base_url"), str):
            places.append((name, table["base_url"], bool(table.get("outbox", False))))

    def matches(base: str) -> bool:
        b_host, b_path = _url_key(base)
        return b_host == host and (path == b_path or path.startswith(b_path + "/"))

    found = [(name, base, outbox) for name, base, outbox in places if matches(base)]
    if not found:
        known = ", ".join(dict.fromkeys(base for _, base, _ in places))
        raise ValueError(
            f"{ref} is not on an annals this machine knows ({known}). "
            "Add its place with `annals configure --to NAME --target ... --base-url ...`."
        )
    found.sort(key=lambda f: (-len(_url_key(f[1])[1]), f[2]))
    return found[0][0]


def write_config(
    settings: Settings,
    *,
    to: str | None = None,
    config_path: Path | None = None,
) -> Path:
    """Write the config file (string keys only; no TOML writer dependency needed).

    With ``to``, ``settings`` is saved as the named target ``[targets.<to>]`` and the
    default section is left as it was; without it the default section is replaced. Either
    way the other tables are kept.
    """
    path = config_path or default_config_path()
    if to is not None and not _NAME_RE.match(to):
        raise ValueError(f"not a valid annals target name: {to!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    default = _read_config_file(path)
    targets = named_targets(config_path=path)
    values: dict = {"target": settings.target, "base_url": settings.base_url}
    if settings.outbox:
        values["outbox"] = True
    if settings.room:
        values["room"] = True
    if settings.share_base_url != f"{settings.base_url}/shared":
        values["share_base_url"] = settings.share_base_url  # only when not the default
    if to:
        targets[to] = values
    else:
        default = values
    body = f"# {APP_NAME} publisher settings. `annals configure` rewrites this file.\n"
    if default:
        body += f"[{APP_NAME}]\n" + "".join(
            f"{k} = {json.dumps(v)}\n" for k, v in default.items()
        )
    for name, table in targets.items():
        body += f"\n[targets.{name}]\n" + "".join(
            f"{k} = {json.dumps(v)}\n" for k, v in table.items()
        )
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)
    return path
