"""Scrolling, zooming tables for published html pages.

A published html page is served as written; this adds one inlined script (the page's own
``ui/tables.js``) that wraps each data table in a horizontally scrollable, zoomable box,
and lifts a viewport meta that forbids pinch-zoom. Markdown documents get the same script
from the page itself, so both paths share one implementation.
"""

import hashlib
import re
from functools import lru_cache
from pathlib import Path

TABLES_JS = Path(__file__).parent / "data" / "ui" / "tables.js"
#: a ``</body>`` (the last one), where the script goes; else the end of the page
_BODY_END_RE = re.compile(rb"</body\s*>(?![\s\S]*</body\s*>)", re.I)
_VIEWPORT_RE = re.compile(rb"<meta\b[^>]*\bname\s*=\s*[\"']?viewport[\"']?[^>]*>", re.I)
#: viewport settings that stop a reader pinching to zoom
_NO_ZOOM_RE = re.compile(
    rb"[,;\s]*(user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*[0-9.]+|minimum-scale\s*=\s*[0-9.]+)",
    re.I,
)


@lru_cache(maxsize=1)
def _snippet() -> bytes:
    js = TABLES_JS.read_bytes().replace(b"</script", b"<\\/script")
    return b'<script data-watch="1">' + js + b"</script>"


def tables_version() -> str:
    """A short hash of what :func:`add_table_tools` injects, for a page's ETag."""
    return hashlib.sha1(_snippet()).hexdigest()[:8]


def allow_zoom(html: bytes) -> bytes:
    """``html`` with pinch-zoom allowed: no ``user-scalable=no`` or scale limits in its viewport meta."""

    def fix(m: re.Match) -> bytes:
        tag = _NO_ZOOM_RE.sub(b"", m.group(0))
        return re.sub(rb"content\s*=\s*([\"'])\s*,?\s*", rb"content=\1", tag, flags=re.I)

    return _VIEWPORT_RE.sub(fix, html)


def add_table_tools(html: bytes) -> bytes:
    """``html`` with the table script injected, unless it has no table or opts out."""
    head = html.lower()
    if b"<table" not in head or b'data-annals-tables="off"' in head:
        return html
    html = allow_zoom(html)
    m = _BODY_END_RE.search(html)
    at = m.start() if m else len(html)
    return html[:at] + _snippet() + html[at:]
