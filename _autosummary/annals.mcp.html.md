# annals.mcp

MCP surface: the same operations as the CLI, from [`annals.tools`](annals.tools.html.md#module-annals.tools), via `py2mcp`.

Run with `python -m annals.mcp` (needs `pip install 'annals[mcp]'`). String refs keep the
core free of any MCP import; the function list is the CLI’s (`annals.tools.EFFECTS` classifies
each operation), narrowed to the effects the host allows: by default read and write, not the
destructive `purge` or `listen`, which spends money.

### Module Attributes

| [`ENV_EFFECTS`](#annals.mcp.ENV_EFFECTS)   | the environment variable that widens (or narrows) what the server offers   |
|----------------------------------------------------------------|----------------------------------------------------------------------------|

### Functions

| [`mk_server`](#annals.mcp.mk_server)(\*[, effects])   | Build the MCP server over [`annals.tools`](annals.tools.html.md#module-annals.tools).   |
|-----------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|

### annals.mcp.ENV_EFFECTS *= 'ANNALS_MCP_EFFECTS'*

the environment variable that widens (or narrows) what the server offers

### annals.mcp.mk_server(, effects=None)

Build the MCP server over [`annals.tools`](annals.tools.html.md#module-annals.tools).

`effects` (default `read` and `write`, or the comma separated `ANNALS_MCP_EFFECTS`)
says which operations to serve; `destructive` adds `purge`, `spend` adds `listen`
(it costs money), `file` adds `aggregate --output`.
