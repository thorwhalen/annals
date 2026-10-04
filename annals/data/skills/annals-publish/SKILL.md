---
name: annals-publish
description: Publish a document or media (a markdown report, an html page, images, video, audio, a PDF, or a whole folder of renders) to the owner's private annals and hand back the link, so they can read it on a phone or tablet away from the terminal. Use whenever the user asks to "publish this", "post it to my annals", "put it where I can read it on my phone", "give me a link to that report", "show me the images", "where can I see the renders", "share the page with me", or whenever you have produced a document longer than a few lines that the user will want to read later or elsewhere. Also covers grouping several documents under one link, listing what is in the annals, and moving a document to the recycle bin.
---

# annals-publish — one command, one link

The annals is the owner's private in-tray: a page where every document an agent publishes is listed newest first, searchable, with a recycle bin. Publishing is a file copy, so it costs one shell command and returns one line.

## The whole recipe

```bash
annals publish path/to/report.md --session <your session name>
```

It prints the link. Put that link in your reply, on its own line. That is the entire protocol.

First time on a machine: `pip install -U annals` (the publisher config, `~/.config/annals/config.toml`, says where documents go; `annals configure` shows it).

- Markdown is rendered on the page with a toggle to the raw source (so the owner can copy it); its relative images resolve. HTML is rendered as-is in a frame. Images, video, audio and PDFs show inline (video streams and seeks). Anything else is offered as a download.
- The title is taken from the first `# heading` (markdown) or `<title>` (html); pass `--title "..."` to override.
- `--tags a,b` adds tags (searchable). `--session <name>` records who published; always pass your session or corpus name when you have one.

## Several documents under one link

```bash
annals publish report.md appendix.md figures.html --group "Q3 review"
```

Prints the group link first, then one line per document. Hand the user the group link.

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
annals configure             # show where documents go and what link is printed
```

## Where it goes

`annals configure` shows the target (a local directory, or `host:/path` over ssh) and the base URL. If the target is remote, publishing needs a working `ssh <host>` with keys (no prompt). If `annals publish` fails with an ssh error, say so and give the user the file path instead; do not retry in a loop.

## What not to do

- Do not paste the document into the chat as well as publishing it: the link is the deliverable.
- Do not publish secrets, credentials, or private data the owner has not seen; the page is private to them, but it is still a copy.
- Do not create one group per document; a group is for a set the user should read together.
