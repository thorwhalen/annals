# PYTHON_ARGCOMPLETE_OK
"""CLI entry point: ``tray publish report.md`` prints a link. Built by ``cw`` over :mod:`intray.tools`."""

from __future__ import annotations

import json
import sys

import cw

from intray.tools import _dispatch_funcs

#: the shape ``publish`` returns for one document; only that shape prints as a bare link
PUBLISH_KEYS = frozenset({"id", "title", "url", "group_id", "group_url"})
#: expected failures: one line on stderr and exit 1, no traceback
EXPECTED_ERRORS = (
    ValueError,
    KeyError,
    FileNotFoundError,
    PermissionError,
    RuntimeError,
)


def _egress(result, *, out=None, err=None) -> int:
    """Print a link when there is one (that is what an agent wants back), else JSON."""
    out = out or sys.stdout
    if result is None:
        return 0
    if isinstance(result, dict) and "url" in result and set(result) <= PUBLISH_KEYS:
        print(result["url"], file=out)
        if "group_url" in result and result["group_url"] != result["url"]:
            print(result["group_url"], file=out)
        return 0
    if isinstance(result, dict) and "docs" in result and "group_url" in result:
        print(result["group_url"], file=out)
        for d in result["docs"]:
            print(f"  {d['url']}  {d['title']}", file=out)
        return 0
    print(json.dumps(result, indent=1, ensure_ascii=False), file=out)
    return 0


def run(argv=None, *, out=None, err=None) -> int:
    """Dispatch ``argv`` (default ``sys.argv[1:]``) and return the exit code."""
    try:
        return cw.dispatch(
            _dispatch_funcs,
            argv,
            prog="tray",
            convention=cw.MODERN,
            egress=_egress,
            out=out,
            err=err,
        )
    except EXPECTED_ERRORS as e:
        print(f"tray: {type(e).__name__}: {e}", file=err or sys.stderr)
        return 1


def main() -> None:
    """Console-script entry point."""
    raise SystemExit(run())


if __name__ == "__main__":
    main()
