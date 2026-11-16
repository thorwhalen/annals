# PYTHON_ARGCOMPLETE_OK
"""CLI entry point: ``annals publish report.md`` prints a link. Built by ``cw`` over :mod:`annals.tools`."""

from __future__ import annotations

import json
import sys

import cw

from annals.tools import _dispatch_funcs

#: the shape ``publish`` (or ``share``) returns for one link; only that shape prints bare
PUBLISH_KEYS = frozenset(
    {"id", "title", "url", "group_id", "group_url", "warning", "note", "markdown", "pdf"}
)
#: a share's other forms, said on stderr beside the bare link: (key, what it is for)
LINK_FORMS = (
    ("markdown", "as Markdown, for an agent"),
    ("pdf", "as PDF, images inside"),
)
#: expected failures: one line on stderr and exit 1, no traceback
EXPECTED_ERRORS = (
    ValueError,
    KeyError,
    FileNotFoundError,
    PermissionError,
    RuntimeError,
)


#: the flag that turns any command's result into JSON on stdout, whatever its shape
JSON_FLAG = "--json"


def _decode(param, hint):
    """cw's usual decoding, except ``--meta`` repeats (``--meta a=1 --meta b=2``) instead of
    taking the values after one flag, so a path may follow it and no earlier one is lost."""
    if param.name == "meta":
        return {"action": "extend", "nargs": 1}
    return cw.convention.argh_decode(param, hint)


def _egress(result, *, out=None, err=None, as_json: bool = False) -> int:
    """Print a link when there is one (that is what an agent wants back), else JSON.

    ``as_json`` prints the result dict as JSON and nothing else on stdout, for a program
    that calls the CLI. Warnings and notes stay on stderr either way.
    """
    out = out or sys.stdout
    if result is None:
        return 0
    if isinstance(result, dict) and result.get("warning"):
        print(f"annals: warning: {result.pop('warning')}", file=err or sys.stderr)
    if isinstance(result, dict) and result.get("note"):
        print(f"annals: {result.pop('note')}", file=err or sys.stderr)
    if as_json and not isinstance(result, str):
        print(json.dumps(result, indent=1, ensure_ascii=False), file=out)
        return 0
    if isinstance(result, str):
        print(result, file=out, end="" if result.endswith("\n") else "\n")
        return 0
    if isinstance(result, dict) and "url" in result and set(result) <= PUBLISH_KEYS:
        print(result["url"], file=out)
        for key, what in LINK_FORMS:
            if result.get(key):
                print(f"annals: {what}: {result[key]}", file=err or sys.stderr)
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
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = JSON_FLAG in argv
    argv = [a for a in argv if a != JSON_FLAG]
    try:
        return cw.dispatch(
            _dispatch_funcs,
            argv,
            prog="annals",
            convention=cw.MODERN,
            decode=_decode,
            egress=lambda result, **kw: _egress(result, as_json=as_json, **kw),
            out=out,
            err=err,
        )
    except EXPECTED_ERRORS as e:
        print(f"annals: {type(e).__name__}: {e}", file=err or sys.stderr)
        return 1


def main() -> None:
    """Console-script entry point."""
    raise SystemExit(run())


if __name__ == "__main__":
    main()
