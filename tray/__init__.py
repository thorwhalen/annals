"""tray: an in-tray for AI agents. Publish markdown and html to a private page; get a link.

Agents call :func:`tray.tools.publish` (or ``tray publish file.md`` from a shell) and hand
the printed URL to their human, who opens it on a phone. The documents are plain files in a
directory, local or on another machine over ssh; :func:`tray.api.mk_app` serves that
directory as a private page with search, sort, groups and a recycle bin.
"""

from tray.config import Settings, load_settings
from tray.store import DocStore
from tray.target import LocalTarget, SshTarget, parse_target
from tray.tools import configure, group, groups, ls, publish, restore, show, trash

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
