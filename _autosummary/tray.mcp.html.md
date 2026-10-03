# tray.mcp

MCP surface: the same operations as the CLI, from [`tray.tools`](tray.tools.html.md#module-tray.tools), via `py2mcp`.

Run with `python -m tray.mcp` (needs `pip install 'intray[mcp]'`). String refs keep the
core free of any MCP import; the function list is the one the CLI dispatches.

### Functions

| [`mk_server`](#tray.mcp.mk_server)()   | Build the MCP server over [`tray.tools`](tray.tools.html.md#module-tray.tools).   |
|----------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|

### tray.mcp.mk_server()

Build the MCP server over [`tray.tools`](tray.tools.html.md#module-tray.tools).
