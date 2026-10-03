---
name: tray-publish
description: Publish a markdown or html document (a report, an analysis, a rendered artifact, a page) to the owner's private tray and hand back the link, so they can read it on a phone or tablet away from the terminal. Use whenever the user asks to "publish this", "post it to my tray", "put it where I can read it on my phone", "give me a link to that report", "share the page with me", or whenever you have produced a document longer than a few lines that the user will want to read later or elsewhere. Also covers grouping several documents under one link, listing what is in the tray, and moving a document to the recycle bin.
---

# tray-publish — one command, one link

The tray is the owner's private in-tray: a page where every document an agent publishes is listed newest first, searchable, with a recycle bin. Publishing is a file copy, so it costs one shell command and returns one line.

## The whole recipe

```bash
tray publish path/to/report.md --session <your session name>
```

It prints the link. Put that link in your reply, on its own line. That is the entire protocol.

- Markdown is rendered on the page with a toggle to the raw source (so the owner can copy it). HTML is rendered as-is in a frame. Other files are offered as downloads.
- The title is taken from the first `# heading` (markdown) or `<title>` (html); pass `--title "..."` to override.
- `--tags a,b` adds tags (searchable). `--session <name>` records who published; always pass your session or corpus name when you have one.

## Several documents under one link

```bash
tray publish report.md appendix.md figures.html --group "Q3 review"
```

Prints the group link first, then one line per document. Hand the user the group link.

## An html artifact with assets (a directory)

```bash
tray publish ./site_dir            # index.html plus its css/js/images, published as one document
```

## From stdin

```bash
some-command | tray publish - --title "Run log"
```

## Housekeeping (rarely needed)

```bash
tray ls                    # newest first, with links; `tray ls "search words"` filters
tray ls --trash            # the recycle bin
tray trash <id>            # move to the bin (the owner can restore from the page)
tray restore <id>
tray group "Title" <id> <id> ...   # one link for existing documents
tray configure             # show where documents go and what link is printed
```

## Where it goes

`tray configure` shows the target (a local directory, or `host:/path` over ssh) and the base URL. If the target is remote, publishing needs a working `ssh <host>` with keys (no prompt). If `tray publish` fails with an ssh error, say so and give the user the file path instead; do not retry in a loop.

## What not to do

- Do not paste the document into the chat as well as publishing it: the link is the deliverable.
- Do not publish secrets, credentials, or private data the owner has not seen; the page is private to them, but it is still a copy.
- Do not create one group per document; a group is for a set the user should read together.
