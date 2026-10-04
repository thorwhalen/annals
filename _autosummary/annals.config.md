# annals.config

Settings: where documents are published and what link to print.

Two values matter to a publisher:

* `target`: where the documents go. A directory (`~/.local/share/annals`) or an ssh
  destination (`tw:/root/.local/share/annals`). This is the data root the annals server
  reads, locally or on another machine.
* `base_url`: the public root of the annals app, so a publish can print the link the owner
  opens (`https://apps.example.com/annals`).

Resolution order, highest first: explicit keyword arguments, environment variables
(`ANNALS_TARGET`, `ANNALS_BASE_URL`), the config file (`$ANNALS_CONFIG` or
`$XDG_CONFIG_HOME/annals/config.toml`, default `~/.config/annals/config.toml`), then the
local defaults (publish into the local data dir, link to a local `annals serve`).

The server side has one knob of its own, `ANNALS_DATA_DIR`: the directory the API reads.
It defaults to `~/.local/share/annals`, which is also the default publish target, so with
no configuration at all `annals publish` and `annals serve` meet in the same place.

### Functions

| [`default_config_path`](#annals.config.default_config_path)()                              | `$ANNALS_CONFIG`, else `$XDG_CONFIG_HOME/annals/config.toml`.                     |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`default_data_dir`](#annals.config.default_data_dir)()                                 | The local data root: `$ANNALS_DATA_DIR` or `~/.local/share/annals`.               |
| [`load_settings`](#annals.config.load_settings)(\*[, target, base_url, config_path]) | Resolve settings: arguments, then env, then the config file, then local defaults. |
| [`write_config`](#annals.config.write_config)(settings, \*[, config_path])          | Write the config file (two string keys; no TOML writer dependency needed).        |

### Classes

| [`Settings`](#annals.config.Settings)(target, base_url[, configured])   | Where to publish and what link to print.   |
|---------------------------------------------------------------------------------------------|--------------------------------------------|

### *class* annals.config.Settings(target, base_url, configured=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Where to publish and what link to print. See the module docstring for precedence.

#### as_dict()

Plain dict, for the CLI and MCP surfaces.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### configured *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= True*

publishing then lands
in the local data dir and the link points at a local server, which is rarely meant

* **Type:**
  False when nothing (argument, env, config file) named a target

### annals.config.default_config_path()

`$ANNALS_CONFIG`, else `$XDG_CONFIG_HOME/annals/config.toml`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### annals.config.default_data_dir()

The local data root: `$ANNALS_DATA_DIR` or `~/.local/share/annals`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### annals.config.load_settings(, target=None, base_url=None, config_path=None)

Resolve settings: arguments, then env, then the config file, then local defaults.

* **Return type:**
  [`Settings`](#annals.config.Settings)

### annals.config.write_config(settings, , config_path=None)

Write the config file (two string keys; no TOML writer dependency needed).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
