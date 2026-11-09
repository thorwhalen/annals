# annals.linkcheck

Find what a document mentions without linking to it: the owner reads on a phone and clicks through.

A published report says “Karl asked on 10-29 in #tech-app-test” or “see owner/repo#12”.
Without a link the reader has to go and find the message or the issue, often on a phone.
This module finds such mentions so `annals publish` can warn the author. It only warns
and never blocks: the author decides.

Two kinds, both in markdown or plain text (code spans and fenced blocks are ignored):

- `issue`: a GitHub-style reference, `owner/repo#12` or a bare `#12`, outside a link;
- `message`: a line that points at one message (a message, a thread, a DM, a reply, a
  post, someone who asked, said or wrote, or a `#channel`), carries a date, and has no
  web address at all. A dated pointer to a conversation names one message, so it should be
  its permalink. Headings and date ranges (“2026-10-04 → 2026-11-07”) are periods, not
  messages, and are skipped.

```pycon
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
```

### Module Attributes

| [`URL`](#annals.linkcheck.URL)          | a web address anywhere on a line                                        |
|---------------------------------------------------------------|-------------------------------------------------------------------------|
| [`MD_LINK`](#annals.linkcheck.MD_LINK)      | a markdown link or image `[text](url)`, or an autolink `<url>`          |
| [`CODE_SPAN`](#annals.linkcheck.CODE_SPAN)    | an inline code span                                                     |
| [`ISSUE_REF`](#annals.linkcheck.ISSUE_REF)    | a GitHub-style issue or PR reference, qualified or bare                 |
| [`CONVERSATION`](#annals.linkcheck.CONVERSATION) | words that point at one message, and a #channel (letters, not a number) |
| [`DATE_RANGE`](#annals.linkcheck.DATE_RANGE)   | a period between two dates, which names no single message               |
| [`MAX_LISTED`](#annals.linkcheck.MAX_LISTED)   | how many mentions a warning lists before it says "and N more"           |

### Functions

| [`unlinked_mentions`](#annals.linkcheck.unlinked_mentions)(text)                  | Every issue reference and dated conversation mention in `text` that has no link.           |
|-------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`unlinked_warning`](#annals.linkcheck.unlinked_warning)(text, \*[, max_listed]) | A one-paragraph warning naming the unlinked mentions in `text`, or None if there are none. |

### Classes

| [`Mention`](#annals.linkcheck.Mention)(line, kind, ref)   | One unlinked mention: the 1-based `line`, its `kind` and the `ref` it names.   |
|-----------------------------------------------------------------------------|--------------------------------------------------------------------------------|

### annals.linkcheck.CODE_SPAN *= re.compile('\`[^\`]\*\`')*

an inline code span

### annals.linkcheck.CONVERSATION *= re.compile('\\\\b(?:message|thread|DM|e-?mail|reply|replied|post|posted|asked|said|wrote)\\\\b|(?<![\\\\w&/])#[a-z][\\\\w-]\*[a-z]\\\\b', re.IGNORECASE)*

words that point at one message, and a #channel (letters, not a number)

### annals.linkcheck.DATE_RANGE *= re.compile('\\\\b(?:\\\\d{4}-)?(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\\\\d|3[01])\\\\b\\\\s\*(?:→|->|–|—|to|-)\\\\s\*\\\\b(?:\\\\d{4}-)?(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\\\\d|3[01])\\\\b')*

a period between two dates, which names no single message

### annals.linkcheck.ISSUE_REF *= re.compile('(?<![\\\\w/&#])(?:[A-Za-z0-9][\\\\w.-]\*/[\\\\w.-]+)?#\\\\d+\\\\b')*

a GitHub-style issue or PR reference, qualified or bare

### annals.linkcheck.MAX_LISTED *= 5*

how many mentions a warning lists before it says “and N more”

### annals.linkcheck.MD_LINK *= re.compile('!?\\\\[[^\\\\]]\*\\\\]\\\\([^)]\*\\\\)|<https?://[^>]+>')*

a markdown link or image `[text](url)`, or an autolink `<url>`

### *class* annals.linkcheck.Mention(line, kind, ref)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One unlinked mention: the 1-based `line`, its `kind` and the `ref` it names.

### annals.linkcheck.URL *= re.compile('https?://\\\\S+')*

a web address anywhere on a line

### annals.linkcheck.unlinked_mentions(text)

Every issue reference and dated conversation mention in `text` that has no link.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Mention`](#annals.linkcheck.Mention)]

### annals.linkcheck.unlinked_warning(text, , max_listed=5)

A one-paragraph warning naming the unlinked mentions in `text`, or None if there are none.

```pycon
>>> print(unlinked_warning("Fixed in #4."))
1 mention without a link (the reader clicks through from a phone): line 1 #4. Link each one: an issue or PR to its GitHub URL, a Slack/email/chat message to its permalink.
>>> unlinked_warning("All linked: [#4](https://github.com/o/r/issues/4).") is None
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
