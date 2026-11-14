---
name: annals-publish
description: Publish a document or media (a markdown report, an html page, images, video, audio, a PDF, or a whole folder of renders) to the owner's private annals and hand back the link, so they can read it on a phone or tablet away from the terminal. Use whenever the user asks to "publish this", "post it to my annals", "put it where I can read it on my phone", "give me a link to that report", "show me the images", "where can I see the renders", "share the page with me", or whenever you have produced a document longer than a few lines that the user will want to read later or elsewhere. Also covers living pages (one link that stays current: `--replace`), grouping several documents under one link, listing what is in the annals, and moving a document to the recycle bin. Also use whenever you are handed an annals link (`.../annals/d/<id>` or `.../annals/g/<id>`) to read: the page is private, so read it with `annals aggregate <link>`, never by fetching the URL and never by asking for a share link.
---

# annals-publish — one command, one link

The annals is the owner's private in-tray: a page where every document an agent publishes is listed newest first, searchable, with a recycle bin. Publishing is a file copy, so it costs one shell command and returns one line.

## The whole recipe

```bash
annals publish path/to/report.md --session <your session name>
```

It prints the link. Put that link in your reply, on its own line. That is the entire protocol.

Only if `annals` is not found: `pip install annals`. Do not `pip install -U` it where it is already installed: on a development machine that replaces the editable source install with the PyPI wheel. The publisher config, `~/.config/annals/config.toml`, says where documents go; `annals configure` shows it.

- Markdown is rendered on the page with a toggle to the raw source (so the owner can copy it); its relative images resolve. HTML is rendered as-is in a frame (a page without `<!doctype html>` is served with one, so it renders in standards mode). Images, video and PDFs show inline (video streams and seeks). Audio plays in the fleet's player (seek bar, skips, speed, and it remembers where the owner stopped), with its transcript and chapters when you publish them beside it (next section). Anything else is offered as a download.
- The title is taken from the first `# heading` (markdown) or `<title>` (html); pass `--title "..."` to override.
- `--tags a,b` adds tags (searchable). `--session <name>` records who published; always pass your session or corpus name when you have one.

## Reading an annals link you are given

The annals is private: fetching a `.../annals/d/<id>` or `.../annals/g/<id>` link gets a login page. Do not fetch it, and do not ask the owner for a share link (share links are for people outside). On any machine where `annals publish` works, read it through the same channel:

```bash
annals aggregate <link>           # the document's text (a group: every document's), as one markdown on stdout
annals show <link>                # its metadata: files, tags, versions, and the groups it is in
annals aggregate <link> --format pdf --output all.pdf
```

Images, audio and video are not in that text: separate files are named on stderr as left out, and a page's own images stay as `![](fig.png)` references you cannot open. A machine whose target is an outbox (`annals configure` shows `"outbox": true`) cannot read the annals; the commands say so, and so should you.

## Link everything you mention

The owner reads on a phone and clicks through. So every time a document mentions something that has a URL, the mention is a link, including the second and later mentions: a Slack, WhatsApp, email or chat message → its permalink (`https://<workspace>.slack.com/archives/<channel>/p<ts>`); an issue, PR, discussion or commit → its GitHub URL, never a bare `#12` or `owner/repo#12`; a published page → its link. "Karl asked on 10-29 in #tech-app-test" is incomplete until "asked on 10-29" is a link to that message. When you build a report from a message export, keep each message's permalink next to its line from the start, so linking costs nothing at writing time.

`annals publish` checks markdown and text documents and warns on stderr (`N mentions without a link: line 12 …`) about bare issue references and dated mentions of a message with no link. It publishes anyway. When you see the warning, add the links and republish with `--replace <link>`. `--no-link-check` turns the check off, for a document where those references are not meant to be links.

## Living pages: one link that stays current

A guide, a status page or a dashboard you will refresh should keep ONE link. Publish it once, then publish each new version over it:

```bash
annals publish guide.html --session <name>                    # first time: prints the link
annals publish guide.html --replace <link-or-id> --session <name>   # later: same link printed
```

The page shows the newest version, marked "updated", and lists the earlier ones (each readable at `<link>@<n>`). Nothing is lost: the previous files are kept as a version. `--replace` takes one path (a file or a folder, such as a site with its assets); it works for a document inside a group too, and the group keeps it. Remember the link (in your ledger or notes) so the next session replaces rather than republishes.

On a machine whose target is an outbox (`annals configure` shows `"outbox": true`: the server pulls the documents and empties the directory), the replacement is queued and applied when the server pulls it, about a minute later; the printed link is already the right one. Elsewhere it applies at once, and a `--replace` of an id that does not exist is an error.

## Rich pages: link to an interactive Artifact

A static html page is fully rendered here (scripts, CDN libraries, fonts). What annals does not have is what a Claude Artifact has: comments the publishing session can watch, per-viewer and shared state, asking Claude from the page, sharing by link. When a page needs those, publish it to both, Artifact first:

```bash
# 1. publish page.html with the Artifact tool; it returns https://claude.ai/... (the artifact link)
annals publish page.html --artifact <artifact-link> --session <name>
annals publish page.html --replace <link-or-id> --artifact <artifact-link>   # later versions
```

The annals page shows the frame as usual plus an "Open the interactive version" button. annals stays the owner's one in-tray; the interactive features live on the artifact. Only `https://claude.ai/...` links are accepted, and `--artifact` takes one path (the page). A `--replace` that omits `--artifact` keeps the document's current link.

## Audio with its transcript and chapters

Whenever you publish audio and have its timed text (a spoken overview, a podcast, a recording you transcribed), publish the timed text beside it. Name each file after the audio's stem:

```bash
annals publish talk.mp3 talk.vtt talk.chapters.vtt --session <name>    # one document, one link
```

| File | What the page does with it |
|---|---|
| `<stem>.cues.json` | The transcript, with paragraphs, speakers and word timing. Its shape is a list of cues, or `{"cues": [...], "chapters": [...]}`. A cue is `{"start": s, "end": s, "text": "...", "speaker"?: "...", "segment"?: n, "words"?: [[start, end, "word"], ...]}`, in seconds; consecutive cues with the same `segment` form a paragraph. A chapter is `{"start": s, "title": "..."}`. This is `@zodal/speech`'s track shape, so a pipeline that already builds one writes it as is. |
| `<stem>.vtt` (or `<stem>.srt`) | The transcript, one line per cue; a voice tag `<v Name>` names the speaker. Use it when that is what you have; it carries no paragraphs and no word timing. |
| `<stem>.chapters.vtt` | Chapters: a WebVTT file with one cue per chapter, whose text is the title. Chapters inside the cues JSON do the same job. |

The page shows the chapters as a list, and the transcript under the player: a tap on a line or a chapter plays from there, and the current line follows the voice. If several are present, the cues JSON wins over `.vtt`, and `.vtt` wins over `.srt`. The audio and its sidecars become ONE document whether you pass them as files (as above) or as a folder that holds nothing else. Audio published without timed text still gets the player, with no transcript.

## Several documents under one link

```bash
annals publish report.md appendix.md figures.html --group "Q3 review"
```

Prints the group link first, then one line per document. Hand the user the group link.

More for the same set later? Add to it rather than making a second group with the same title: `annals publish more.md --add-to <group-id>` (the id is the last part of the group link). `--group` always makes a NEW group.

## A folder: renders, frames, a page with its assets

```bash
annals publish ./renders --session <name>   # a gallery: thumbnails, players, file list; each file opens with prev/next
annals publish ./site_dir                   # index.html plus its css/js/images, published as one document
annals publish ./report_dir                 # one .md plus its figures: the page, with the figures below
```

A folder is ONE document and one link. Publish the folder of finished outputs (a contact sheet, the renders, the clips), not a working directory of thousands of intermediates: the owner will scroll whatever you send. Hidden files and caches are skipped; `--all-files` keeps them.

## From stdin

```bash
some-command | annals publish - --title "Run log"
```

## Housekeeping (rarely needed)

```bash
annals ls                    # newest first, with links; `annals ls "search words"` filters
annals ls --trash            # the recycle bin
annals trash <id>            # move to the bin (the owner can restore from the page)
annals restore <id>
annals group "Title" <id> <id> ...   # one link for existing documents
annals aggregate <group-or-doc-id> > all.md # a group's files as one .md (title, contents, a section per file)
annals aggregate <id> --format pdf --output all.pdf   # or --format html; md/html/text/pdf/image files go in
annals configure             # show where documents go and what link is printed
```

## A second place to publish (named targets)

The default target is the owner's own annals. A config file can also name other places, each its own table (`annals configure --to inoocq --target <dir-or-host:/path> --base-url https://.../annals` writes one). Opt in per command and nothing else changes:

```bash
annals publish report.md --to inoocq --session <name>   # lands in the "inoocq" annals; prints ITS link
annals ls --to inoocq                                   # list it
annals copy <link-or-id> --to inoocq                    # copy a document or a whole group (ids are kept)
annals copy <link-or-id> --to inoocq --source other     # read from a named target instead of the default
```

Without `--to` documents go to the default target, as always. Use `--to <name>` only when you were told to (for example: material meant for the whole inoocq team goes `--to inoocq`, private notes do not). `copy` reads the documents from a place this machine can read (a directory or `ssh`), so it works where the documents live, not from a machine that only has the link. An unknown name is an error that lists the known ones.

## Sharing one page with someone else

The annals is the owner's alone. Only when the owner asks to share a document with someone (a client, a colleague), make a share link; never on your own initiative, since it makes the document readable by whoever holds the link:

```bash
annals share <id-or-link> --expires 7d                 # every file of the document; prints the public link
annals share <id> --include img/a.png --expires 2026-11-01 --password -   # password from stdin
annals shares                                          # the live links
annals unshare <link>                                  # turn one off
```

Give the owner the link and, if you set one, the password, and say when it expires. Default to an expiry (`7d`) unless told otherwise. On a machine whose target is an outbox (another machine pulls it), `annals share` refuses: point the owner at the Share button on the document's page instead.

## Where it goes

`annals configure` shows the target (a local directory, or `host:/path` over ssh) and the base URL. If the target is remote, publishing needs a working `ssh <host>` with keys (no prompt). If `annals publish` fails with an ssh error, say so and give the user the file path instead; do not retry in a loop.

## What not to do

- Do not paste the document into the chat as well as publishing it: the link is the deliverable.
- Do not publish secrets, credentials, or private data the owner has not seen; the page is private to them, but it is still a copy.
- Do not create one group per document; a group is for a set the user should read together.
- Do not republish a living page as a new document each time; `--replace` it, so the owner's link stays current.
