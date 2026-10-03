# intray.mcp

MCP surface: the same operations as the CLI, from [`intray.tools`](intray.tools.md#module-intray.tools), via `py2mcp`.

Run with `python -m intray.mcp` (needs `pip install 'intray[mcp]'`). String refs keep the
core free of any MCP import; the function list is the one the CLI dispatches.

### Functions

| [`mk_server`](#intray.mcp.mk_server)()   | Build the MCP server over [`intray.tools`](intray.tools.md#module-intray.tools).   |
|----------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|

### intray.mcp.mk_server()

Build the MCP server over [`intray.tools`](intray.tools.md#module-intray.tools).
