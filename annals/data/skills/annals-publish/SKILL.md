---
name: annals-publish
description: Publish a document or media (a markdown report, an html page, images, video, audio, a PDF, or a whole folder of renders) to the owner's private annals and hand back the link, so they can read it on a phone or tablet away from the terminal. Use whenever the user asks to "publish this", "post it to my annals", "put it where I can read it on my phone", "give me a link to that report", "show me the images", "where can I see the renders", "share the page with me", or whenever you have produced a document longer than a few lines that the user will want to read later or elsewhere. Also covers living pages (one link that stays current: `--replace`), grouping several documents under one link, listing what is in the annals, and moving a document to the recycle bin.
---

# annals-publish — one command, one link

The annals is the owner's private in-tray: a page where every document an agent publishes is listed newest first, searchable, with a recycle bin. Publishing is a file copy, so it costs one shell command and returns one line.

## The whole recipe

```bash
annals publish path/to/report.md --session <your session name>
```

It prints the link. Put that link in your reply, on its own line. That is the entire protocol.

Only if `annals` is not found: `pip install annals`. Do not `pip install -U` it where it is already installed: on a development machine that replaces the editable source install with the PyPI wheel. The publisher config, `~/.config/annals/config.toml`, says where documents go; `annals configure` shows it.

- Markdown is rendered on the page with a toggle to the raw source (so the owner can copy it); its relative images resolve. HTML is rendered as-is in a frame (a page without `<!doctype html>` is served with one, so it renders in standards mode). Images, video, audio and PDFs show inline (video streams and seeks). Anything else is offered as a download.
- The title is taken from the first `# heading` (markdown) or `<title>` (html); pass `--title "..."` to override.
- `--tags a,b` adds tags (searchable). `--session <name>` records who published; always pass your session or corpus name when you have one.

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
annals aggregate <group-id> > all.md # every markdown file of a group as one .md (title, contents, a section per file)
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
