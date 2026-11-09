"""The media relay for published html pages: what a framed page plays, told to the page around it.

A spoken overview is an html page shown in a sandboxed frame, so the annals page cannot see
its audio. This adds one inlined script (the page's own ``ui/media-progress.js``) to any
html page that may play audio or video; the script posts what is played to the parent
page, which records what the reader heard (:mod:`annals.listening`), and takes a "start at"
from it. Opened on its own (no parent), the script does nothing.
"""

import hashlib
import re
from functools import lru_cache
from pathlib import Path

MEDIA_JS = Path(__file__).parent / "data" / "ui" / "media-progress.js"
#: what a page that plays media holds: a tag, a script building one ("audio" as a tag name
#: handed to createElement or a helper), or an ``Audio()``; matched on the lowercased page
_MEDIA_HINT_RE = re.compile(rb"<(?:audio|video)\b|[\"'`](?:audio|video)[\"'`]|\baudio\s*\(")
#: the opt-out, as an attribute of the page's ``<html>`` or ``<body>``
_OPT_OUT_RE = re.compile(rb"<(?:html|body)\b[^>]*\bdata-annals-media\s*=\s*[\"']?off\b")


@lru_cache(maxsize=1)
def _snippet() -> bytes:
    js = MEDIA_JS.read_bytes().replace(b"</script", b"<\\/script")
    return b'<script data-annals-media="1">' + js + b"</script>"


def media_version() -> str:
    """A short hash of what :func:`add_media_relay` injects, for a page's ETag."""
    return hashlib.sha1(_snippet()).hexdigest()[:8]


def add_media_relay(html: bytes) -> bytes:
    """``html`` with the media relay injected, unless it plays nothing or opts out.

    >>> add_media_relay(b"<p>no media</p>") == b"<p>no media</p>"
    True
    >>> b"annalsMedia" in add_media_relay(b"<body><audio src=a.mp3></audio></body>")
    True
    >>> add_media_relay(b"<p>an audio overview</p>") == b"<p>an audio overview</p>"
    True
    """
    low = html.lower()
    if not _MEDIA_HINT_RE.search(low) or _OPT_OUT_RE.search(low):
        return html
    at = low.rfind(b"</body")
    at = at if at >= 0 else len(html)
    return html[:at] + _snippet() + html[at:]
