"""MCP surface: the same operations as the CLI, from :mod:`annals.tools`, via ``py2mcp``.

Run with ``python -m annals.mcp`` (needs ``pip install 'annals[mcp]'``). String refs keep the
core free of any MCP import; the function list is the CLI's (``annals.tools.EFFECTS`` classifies
each operation), narrowed to the effects the host allows: by default read and write, not the
destructive ``purge`` or ``listen``, which spends money.
"""

from __future__ import annotations

import os

from annals.tools import DFLT_EFFECTS, tools_with

#: the environment variable that widens (or narrows) what the server offers
ENV_EFFECTS = "ANNALS_MCP_EFFECTS"


def _refs(effects=DFLT_EFFECTS) -> list[str]:
    """String refs to the operations of :func:`annals.tools.tools_with` ``effects``."""
    return [f"annals.tools:{f.__name__}" for f in tools_with(effects)]


def mk_server(*, effects=None):
    """Build the MCP server over :mod:`annals.tools`.

    ``effects`` (default ``read`` and ``write``, or the comma separated ``ANNALS_MCP_EFFECTS``)
    says which operations to serve; ``destructive`` adds ``purge``, ``spend`` adds ``listen``
    (it costs money), ``file`` adds ``aggregate --output``.
    """
    from py2mcp import mk_mcp_from_refs

    if effects is None and os.environ.get(ENV_EFFECTS):
        effects = {e.strip() for e in os.environ[ENV_EFFECTS].split(",") if e.strip()}
    return mk_mcp_from_refs(_refs(effects or DFLT_EFFECTS), name="annals")


if __name__ == "__main__":
    mk_server().run()
