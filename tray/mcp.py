"""MCP surface: the same operations as the CLI, from :mod:`tray.tools`, via ``py2mcp``.

Run with ``python -m tray.mcp`` (needs ``pip install 'tray[mcp]'``). String refs keep the
core free of any MCP import; the function list is the one the CLI dispatches.
"""

from __future__ import annotations

_REFS = [f"tray.tools:{name}" for name in ("publish", "ls", "show", "trash", "restore", "group", "groups", "configure")]


def mk_server():
    """Build the MCP server over :mod:`tray.tools`."""
    from py2mcp import mk_mcp_from_refs

    return mk_mcp_from_refs(_REFS, name="tray")


if __name__ == "__main__":
    mk_server().run()
