"""MCP surface: the same operations as the CLI, from :mod:`annals.tools`, via ``py2mcp``.

Run with ``python -m annals.mcp`` (needs ``pip install 'annals[mcp]'``). String refs keep the
core free of any MCP import; the function list is the one the CLI dispatches.
"""

from __future__ import annotations

_REFS = [
    f"annals.tools:{name}"
    for name in (
        "publish",
        "ls",
        "show",
        "trash",
        "restore",
        "group",
        "groups",
        "configure",
    )
]


def mk_server():
    """Build the MCP server over :mod:`annals.tools`."""
    from py2mcp import mk_mcp_from_refs

    return mk_mcp_from_refs(_REFS, name="annals")


if __name__ == "__main__":
    mk_server().run()
