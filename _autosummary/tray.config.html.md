# tray.config

Settings: where documents are published and what link to print.

Two values matter to a publisher:

* `target`: where the documents go. A directory (`~/.local/share/tray`) or an ssh
  destination (`tw:/root/.local/share/tray`). This is the data root the tray server
  reads, locally or on another machine.
* `base_url`: the public root of the tray app, so a publish can print the link the owner
  opens (`https://apps.example.com/tray`).

Resolution order, highest first: explicit keyword arguments, environment variables
(`TRAY_TARGET`, `TRAY_BASE_URL`), the config file (`$TRAY_CONFIG` or
`$XDG_CONFIG_HOME/tray/config.toml`, default `~/.config/tray/config.toml`), then the
local defaults (publish into the local data dir, link to a local `tray serve`).

The server side has one knob of its own, `TRAY_DATA_DIR`: the directory the API reads.
It defaults to `~/.local/share/tray`, which is also the default publish target, so with
no configuration at all `tray publish` and `tray serve` meet in the same place.

### Functions

| [`default_config_path`](#tray.config.default_config_path)()                              | `$TRAY_CONFIG`, else `$XDG_CONFIG_HOME/tray/config.toml`.                         |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`default_data_dir`](#tray.config.default_data_dir)()                                 | The local data root: `$TRAY_DATA_DIR` or `~/.local/share/tray`.                   |
| [`load_settings`](#tray.config.load_settings)(\*[, target, base_url, config_path]) | Resolve settings: arguments, then env, then the config file, then local defaults. |
| [`write_config`](#tray.config.write_config)(settings, \*[, config_path])          | Write the config file (two string keys; no TOML writer dependency needed).        |

### Classes

| [`Settings`](#tray.config.Settings)(target, base_url)   | Where to publish and what link to print.   |
|-------------------------------------------------------------------------------|--------------------------------------------|

### *class* tray.config.Settings(target, base_url)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Where to publish and what link to print. See the module docstring for precedence.

#### as_dict()

Plain dict, for the CLI and MCP surfaces.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### tray.config.default_config_path()

`$TRAY_CONFIG`, else `$XDG_CONFIG_HOME/tray/config.toml`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### tray.config.default_data_dir()

The local data root: `$TRAY_DATA_DIR` or `~/.local/share/tray`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### tray.config.load_settings(, target=None, base_url=None, config_path=None)

Resolve settings: arguments, then env, then the config file, then local defaults.

* **Return type:**
  [`Settings`](#tray.config.Settings)

### tray.config.write_config(settings, , config_path=None)

Write the config file (two string keys; no TOML writer dependency needed).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
