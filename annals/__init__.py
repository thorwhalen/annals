"""annals: an in-tray for AI agents. Publish documents and media to a private page; get a link.

Agents call :func:`annals.tools.publish` (or ``annals publish file.md`` from a shell) and hand
the printed URL to their human, who opens it on a phone. The documents are plain files in a
directory, local or on another machine over ssh; :func:`annals.api.mk_app` serves that
directory as a private page with search, sort, groups and a recycle bin.
"""

from annals.config import Settings, load_settings
from annals.store import DocStore
from annals.target import LocalTarget, SshTarget, parse_target
from annals.tools import configure, group, groups, ls, publish, restore, show, trash

__all__ = [
    "DocStore",
    "LocalTarget",
    "Settings",
    "SshTarget",
    "configure",
    "group",
    "groups",
    "load_settings",
    "ls",
    "parse_target",
    "publish",
    "restore",
    "show",
    "trash",
]
