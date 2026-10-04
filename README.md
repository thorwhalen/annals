# annals

Annals for AI agents. An agent publishes a document (markdown, html, an image, a video, a PDF, or a whole folder of renders) with one command and gets back a link; the owner opens their annals on a phone and finds everything their agents left for them, newest first, searchable, with a recycle bin.

```bash
pip install annals
annals publish report.md --session my-agent
# https://apps.example.com/annals/d/20261003-203301-quarterly-report-3f9a
```

Documents are plain files in a directory. The directory can be on this machine or on another one over ssh, and the page that serves it reads it directly, so publishing never redeploys anything. No database, no build step, no API token.

## For agents

Load the shipped skill, `annals-publish`, and you have the whole protocol: one command, one link, put the link in your reply.

```bash
annals publish report.md                          # one document, prints its link
annals publish a.md b.md c.html --group "Review"  # one link for a set (the group link prints first)
annals publish d.md --add-to <group-id>           # add to that set later (same link)
annals publish ./renders                          # a folder: a gallery with inline images, video, audio
annals publish ./site_dir                         # an html page with its assets, as one document
annals publish clip.mp4                           # media plays inline (streamed, seekable)
some-command | annals publish - --title "Log"     # from stdin
annals ls "search words"                          # what is there, newest first
annals trash <id>  /  annals restore <id>         # the recycle bin
```

What each kind looks like on the page:

| Published | Shown as |
|---|---|
| a `.md` file | rendered markdown, with a toggle to the source and a copy button; its relative images and links resolve to its own files |
| an `.html` file, or a folder with `index.html` | the page itself, in a sandboxed frame |
| an image, video, audio file or PDF | inline: image, player (byte-range streaming, so video seeks), PDF viewer |
| a folder with one page in it | that page, with the other files below it |
| any other folder | a gallery: image thumbnails (a page at a time), players, a file list; every file opens on its own with prev/next |
| anything else | a download |

A folder skips hidden files and caches (`.*`, `__pycache__`, `*.pyc`); `--all-files` keeps them.

With `pip install 'annals[mcp]'`, the same operations are an MCP server: `python -m annals.mcp`.

## Where documents go

```bash
annals configure --target tw:/root/.local/share/annals --base-url https://apps.example.com/annals
```

That writes `~/.config/annals/config.toml`. `target` is a directory, or `host:/path` for a directory on another machine reached by `ssh host` (keys, no prompt; `host` can be an alias from `~/.ssh/config`). `ANNALS_TARGET` and `ANNALS_BASE_URL` override it per shell. With no configuration, documents go to `~/.local/share/annals` and the link points at a local `annals serve`.

## Hosting the page

**Inside an app platform** (the usual case). Mount the API under the platform's prefix and let the platform's login gate it:

```python
# server.py of the host app; the platform serves frontend/ at /annals/ and this at /api/annals
from annals.api import mk_api
app = mk_api(data_dir="/root/.local/share/annals")
```

and write the page shell once as the app's frontend:

```bash
annals page-shell --api /api/annals --base /annals > frontend/index.html
```

The shell only names those two paths; the page's script and style load from the API, so upgrading the package upgrades the page. Gallery thumbnails are made with Pillow when it is installed (cached under the data root's `cache/`), and fall back to the original image when it is not.

**Standalone**, for a machine with no platform:

```bash
pip install 'annals[server]'
ANNALS_DATA_DIR=~/.local/share/annals annals serve --host 127.0.0.1 --port 8765
```

The page is at `http://127.0.0.1:8765/annals/`, its API under `/annals/api/`. Auth is chosen by environment variables:

| Situation | Set | Effect |
|---|---|---|
| Behind an existing login that exposes a who-am-I endpoint | `ANNALS_WHOAMI_URL`, `ANNALS_ALLOWED_USERS=me@example.com`, optionally `ANNALS_LOGIN_URL=/auth/login` | the browser's cookies are forwarded to that endpoint and the listed emails are allowed; anyone else is sent to the login page |
| No platform login | `ANNALS_BASIC_USER`, `ANNALS_BASIC_PASSWORD` | HTTP Basic |
| Localhost only | nothing | open |

## Python API

```python
from annals import DocStore, publish
meta = DocStore("~/.local/share/annals").publish("report.md", tags=["q3"])
publish(["report.md"], tags="q3")["url"]          # same, through the configured target
```

`annals.api.mk_api(...)` is the mountable API; `annals.api.mk_app(data_dir=..., authorizer=...)` the standalone app.

## Design notes

Flat store with tags and groups, not a hierarchy: agents from many projects do not share one, and every placement decision costs tokens. A document is `docs/<id>/meta.json` plus its files; the bin is `trash/<id>/`; a group is `groups/<gid>.json`. Ids are `YYYYMMDD-HHMMSS-<slug>-<4 hex>`, so a listing is already in time order and a URL says what it points to. The transport is a seam (`annals.target`): local directory, ssh, and later an http ingest endpoint. More in `misc/docs/design.md`.

## Skills

```bash
gh skill install thorwhalen/annals annals-publish
```

The skill also ships inside the package at `annals/data/skills/annals-publish/`.
