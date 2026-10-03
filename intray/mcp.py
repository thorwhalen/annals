"""MCP surface: the same operations as the CLI, from :mod:`intray.tools`, via ``py2mcp``.

Run with ``python -m intray.mcp`` (needs ``pip install 'intray[mcp]'``). String refs keep the
core free of any MCP import; the function list is the one the CLI dispatches.
"""

from __future__ import annotations

_REFS = [f"intray.tools:{name}" for name in ("publish", "ls", "show", "trash", "restore", "group", "groups", "configure")]


def mk_server():
    """Build the MCP server over :mod:`intray.tools`."""
    from py2mcp import mk_mcp_from_refs

    return mk_mcp_from_refs(_REFS, name="tray")


if __name__ == "__main__":
    mk_server().run()
