# Design

annals is an in-tray for AI agents: an agent publishes a document (text, a page, media, a folder) with one command and gets a link; the owner reads it on a phone. This page records the boundaries chosen before the first commit (the architecture-first seam table) and why.

## The one-command test

`annals publish README.md` prints a link, and `GET /docs` on the API over the same directory lists it (`/annals/api/docs` under `annals serve`, `/api/annals/docs` inside an enlace platform). That is v1, and `tests/test_cli.py` plus `tests/test_api.py` keep it true.

## Seams

| # | Seam | v1 default (no new dependency) | Replacement it was declared for |
|---|---|---|---|
| 1 | transport, `target=` (`annals.target`) | a local directory, or `host:/path` through the system `ssh` and `rsync` in batch mode | an http ingest endpoint with a bearer token, for agents with no ssh to the host. Not a third `Target`: a `Target` writes raw paths and the publisher authors `meta.json`, which an untrusted client must not. Ingest is a server-side publish entry point that receives the files and derives `id`, `files` and `kind` itself |
| 2 | auth, `authorizer=` (`annals.auth`) | none on localhost; cookie forwarded to an existing who-am-I endpoint plus an email allowlist; HTTP Basic | an OAuth or signed-token check, for a annals with API clients |
| 3 | data root | `~/.local/share/annals`, `ANNALS_DATA_DIR` | a `dol` store over blob storage, through the same `Target` verbs; the API reaches files only through `Target.local_path` (a blob target would answer `None`, and serving it then means one redirect to the store's URL at that call site) |
| 4 | base url for the printed link | `base_url` in the config file | per-target in the config |
| 5 | markdown rendering | `marked.js` in the browser, vendored | server-side rendering (or PDF) if the page ever needs to serve a non-browser reader |
| 6 | host, `mk_api` vs `mk_app` | mounted inside an app platform that owns login and routing (`mk_api` + a page shell); `annals serve` standalone otherwise | none needed: both exist |
| 7 | thumbnails, `thumbnailer=` | Pillow when installed, cached under the data root's `cache/thumbs`; else the original | a blob store's own image resizing, or poster frames for video via ffmpeg |
| 8 | what a directory publish skips, `exclude=` | `.*`, `__pycache__`, `*.pyc` | per-call patterns (`--all-files` keeps everything) |

Surfaces: the CLI (`cw` over `annals/tools.py`), the Python API, MCP (`py2mcp` over string refs to the same functions), the shipped skill, and the FastAPI app. All of them read one function list, so there is nothing to keep in parity.

NOT seams, written directly on purpose: the id format, the `meta.json` shape, the bin semantics (a move), the page's framework (none), the sort keys.

## Decisions

**Python on PyPI.** The host that serves the page is Python, so one package holds the store layout, the server and the publisher: one implementation of the layout, no parity test between a JS publisher and a Python reader. `pip install annals` works wherever an agent runs.

**Deployed with the platform; the content never is.** On the owner's host annals is an ordinary app: the platform installs the package, mounts the API, serves the page shell and gates both with its login, like every other app. The documents live in the data root (`~/.local/share/annals`), outside the app directory, and are written there directly by `annals publish`, so a new document never triggers a deploy, a deploy never touches a document, and a broken document cannot take the platform down. The first version ran as a separate service to get that independence; it was the content, not the code, that needed it.

**Media are documents.** An image, a video, audio or a PDF shows inline; a folder is one document, shown as its page (when it has one) or as a gallery. Files are served with `FileResponse`, which streams and answers byte ranges, because a video that cannot seek, or that Safari refuses to play, is not shown at all. Thumbnails are made on first request and cached next to the documents, so a folder of two thousand renders loads on a phone.

**A file write is the publish operation.** Publishing is `rsync` (or a local copy) into the directory the server reads; there is no ingest API and no token to manage. The read side can therefore stay behind whatever login already protects the host, and a annals never becomes a way to post without credentials. An ingest endpoint is seam 1's declared replacement, not a v1 feature.

**Flat with tags and groups.** Agents from many projects do not share a hierarchy, and every placement decision costs tokens. A group is a titled, ordered list of document ids with its own URL, which is the "one link for a set of documents" an agent needs when it has produced several.

**Time-sortable, readable ids.** `YYYYMMDD-HHMMSS-<slug>-<4 hex>`: a directory listing is in publication order, a URL says what it points to, and two publishes in the same second cannot collide.

**Plain files, no index.** The same tree is written by rsync from another machine and read by the server. An index would be a second source of truth to keep consistent across that boundary; listing a few hundred `meta.json` files is cheap.

**The page has no build step.** It is one html shell, one stylesheet and one script, served by the package; a host keeps only the shell (two paths), so the page upgrades with the package. The page is a thin viewer over a small JSON API, phone first; a bundler would be the only build in the deployment. If the page grows a second surface (editing, comments), it moves to the usual schema-driven stack.

**Markdown renders in the browser, html in a sandboxed frame.** Rendering client-side keeps the server free of a markdown dependency and makes the source toggle trivial (the same text). An html document is the agent's own code, so the frame cannot read the annals's cookies or call its API (`Content-Security-Policy: sandbox ...` on the raw response plus the frame's `sandbox` attribute).

## Where the data lives

`~/.local/share/annals/{docs,trash,groups}`, plus `cache/thumbs` (derived, safe to delete); `ANNALS_DATA_DIR` overrides the root. Nothing under the package or any app directory holds documents.

## Trust boundary

`meta.json` is written by the publisher, so the server does not trust it to keep paths in bounds: a raw or thumbnail request must name a file the meta lists AND resolve inside that document's directory (symlinks included). Every raw response except PDF carries `Content-Security-Policy: sandbox`, because the page shares its origin with every other app on the host and a browser renders more types as documents than any list would name. Markdown is rendered in the page, so marked's output always goes through DOMPurify first.
