# annals

Annals for AI agents. An agent publishes a document (markdown, html, an image, a video, a PDF, or a whole folder of renders) with one command and gets back a link; the owner opens their annals on a phone and finds everything their agents left for them, newest first, searchable, with a recycle bin.

```bash
pip install annals
annals publish report.md --session my-agent
# https://apps.example.com/annals/d/20261003-203301-quarterly-report-3f9a
```

Beside what agents publish, the page can list other folders read in place, such as the sessions' ledgers (`~/.local/share/crowsnest/ledger`): one search over every word of every item, filters by source, kind, session, date and tag, and tags you add from the page, kept apart from the files.

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
annals publish guide.html --replace <link-or-id>  # a new version of a document: same link
annals publish page.html --artifact <claude.ai artifact link>  # plus a button to its interactive version
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

### Interactive version (`--artifact`)

`annals publish page.html --artifact https://claude.ai/...` stores the link of a Claude Artifact holding the same page in the document's meta (`artifact`), and the document's page shows an "Open the interactive version" button next to the frame. Comments, per-viewer and shared state and sharing then live on the artifact while annals stays the single in-tray. Only plain `https` links to `claude.ai` are accepted (`annals.store.ARTIFACT_HOSTS`; no port, credentials or odd characters), `--artifact` takes one path, and a `--replace` without `--artifact` keeps the current link.

### Living pages (`--replace`)

`annals publish <path> --replace <link-or-id>` publishes a new version of an existing document: the id and the link stay, the page shows the new version marked "updated" and lists the earlier ones, each readable at `/d/<id>@<n>`. The previous files are kept under the document's `.versions/<n>/`; nothing is deleted. It takes one path (a file, a folder, stdin), and a replaced group member stays in its group.

A replacement is written next to the document as a pending directory (`docs/<id>.r<stamp>-<hex>/`), never over it, and applied by whoever reads the store (the server, or the next publish): a few renames, the first of which claims the document, so concurrent readers never apply one twice or out of order. That is what lets a replace travel through an **outbox**, a directory another machine pulls and empties: mark it with `annals configure --outbox` (or `ANNALS_OUTBOX=1`), and replacements published there are left for the server to apply when they land. HTML pages without a doctype are served with `<!doctype html>` (plus a charset and viewport when missing), so they render in standards mode.

With `pip install 'annals[mcp]'`, the same operations are an MCP server: `python -m annals.mcp`.

## Where documents go

```bash
annals configure --target tw:/root/.local/share/annals --base-url https://apps.example.com/annals
```

That writes `~/.config/annals/config.toml`. `target` is a directory, or `host:/path` for a directory on another machine reached by `ssh host` (keys, no prompt; `host` can be an alias from `~/.ssh/config`). `ANNALS_TARGET` and `ANNALS_BASE_URL` override it per shell. With no configuration, documents go to `~/.local/share/annals` and the link points at a local `annals serve`.

### A second place (`--to`)

A config file can name more places: `annals configure --to team --target host:/path --base-url https://team.example.com/annals` saves a `[targets.team]` table and leaves the default alone. Then `annals publish r.md --to team` (also `ls`, `show`, `trash`, `restore`, `group`, `groups`) works on that place only, and `annals copy <link-or-id> --to team [--source other]` copies documents or whole groups there, keeping their ids. Nothing about the place is in the code: a name, a target and a base url.

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

## Acting on documents: pick, then choose what you want back

On a group's page, tick the documents you want (with none ticked, all of them count); a bar at the bottom says what is picked and offers three buttons named after what they give, each opening one sheet (Back closes it):

- **Links**: **One link** for a person (expiry, optional password, and on a document "What's included") or **A link per document** for a notebook or an agent (one plain page each, no password). Every link has its own copy button, plus **Copy all**.
- **One file**: the picked documents' files (Markdown, html, text, PDFs, images) as one Markdown, PDF or web page file, to copy, download or open.
- **Listen**: a spoken review (when the host offers them, see below). For several documents, **One review of all** (their text is put in one document, tagged `combined` and added to the group, and that document gets an ordinary review; the same documents at the same versions reuse it) or **One each** (makes only the missing or out-of-date ones).

A document's page has the same three buttons, acting on that document, and both pages keep the rest (copy the text, downloads, open raw, move to bin) under **⋯ More**. Every link, password and code block on the page has the same copy button: it copies inside the tap and answers on itself with a check and "Copied".

## Spoken overviews

A document's page can offer a Listen button: a few minutes of speech about the document, played with its script in sync. It is off unless the host turns it on, because making one spends money.

```python
app = mk_api(overviews=True)  # the button, and POST /docs/{id}/overview
```

A worker on the same machine fulfils the requests. It runs a command you choose, which takes a text file and writes one HTML page, and publishes that page as a document of its own:

```bash
export ANNALS_OVERVIEW_COMMAND='hailing overview {source} --minutes {minutes} --no-publish --player-to {out}'
annals listen-work                 # fulfils what is queued, one at a time
annals listen <doc-id> --minutes 3 # asks for one from the command line, as the button does
```

Run `annals listen-work` from a timer, not from a watcher on the folder: finished request files stay there, so a watcher would keep waking it. A current overview is not made again unless forced, and at most 20 are started in any 24 hours (`ANNALS_OVERVIEW_DAILY_LIMIT`). `annals.overview` has the details.

## Sharing one page

The annals is private; a **share link** lets someone without an account read ONE document (or one group) and nothing else. From the page, **Links › One link** on a document lists its files and the annals pages it links to under "What's included", so you choose what goes; from a shell:

```bash
annals share <id-or-link> --password -                       # 7 days by default; password from stdin
annals share <id> --expires 2026-11-30                       # or 12h, 30d, an ISO time, `never`
annals share <id> --include img/chart.png,img/map.png        # only these files (the page always goes)
annals shares                                                # live links (--all: revoked and expired too)
annals unshare <link-or-token>                               # off at once
```

The link is `<share_base_url>/<token>/`: 128 random bits, `noindex`, `no-referrer`. Every request is checked against the share's record (`shares/<token>.json` under the data root), so a file you did not choose is a 404 even beside the shared page, a revoke or an expiry takes effect on the next request, and references to anything outside the share (an image you left out, a link to another annals page or to anything else on your annals' host, an annals id in the text) are removed from every text file before it is sent (markdown, html, plain text, svg). A linked page you tick goes with the files it shows, not every file beside it. The password is a gate on the link, not an account: at least 8 characters, stored hashed (stdlib scrypt), with attempts limited per client and per link, and a correct one earns a cookie scoped to that link. Links are read-only and last 7 days unless you say otherwise.

Where the links are served:

- **Standalone** (`annals serve`): at `/annals/shared/<token>/`, outside the login, with nothing to configure.
- **Inside an app platform**: the share server must be reachable without the platform's login, so run it as its own public app and tell annals where it is:

```python
# server.py of a second, PUBLIC app (the owner's app keeps its login)
from annals.share_api import mk_share_api
app = mk_share_api(data_dir="/root/.local/share/annals")
```

then set `ANNALS_SHARE_BASE_URL` (or `annals configure --share-base-url ...`, or `mk_api(share_base_url=...)` for the owner's page) to that app's public URL. Until it is set, shares are made but carry no link. `mk_share_api` takes `rate_limiter=` and `link_failure_limiter=` (anything with `allow(key) -> bool`, such as heed's Redis limiter; the defaults count per process), `trusted_proxies=` (whose `X-Forwarded-For` names the client; loopback by default) and `private_hosts=`; the password `hasher` is a keyword of `annals.share.Shares` (argon2, or anything with `hash`/`verify`).

## Downloads

Every markdown page offers two downloads made by the server, under **One file** and under **⋯ More**: **Markdown (.md)** and a titled **PDF** with the images inside (audio, video and other files appear as a link to the resource). Both are named after the title (`quarterly-report-q3.pdf`) and are served under the same rules as the page: the owner's login, or a share link's scope (a recipient gets the filtered text and only the files the link includes). The PDF needs `pip install "annals[pdf]"` (WeasyPrint, which uses Pango; `annals[server]` includes it); without it the PDF action answers with that hint. Pages (`/d/<id>`) are drawn in the browser by `app.js`, so a page that gains an action gains it for every existing document.

## One file from many: Markdown, PDF or a web page

**One file** (on a group, a selection or one document) combines the picked documents' files into a single file and lets you choose its format: **Markdown** (shown, with **Copy Markdown**, **Download .md** and **Open as text**), **PDF** (with a bookmark for each file) or a **Web page** (one self-contained `.html`). Audio and video cannot be part of a document; they are listed as left out, each with the reason, and so is a file that cannot be read (a damaged or password-protected PDF) while the others still go in. It is made on each request and never stored. A share link has the same button, built from the share's filtered text and only the files it includes.

| input | to Markdown | to web page / to PDF |
|---|---|---|
| markdown | as it is | rendered, the document's images inside |
| html | converted (needs `markdownify`) | its structure and words; scripts, styles, frames, forms and remote images are dropped |
| text (`.txt`, `.json`, `.csv`, code...) | a code block | a preformatted block |
| PDF | its text (a scan has none) | web page: its text; PDF: its pages, joined as they are |
| image | not supported | a figure / a page of its own |

An image or a text file that sits in a document with pages (markdown, html, a PDF) belongs to that document, not a section of its own: a report and its figures combine as the report. Files are arranged with numbered names first, in numeric order, then the rest in the documents' order.

```bash
annals aggregate <group-or-doc-id-or-link> > all.md                    # Markdown, from a shell
annals aggregate <id> --format pdf --output all.pdf                     # a PDF needs --output
annals aggregate <id> --format html --output all.html
annals aggregate <id> --order given --demote 0 --no-toc --keep-wraps   # Markdown options
```

The libraries behind each pair load only when it is used: PDF pages need WeasyPrint (which uses Pango), joining and reading PDFs need `pypdf` and `pdfdol`, html to Markdown needs `markdownify`. `pip install "annals[pdf]"` installs them all; a missing one stops the job before it starts, naming the library and the command. The API is `GET /groups/<gid>/aggregate?format=md|html|pdf` and `GET /aggregate?doc=<id>&doc=<id>` (`&download=1` to save, `&demote=`), `GET /<token>/aggregate` on the share server, and `GET /combine/formats` for what can be made; the response carries `X-Annals-Sections` (files that went in) and `X-Annals-Skipped` (percent-encoded JSON: which were left out and why).

A new pair (say docx to PDF) is one function in `annals/combine.py`, and every surface above learns it:

```python
from annals.combine import register

@register("docx", "pdf", requires=("some_module",))
def docx_to_pdf(item, ctx):          # item.text(), item.data(), item.rel; return the part for the format
    ...
```

```python
from annals.aggregate import aggregate_markdown        # the text mechanism, no documents involved
aggregate_markdown({"notes.md": "# Notes", "01-intro.md": "Hello"}, title="Bundle", demote=1)
```

`aggregate_markdown` takes `(path, text)` pairs and knows nothing of annals: `order=` (`numbered_first` by default, `None` for the order given, or any `paths -> paths` callable), `demote=`, `unwrap=`, `toc=`. The Markdown file has the title, a table of contents, and one `##` section per file named after its path (`Report/01-intro.md`); each file's headings go one level down and hard-wrapped lines are joined. Footnotes are renamed per file so they do not collide, and a code block a file leaves open is closed at the end of its section. Relative links and images keep their paths, so they do not resolve inside the combined Markdown.

## A group's documents as separate notebook sources

To take a group into a notebook (NotebookLM, now Gemini Notebook) with each document as its own source, open the group, tick the documents (none ticked means all), tap **Links**, choose **A link per document** and how long the links work (1 day by default), and tap **Make N links**. You get one link per page, each with its own copy button; tap **Copy all N links**, then in the notebook choose Add source → Website and paste: the notebook makes one source of each link, named after the document.

The links are an ordinary share of just those documents (no password, since the notebook cannot type one): unguessable, filtered like every shared text, and revocable with **Turn these links off** or under the **Links** tab. The notebook keeps its own copy once a link is added, so turning the links off afterwards does not remove the sources. Each link is a plain web page with no script (`<share link>/source/<doc id>/<file>`); markdown is rendered on the server, images, audio and PDFs get no link (a notebook takes those only as uploads). Why links and not a zip or a download: `misc/docs/notebook-sources.md`.

The API: `GET /shares/<token>/sources` (the owner's) or `GET <share link>/sources` (the recipient's) lists `{title, url}` per page; `GET /groups/<gid>/aggregate?doc=<id>&doc=<id>` combines only those documents.

## Other folders, search, filters and tags

Name extra folders when you mount the API, and they appear beside the published documents, each in its own section (`/annals/s/<name>`) and in `/annals/all`:

```python
app = mk_api(data_dir="~/.local/share/annals", sources={"ledgers": "~/.local/share/crowsnest/ledger"})
```

or, with no code, `ANNALS_SOURCES="ledgers=~/.local/share/crowsnest/ledger"` (several: comma-separated). A folder is read in place and never written: its files are listed newest first with their age, markdown renders, html is framed, the rest shows by its kind, and a sub-folder's files count as written by the sub-folder's name. Hidden files and caches are skipped.

On every list:

- **Search** matches every word, case-insensitively, against titles, tags, sessions, excerpts and the full text of markdown and text files (on the server; the matching passage shows under the title).
- **Filters** are one button per family (source, kind, session, date, tag). Checked values within a family are alternatives ("any of"), families combine ("and"), the counts are what each choice would give now, and the active filters show as removable chips. The filters and the search are in the URL, so Back undoes a filter and a link reproduces the view.
- **Tags**: add or remove them on any item's page; they save as you go. They are stored apart from the items, in one file under the data root (`tags/tags.json`), so a ledger is never touched; on a published document they replace the tags the publisher gave.

The API behind it: `GET /items?q=&source=&trash=` → `{data, total}`, `GET /items/<source>:<id>`, `PATCH /items/<source>:<id>` with `{"tags": [...]}`, `GET /tags`, `GET /sources`, and `GET /files/<source>/<path>` for a folder's raw files. The page reaches items through [`@zodal/store-http`](https://www.npmjs.com/package/@zodal/store-http)'s provider (vendored; rebuild with `misc/vendor/build.sh`).

## Python API

```python
from annals import DocStore, publish
meta = DocStore("~/.local/share/annals").publish("report.md", tags=["q3"])
publish(["report.md"], tags="q3")["url"]          # same, through the configured target
```

`annals.api.mk_api(...)` is the mountable API; `annals.api.mk_app(data_dir=..., authorizer=...)` the standalone app. Both take `sources=` (name → folder path, or any `annals.sources.Source`) and `tags=` (any `MutableMapping` from item key to tag list; default `JsonTagStore`). `annals.catalog.Catalog` is the facade they stand on: every source's rows as one list, searched, with the owner's tags.

## Design notes

Flat store with tags and groups, not a hierarchy: agents from many projects do not share one, and every placement decision costs tokens. A document is `docs/<id>/meta.json` plus its files; the bin is `trash/<id>/`; a group is `groups/<gid>.json`. Ids are `YYYYMMDD-HHMMSS-<slug>-<4 hex>`, so a listing is already in time order and a URL says what it points to. The transport is a seam (`annals.target`): local directory, ssh, and later an http ingest endpoint. More in `misc/docs/design.md`.

## Skills

```bash
gh skill install thorwhalen/annals annals-publish
```

The skill also ships inside the package at `annals/data/skills/annals-publish/`.
