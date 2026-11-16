"""MCP surface: the same operations as the CLI, from :mod:`annals.tools`, via ``py2mcp``.

Run with ``python -m annals.mcp`` (needs ``pip install 'annals[mcp]'``). String refs keep the
core free of any MCP import; the function list is :data:`annals.tools.TOOLS`, the one the CLI
dispatches minus the server-side ones. ``SIDE_EFFECTS`` names those that write, for a host that
wants only the read verbs.
"""

from __future__ import annotations

def _refs() -> list[str]:
    """String refs to every operation of :data:`annals.tools.TOOLS`: the CLI's list minus what
    only a server runs, so the two cannot drift apart."""
    from annals.tools import TOOLS

    return [f"annals.tools:{f.__name__}" for f in TOOLS]


def mk_server():
    """Build the MCP server over :mod:`annals.tools`."""
    from py2mcp import mk_mcp_from_refs

    return mk_mcp_from_refs(_refs(), name="annals")


if __name__ == "__main__":
    mk_server().run()
