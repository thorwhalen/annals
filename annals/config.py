"""Settings: where documents are published and what link to print.

Two values matter to a publisher:

* ``target``: where the documents go. A directory (``~/.local/share/annals``) or an ssh
  destination (``tw:/root/.local/share/annals``). This is the data root the annals server
  reads, locally or on another machine.
* ``base_url``: the public root of the annals app, so a publish can print the link the owner
  opens (``https://apps.example.com/annals``).

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
#: extra folders the page lists beside the published documents: "name=path, name2=path2"
ENV_SOURCES = "ANNALS_SOURCES"
ENV_CONFIG = "ANNALS_CONFIG"
ENV_OUTBOX = "ANNALS_OUTBOX"
_TRUE = frozenset({"1", "true", "yes", "on"})
DFLT_SERVE_PORT = 8765
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# A document's content file is read whole into the API's JSON response; this is the cap.
MAX_INLINE_TEXT_BYTES = 2_000_000


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
    return Settings(
        target=resolved_target,
        base_url=resolved_base_url.rstrip("/"),
        configured=configured,
        outbox=outbox,
    )


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
