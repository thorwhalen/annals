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
#: a ``</body>`` (the last one), where the script goes; else the end of the page
_BODY_END_RE = re.compile(rb"</body\s*>(?![\s\S]*</body\s*>)", re.I)
#: words a page that plays media holds somewhere (a tag, or a script building an element)
_MEDIA_HINTS = (b"audio", b"video")
OPT_OUT = b'data-annals-media="off"'


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
    """
    low = html.lower()
    if not any(w in low for w in _MEDIA_HINTS) or OPT_OUT in low:
        return html
    m = _BODY_END_RE.search(html)
    at = m.start() if m else len(html)
    return html[:at] + _snippet() + html[at:]
