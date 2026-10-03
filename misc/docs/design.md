# Design

tray is an in-tray for AI agents: an agent publishes a document with one command and gets a link; the owner reads it on a phone. This page records the boundaries chosen before the first commit (the architecture-first seam table) and why.

## The one-command test

`tray publish README.md` prints a link, and `GET /tray/api/docs` on a `tray serve` over the same directory lists it. That is v1, and `tests/test_cli.py` plus `tests/test_api.py` keep it true.

## Seams

| # | Seam | v1 default (no new dependency) | Replacement it was declared for |
|---|---|---|---|
| 1 | transport, `target=` (`tray.target`) | a local directory, or `host:/path` through the system `ssh` and `rsync` in batch mode | an http ingest endpoint with a bearer token, for agents with no ssh to the host |
| 2 | auth, `authorizer=` (`tray.auth`) | none on localhost; cookie forwarded to an existing who-am-I endpoint plus an email allowlist; HTTP Basic | an OAuth or signed-token check, for a tray with API clients |
| 3 | data root | `~/.local/share/tray`, `TRAY_DATA_DIR` | a `dol` store over blob storage, through the same `Target` verbs |
| 4 | base url for the printed link | `base_url` in the config file | per-target in the config |
| 5 | markdown rendering | `marked.js` in the browser, vendored | server-side rendering (or PDF) if the page ever needs to serve a non-browser reader |

Surfaces: the CLI (`cw` over `tray/tools.py`), the Python API, MCP (`py2mcp` over string refs to the same functions), the shipped skill, and the FastAPI app. All of them read one function list, so there is nothing to keep in parity.

NOT seams, written directly on purpose: the id format, the `meta.json` shape, the bin semantics (a move), the page's framework (none), the sort keys.

## Decisions

**Python on PyPI.** The host that serves the page is Python, so one package holds the store layout, the server and the publisher: one implementation of the layout, no parity test between a JS publisher and a Python reader. `pip install tray` works wherever an agent runs.

**A file write is the publish operation.** Publishing is `rsync` (or a local copy) into the directory the server reads; there is no ingest API and no token to manage. The read side can therefore stay behind whatever login already protects the host, and a tray never becomes a way to post without credentials. An ingest endpoint is seam 1's declared replacement, not a v1 feature.

**Flat with tags and groups.** Agents from many projects do not share a hierarchy, and every placement decision costs tokens. A group is a titled, ordered list of document ids with its own URL, which is the "one link for a set of documents" an agent needs when it has produced several.

**Time-sortable, readable ids.** `YYYYMMDD-HHMMSS-<slug>-<4 hex>`: a directory listing is in publication order, a URL says what it points to, and two publishes in the same second cannot collide.

**Plain files, no index.** The same tree is written by rsync from another machine and read by the server. An index would be a second source of truth to keep consistent across that boundary; listing a few hundred `meta.json` files is cheap.

**The page has no build step.** It is one html shell, one stylesheet and one script, served by the package. The page is a thin viewer over a small JSON API, phone first; a bundler would be the only build in the deployment. If the page grows a second surface (editing, comments), it moves to the usual schema-driven stack.

**Markdown renders in the browser, html in a sandboxed frame.** Rendering client-side keeps the server free of a markdown dependency and makes the source toggle trivial (the same text). An html document is the agent's own code, so the frame cannot read the tray's cookies or call its API (`Content-Security-Policy: sandbox ...` on the raw response plus the frame's `sandbox` attribute).

## Where the data lives

`~/.local/share/tray/{docs,trash,groups}`; `TRAY_DATA_DIR` overrides the root. Nothing under the package or any app directory holds documents.
