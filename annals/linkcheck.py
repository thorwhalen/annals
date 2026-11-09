"""Find what a document mentions without linking to it: the owner reads on a phone and clicks through.

A published report says "Karl asked on 10-29 in #tech-app-test" or "see owner/repo#12".
Without a link the reader has to go and find the message or the issue, often on a phone.
This module finds such mentions so ``annals publish`` can warn the author. It only warns
and never blocks: the author decides.

Two kinds, both in markdown or plain text (code spans and fenced blocks are ignored):

- ``issue``: a GitHub-style reference, ``owner/repo#12`` or a bare ``#12``, outside a link;
- ``message``: a line that points at one message (a message, a thread, a DM, a reply, a
  post, someone who asked, said or wrote, or a ``#channel``), carries a date, and has no
  web address at all. A dated pointer to a conversation names one message, so it should be
  its permalink. Headings and date ranges ("2026-10-04 → 2026-11-07") are periods, not
  messages, and are skipped.

>>> doc = '''# Catch-up
... - Karl asked on 2026-10-29 in #tech-app-test what was missing.
... - Karl asked on [2026-10-29](https://x.slack.com/archives/C1/p1) in #tech-app-test.
... - Tracked in inoocq/meta#7 and #12.
... - Tracked in [inoocq/meta#7](https://github.com/inoocq/meta/issues/7).
... - Run `git log #3` here.
... ## Slack, 2026-10-04 → 2026-11-07
... - 574 messages from 2026-10-04 to 2026-11-07, Slack read by hand until 10-04.
... '''
>>> [(m.line, m.kind, m.ref) for m in unlinked_mentions(doc)]
[(2, 'message', 'Slack/chat message of 2026-10-29'), (4, 'issue', 'inoocq/meta#7'), (4, 'issue', '#12')]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

#: a web address anywhere on a line
URL = re.compile(r"https?://\S+")
#: a markdown link or image ``[text](url)``, or an autolink ``<url>``
MD_LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)|<https?://[^>]+>")
#: an inline code span
CODE_SPAN = re.compile(r"`[^`]*`")
#: a GitHub-style issue or PR reference, qualified or bare
ISSUE_REF = re.compile(r"(?<![\w/&#])(?:[A-Za-z0-9][\w.-]*/[\w.-]+)?#\d+\b")
#: words that point at one message, and a #channel (letters, not a number)
CONVERSATION = re.compile(
    r"\b(?:message|thread|DM|e-?mail|reply|replied|post|posted|asked|said|wrote)\b"
    r"|(?<![\w&/])#[a-z][\w-]*[a-z]\b",
    re.IGNORECASE,
)
#: a date: 2026-10-29, or the short 10-29 form reports use within one year
_D = r"\b(?:\d{4}-)?(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b"
DATE = re.compile(_D)
#: a period between two dates, which names no single message
DATE_RANGE = re.compile(_D + r"\s*(?:→|->|–|—|to|-)\s*" + _D)
#: how many mentions a warning lists before it says "and N more"
MAX_LISTED = 5


@dataclass(frozen=True)
class Mention:
    """One unlinked mention: the 1-based ``line``, its ``kind`` and the ``ref`` it names."""

    line: int
    kind: str
    ref: str


def _prose_lines(text: str) -> Iterator[tuple[int, str]]:
    """The lines outside fenced code blocks, with inline code removed, numbered from 1."""
    fenced = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not fenced:
            yield n, CODE_SPAN.sub("", line)


def unlinked_mentions(text: str) -> list[Mention]:
    """Every issue reference and dated conversation mention in ``text`` that has no link."""
    found = []
    for n, line in _prose_lines(text):
        bare = MD_LINK.sub("", line)
        for m in ISSUE_REF.finditer(URL.sub("", bare)):
            found.append(Mention(n, "issue", m.group(0)))
        if line.lstrip().startswith("#") and not ISSUE_REF.match(line.lstrip()):
            continue  # a heading names a period or a subject, not one message
        if not URL.search(line) and CONVERSATION.search(bare):
            date = DATE.search(DATE_RANGE.sub("", bare))
            if date:
                found.append(
                    Mention(n, "message", f"Slack/chat message of {date.group(0)}")
                )
    return found


def unlinked_warning(text: str, *, max_listed: int = MAX_LISTED) -> str | None:
    """A one-paragraph warning naming the unlinked mentions in ``text``, or None if there are none.

    >>> print(unlinked_warning("Fixed in #4."))
    1 mention without a link (the reader clicks through from a phone): line 1 #4. Link each one: an issue or PR to its GitHub URL, a Slack/email/chat message to its permalink.
    >>> unlinked_warning("All linked: [#4](https://github.com/o/r/issues/4).") is None
    True
    """
    found = unlinked_mentions(text)
    if not found:
        return None
    listed = "; ".join(f"line {m.line} {m.ref}" for m in found[:max_listed])
    more = f"; and {len(found) - max_listed} more" if len(found) > max_listed else ""
    s = "" if len(found) == 1 else "s"
    return (
        f"{len(found)} mention{s} without a link (the reader clicks through from a phone): "
        f"{listed}{more}. Link each one: an issue or PR to its GitHub URL, "
        f"a Slack/email/chat message to its permalink."
    )
