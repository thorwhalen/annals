# tray

An in-tray for AI agents. An agent publishes a markdown or html document with one command and gets back a link; the owner opens the tray on a phone and finds everything their agents left for them, newest first, searchable, with a recycle bin.

```bash
pip install tray
tray publish report.md --session my-agent
# https://apps.example.com/tray/d/20261003-203301-quarterly-report-3f9a
```

Documents are plain files in a directory. The directory can be on this machine or on another one over ssh, and `tray serve` turns it into a private page. Nothing else is needed: no database, no build step, no API token.

## For agents

Load the shipped skill, `tray-publish`, and you have the whole protocol: one command, one link, put the link in your reply.

```bash
tray publish report.md                       # one document, prints its link
tray publish a.md b.md c.html --group "Review"   # one link for a set (the group link prints first)
tray publish ./artifact_dir                  # an html page with its assets, as one document
some-command | tray publish - --title "Log"  # from stdin
tray ls "search words"                       # what is there, newest first
tray trash <id>  /  tray restore <id>        # the recycle bin
```

`--title` overrides the inferred title (first `# heading` or `<title>`), `--tags a,b` adds searchable tags, `--session name` records who published. Markdown renders on the page with a toggle to the raw, copyable source; html renders as-is.

With `pip install 'tray[mcp]'`, the same operations are an MCP server: `python -m tray.mcp`.

## For the owner: where it goes and what link it prints

```bash
tray configure --target tw:/root/.local/share/tray --base-url https://apps.example.com/tray
```

That writes `~/.config/tray/config.toml`. `target` is a directory, or `host:/path` for a directory on another machine reached by `ssh host` (keys, no prompt; `host` can be an alias from `~/.ssh/config`). `TRAY_TARGET` and `TRAY_BASE_URL` override it per shell. With no configuration, documents go to `~/.local/share/tray` and the link points at a local `tray serve`.

## Hosting the page

```bash
pip install 'tray[server]'
TRAY_DATA_DIR=~/.local/share/tray tray serve --host 127.0.0.1 --port 8765
```

The page is at `http://127.0.0.1:8765/tray/`; its JSON API under `/tray/api/`. Put a reverse proxy in front for https. Auth is chosen by environment variables:

| Situation | Set | Effect |
|---|---|---|
| Behind an existing login that exposes a who-am-I endpoint (enlace_auth's `/auth/whoami`) | `TRAY_WHOAMI_URL=http://127.0.0.1:8010/auth/whoami`, `TRAY_ALLOWED_USERS=me@example.com`, optionally `TRAY_LOGIN_URL=/auth/login` | the tray forwards the browser's cookies to that endpoint and allows the listed emails; anyone else is sent to the login page |
| No platform login | `TRAY_BASIC_USER`, `TRAY_BASIC_PASSWORD` | HTTP Basic |
| Localhost only | nothing | open |

A systemd unit and a Traefik router for the first case are in `misc/deploy/`.

## Python API

```python
from tray import DocStore, publish
meta = DocStore("~/.local/share/tray").publish("report.md", tags=["q3"])
publish("report.md", tags="q3")["url"]          # same, through the configured target
```

`tray.api.mk_app(data_dir=..., authorizer=...)` returns the FastAPI app for embedding.

## Design notes

Flat store with tags and groups, not a hierarchy: agents from many projects do not share one, and every placement decision costs tokens. A document is `docs/<id>/meta.json` plus its files; the bin is `trash/<id>/`; a group is `groups/<gid>.json`. Ids are `YYYYMMDD-HHMMSS-<slug>-<4 hex>`, so a listing is already in time order and a URL says what it points to. The transport is a seam (`tray.target`): local directory, ssh, and later an http ingest endpoint. More in `misc/docs/design.md`.

## Skills

```bash
gh skill install thorwhalen/tray tray-publish
```

The skill also ships inside the package at `tray/data/skills/tray-publish/`.
