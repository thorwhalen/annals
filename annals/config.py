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

The server side has one knob of its own, ``ANNALS_DATA_DIR``: the directory the API reads.
It defaults to ``~/.local/share/annals``, which is also the default publish target, so with
no configuration at all ``annals publish`` and ``annals serve`` meet in the same place.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, asdict
from pathlib import Path

APP_NAME = "annals"
ENV_TARGET = "ANNALS_TARGET"
ENV_BASE_URL = "ANNALS_BASE_URL"
ENV_DATA_DIR = "ANNALS_DATA_DIR"
ENV_CONFIG = "ANNALS_CONFIG"
DFLT_SERVE_PORT = 8765
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

    def as_dict(self) -> dict:
        """Plain dict, for the CLI and MCP surfaces."""
        return asdict(self)


def _read_config_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    section = data.get(APP_NAME, data)
    return {k: v for k, v in section.items() if isinstance(v, str)}


def load_settings(
    *,
    target: str | None = None,
    base_url: str | None = None,
    config_path: Path | None = None,
) -> Settings:
    """Resolve settings: arguments, then env, then the config file, then local defaults."""
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
    return Settings(target=resolved_target, base_url=resolved_base_url.rstrip("/"), configured=configured)


def write_config(settings: Settings, *, config_path: Path | None = None) -> Path:
    """Write the config file (two string keys; no TOML writer dependency needed)."""
    path = config_path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# {APP_NAME} publisher settings. `annals configure` rewrites this file.\n"
        f"[{APP_NAME}]\n"
        f'target = "{settings.target}"\n'
        f'base_url = "{settings.base_url}"\n'
    )
    path.write_text(body, encoding="utf-8")
    return path
