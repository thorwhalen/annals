# annals.config

Settings: where documents are published and what link to print.

Two values matter to a publisher:

* `target`: where the documents go. A directory (`~/.local/share/annals`) or an ssh
  destination (`tw:/root/.local/share/annals`). This is the data root the annals server
  reads, locally or on another machine.
* `base_url`: the public root of the annals app, so a publish can print the link the owner
  opens (`https://apps.example.com/annals`).
* `share_base_url`: where the public share server answers, so `annals share` prints the
  link a recipient opens (`<share_base_url>/<token>/`). It defaults to
  `<base_url>/shared`, which is where `annals serve` mounts it; a platform that runs the
  share server as its own public app sets it (`ANNALS_SHARE_BASE_URL` or the config file).

Resolution order, highest first: explicit keyword arguments, environment variables
(`ANNALS_TARGET`, `ANNALS_BASE_URL`), the config file (`$ANNALS_CONFIG` or
`$XDG_CONFIG_HOME/annals/config.toml`, default `~/.config/annals/config.toml`), then the
local defaults (publish into the local data dir, link to a local `annals serve`).

Named targets (`--to NAME`): a second place to publish, opted into per command. The config
file holds them as `[targets.NAME]` tables with the same two keys; `annals configure --to
NAME --target ... --base-url ...` writes one. `to` picks it over the environment and the
file’s default, and explicit `target`/`base_url` arguments still win over `to`.

A third, `outbox`, is true for a target another machine pulls and empties (the server
fetches documents from it rather than being written to): a replacement published there
travels as it is and is applied where it lands (see [`annals.store`](annals.store.html.md#module-annals.store)). `ANNALS_OUTBOX`
overrides it.

The server side has two knobs of its own. `ANNALS_DATA_DIR` is the directory the API
reads. It defaults to `~/.local/share/annals`, which is also the default publish target,
so with no configuration at all `annals publish` and `annals serve` meet in the same
place. `ANNALS_SOURCES` names extra folders the page lists beside the published documents,
read in place (`ledgers=~/.local/share/crowsnest/ledger`; several, comma-separated).

### Module Attributes

| [`ENV_SHARE_BASE_URL`](#annals.config.ENV_SHARE_BASE_URL)   | where the public share server answers (a share link is `<this>/<token>/`)   |
|-----------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`ENV_SOURCES`](#annals.config.ENV_SOURCES)          | "name=path, name2=path2"                                                    |

### Functions

| [`default_config_path`](#annals.config.default_config_path)()                          | `$ANNALS_CONFIG`, else `$XDG_CONFIG_HOME/annals/config.toml`.                      |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`default_data_dir`](#annals.config.default_data_dir)()                             | The local data root: `$ANNALS_DATA_DIR` or `~/.local/share/annals`.                |
| [`load_settings`](#annals.config.load_settings)(\*[, target, base_url, to, ...]) | Resolve settings: arguments, then `to`, env, the config file, then local defaults. |
| [`named_targets`](#annals.config.named_targets)(\*[, config_path])               | The `[targets.NAME]` tables of the config file: name -> {target, base_url}.        |
| [`write_config`](#annals.config.write_config)(settings, \*[, to, config_path])  | Write the config file (string keys only; no TOML writer dependency needed).        |

### Classes

| [`Settings`](#annals.config.Settings)(target, base_url[, configured, ...])   | Where to publish and what link to print.   |
|--------------------------------------------------------------------------------------------------|--------------------------------------------|

### annals.config.ENV_SHARE_BASE_URL *= 'ANNALS_SHARE_BASE_URL'*

where the public share server answers (a share link is `<this>/<token>/`)

### annals.config.ENV_SOURCES *= 'ANNALS_SOURCES'*

“name=path, name2=path2”

* **Type:**
  extra folders the page lists beside the published documents

### *class* annals.config.Settings(target, base_url, configured=True, outbox=False, share_base_url='')

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

#### outbox *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

the target is pulled and emptied by another machine; replacements apply there

#### share_base_url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= ''*

where share links point (`<this>/<token>/`); `<base_url>/shared` by default

### annals.config.default_config_path()

`$ANNALS_CONFIG`, else `$XDG_CONFIG_HOME/annals/config.toml`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### annals.config.default_data_dir()

The local data root: `$ANNALS_DATA_DIR` or `~/.local/share/annals`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### annals.config.load_settings(, target=None, base_url=None, to=None, outbox=None, share_base_url=None, config_path=None)

Resolve settings: arguments, then `to`, env, the config file, then local defaults.

`to` names a `[targets.NAME]` table of the config file; it replaces the environment
and the file’s default target for this call (explicit arguments still win).

* **Return type:**
  [`Settings`](#annals.config.Settings)

### annals.config.named_targets(, config_path=None)

The `[targets.NAME]` tables of the config file: name -> {target, base_url}.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### annals.config.write_config(settings, , to=None, config_path=None)

Write the config file (string keys only; no TOML writer dependency needed).

With `to`, `settings` is saved as the named target `[targets.<to>]` and the
default section is left as it was; without it the default section is replaced. Either
way the other tables are kept.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
