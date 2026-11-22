"""The sessions that made a document: each one's name and the link that opens it.

A document's meta carries them as ``sessions``, a list of ``{"name": ..., "url": ...}``
in the order they first worked on it: the session that published it, then each session
that published a new version (``annals publish --replace``). A group shows the sessions of
its documents. The link is a claude.ai link (``https://claude.ai/code/<bridge session id>``),
which only the owner can open; it is provenance, like ``source`` and ``artifact``, so it is
never part of the document's own content and leaves with the meta: a share or a room shows
an allowlist of meta fields that does not name it.

>>> sessions_of({"source": {"session": "b2", "session_url": "https://claude.ai/code/session_01X"}})
[{'name': 'b2', 'url': 'https://claude.ai/code/session_01X'}]
>>> merged_sessions([{"name": "a", "url": ""}], [{"name": "a", "url": "https://claude.ai/code/s"}, {"name": "b", "url": ""}])
[{'name': 'a', 'url': 'https://claude.ai/code/s'}, {'name': 'b', 'url': ''}]
"""

import os
from collections.abc import Iterable, Mapping

#: the claude.ai link of a session, from its Remote Control (bridge) session id
SESSION_URL_TEMPLATE = "https://claude.ai/code/{bridge_id}"
#: the variable Claude Code sets in a session's shell: its Remote Control session id
BRIDGE_ENV_VAR = "CLAUDE_CODE_BRIDGE_SESSION_ID"


def session_url_from_env(
    env: Mapping[str, str] | None = None,
    *,
    var: str = BRIDGE_ENV_VAR,
    template: str = SESSION_URL_TEMPLATE,
) -> str:
    """The claude.ai link of the Claude Code session this process runs in, or ``""``.

    >>> session_url_from_env({"CLAUDE_CODE_BRIDGE_SESSION_ID": "session_01X"})
    'https://claude.ai/code/session_01X'
    >>> session_url_from_env({})
    ''
    """
    env = os.environ if env is None else env
    bridge = (env.get(var) or "").strip()
    return template.format(bridge_id=bridge) if bridge else ""


def _entry(name, url) -> dict | None:
    name = name.strip() if isinstance(name, str) else ""
    url = url.strip() if isinstance(url, str) else ""
    return {"name": name, "url": url} if name or url else None


def sessions_of(meta: Mapping) -> list[dict]:
    """The sessions that made the document ``meta`` describes (see the module doc).

    A meta written before ``sessions`` existed names its one session in ``source``."""
    listed = meta.get("sessions")
    if isinstance(listed, list):
        found = (_entry(s.get("name"), s.get("url")) for s in listed if isinstance(s, Mapping))
        return merged_sessions(found)
    source = meta.get("source")
    if not isinstance(source, Mapping):
        return []
    one = _entry(source.get("session"), source.get("session_url"))
    return [one] if one else []


def merged_sessions(*lists: Iterable[dict | None]) -> list[dict]:
    """The sessions of ``lists`` in order, one entry each: the same link, or the same name
    when one of the two has no link, is the same session (the link is kept)."""
    out: list[dict] = []
    for items in lists:
        for s in items:
            if not s:
                continue
            same = next(
                (
                    o
                    for o in out
                    if (s["url"] and o["url"] == s["url"])
                    or (s["name"] and o["name"] == s["name"] and not (s["url"] and o["url"]))
                ),
                None,
            )
            if same is None:
                out.append(dict(s))
            else:
                same["url"] = same["url"] or s["url"]
                same["name"] = same["name"] or s["name"]
    return out


def checked_sessions(sessions: Iterable[dict], check_url) -> list[dict]:
    """``sessions`` with each link ``check_url`` refuses (it raises ``ValueError``) emptied:
    a meta written by another publisher is checked again before a page shows its links."""
    out = []
    for s in sessions:
        url = s["url"]
        if url:
            try:
                url = check_url(url)
            except ValueError:
                url = ""
        out.append({"name": s["name"], "url": url})
    return out
