"""Spoken overviews of a document: the request a page makes, and the worker that fulfils it.

A reader asks for an overview from a document's page. That writes one small JSON file under
the data root (``overviews/<doc id>.json``). A worker on the same machine reads the document
from the store, runs a command that makes the overview, and publishes the result as a
document of its own. The page polls the request's state.

annals does not know how an overview is made. The command is the seam: any program that
takes a text file and writes one HTML page, named in ``ANNALS_OVERVIEW_COMMAND`` or passed to
:func:`work`, with ``{source}``, ``{minutes}`` and ``{out}`` filled in::

    my-overview {source} --minutes {minutes} --player-to {out}

The feature is off unless the host turns it on (``mk_api(overviews=True)``), because making
an overview spends money.

>>> html_to_text("<title>x</title><p>One &amp; two</p><script>no()</script><p>Three</p>")
'One & two\\n\\nThree'
>>> [c["characters"] for c in choices()]
[2700, 4500, 6300]
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Sequence

ENV_COMMAND = "ANNALS_OVERVIEW_COMMAND"
FOLDER = "overviews"
LOCK_NAME = ".lock"
#: the lengths a reader can pick, in minutes; each costs voice characters, so the set is closed
MINUTES = (3, 5, 7)
DFLT_MINUTES = 5
#: spoken English at about 150 words a minute and 6 characters a word; shown as an estimate
CHARS_PER_MINUTE = 900
DFLT_TIMEOUT_S = 1800
MAX_ERROR_CHARS = 300
#: marks a document that is itself an overview, so nobody makes an overview of an overview
TAG = "overview"
SUPPORTED_KINDS = frozenset({"md", "text", "html"})
QUEUED, RUNNING, DONE, FAILED, NONE = "queued", "running", "done", "failed", "none"
ACTIVE = frozenset({QUEUED, RUNNING})
_SKIPPED_TAGS = frozenset({"script", "style", "head", "title", "template", "noscript", "svg"})
_BLOCK_TAGS = frozenset(
    "p div section article br li tr h1 h2 h3 h4 h5 h6 blockquote pre table ul ol".split()
)


def choices() -> list[dict]:
    """Each length on offer and what it would cost in voice characters."""
    return [{"minutes": m, "characters": m * CHARS_PER_MINUTE} for m in MINUTES]


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIPPED_TAGS:
            self.skipping += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in _SKIPPED_TAGS:
            self.skipping = max(0, self.skipping - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """The readable text of a page: no markup, scripts or styles."""
    parser = _Text()
    parser.feed(html)
    blocks = (" ".join(b.split()) for b in "".join(parser.parts).split("\n\n"))
    return "\n\n".join(b for b in blocks if b)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def eligible(meta: dict) -> bool:
    """Whether a document can be spoken: readable text, current, and not itself an overview."""
    return (
        meta.get("kind") in SUPPORTED_KINDS
        and not meta.get("in_trash")
        and "version_of" not in meta
        and TAG not in (meta.get("tags") or [])
    )


class Requests:
    """The request files: one per document, each replaced whole so a reader never sees half."""

    def __init__(self, data_dir: Path | str):
        self.folder = Path(data_dir) / FOLDER

    def _path(self, doc_id: str) -> Path:
        return self.folder / f"{doc_id}.json"

    def get(self, doc_id: str) -> dict | None:
        try:
            return json.loads(self._path(doc_id).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None

    def put(self, doc_id: str, record: dict) -> dict:
        self.folder.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.folder, prefix=".tmp-", suffix=".part")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f)
        # A name that ends in .json appears at once and whole, so the worker's watcher fires
        # only for a finished file.
        os.replace(tmp, self._path(doc_id))
        return record

    def ids(self) -> list[str]:
        """Documents with a request, oldest request first."""
        if not self.folder.is_dir():
            return []
        paths = sorted(self.folder.glob("*.json"), key=lambda p: p.stat().st_mtime)
        return [p.stem for p in paths]


def state_of(store, requests: Requests, meta: dict) -> dict:
    """What a page shows for a document: its request's state and what it can start."""
    record = requests.get(meta["id"]) or {}
    state = record.get("state", NONE)
    overview = record.get("overview")
    if state == DONE:
        try:
            if store.meta(overview).get("in_trash"):
                state, overview = NONE, None
        except (KeyError, ValueError, OSError):  # deleted since it was made
            state, overview = NONE, None
    return {
        "state": state,
        "minutes": record.get("minutes", DFLT_MINUTES),
        "overview": overview,
        "error": record.get("error") if state == FAILED else None,
        "stale": state == DONE and record.get("version") != meta.get("version"),
        "choices": choices(),
    }


def request(store, requests: Requests, doc_id: str, *, minutes: int = DFLT_MINUTES) -> dict:
    """Ask for an overview of a document. Raises ``ValueError`` if it cannot be asked for.

    Asking again while one is being made changes nothing, so a double tap costs nothing.
    """
    meta = store.meta(doc_id)
    if not eligible(meta):
        raise ValueError("this document cannot be spoken")
    if minutes not in MINUTES:
        raise ValueError(f"minutes must be one of {list(MINUTES)}")
    current = state_of(store, requests, meta)
    if current["state"] in ACTIVE:
        return current
    requests.put(
        doc_id,
        {"state": QUEUED, "minutes": minutes, "version": meta.get("version"), "requested": _now()},
    )
    return state_of(store, requests, meta)


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1][:MAX_ERROR_CHARS] if lines else ""


def _source_text(store, meta: dict) -> str:
    text = store.read_text(meta["id"])
    return html_to_text(text) if meta.get("kind") == "html" else text


def _fulfil(store, doc_id: str, *, minutes: int, command: Sequence[str], timeout: float) -> str:
    """Make the overview and publish it; return the new document's id."""
    meta = store.meta(doc_id)
    if not eligible(meta):
        raise RuntimeError("this document can no longer be spoken")
    text = _source_text(store, meta).strip()
    if not text:
        raise RuntimeError("this document has no text to speak")
    with tempfile.TemporaryDirectory(prefix="annals-overview-") as tmp:
        source = Path(tmp) / "source.md"
        title = meta.get("title") or doc_id
        source.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
        out = Path(tmp) / "overview.html"
        fill = {"source": str(source), "minutes": str(minutes), "out": str(out)}
        argv = [arg.format(**fill) for arg in command]
        try:
            done = subprocess.run(
                argv, cwd=tmp, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL, check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"gave up after {int(timeout)} seconds") from None
        except OSError as e:
            raise RuntimeError(f"could not run the overview command: {e.strerror}") from None
        if done.returncode:
            why = _last_line(done.stderr) or _last_line(done.stdout)
            raise RuntimeError(why or f"the overview command exited {done.returncode}")
        if not out.is_file() or not out.stat().st_size:
            raise RuntimeError("the overview command wrote no page")
        made = store.publish(
            out, title=f"Listen: {title}", tags=[TAG], source={"session": "annals overview", "of": doc_id},
        )  # fmt: skip
    return made["id"]


@contextmanager
def _only_one_worker(folder: Path):
    """Yields whether this process holds the lock. Another worker means this one does nothing."""
    import fcntl

    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / LOCK_NAME, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True


def _command(command: str | Sequence[str] | None) -> list[str]:
    command = command or os.environ.get(ENV_COMMAND)
    if not command:
        raise ValueError(f"no overview command: pass one, or set {ENV_COMMAND}")
    argv = shlex.split(command) if isinstance(command, str) else list(command)
    if not any("{out}" in arg for arg in argv) or not any("{source}" in arg for arg in argv):
        raise ValueError("the overview command must name {source} and {out}")
    return argv


def work(
    store,
    requests: Requests,
    *,
    command: str | Sequence[str] | None = None,
    timeout: float = DFLT_TIMEOUT_S,
) -> list[dict]:
    """Fulfil every queued request, one at a time; return what happened to each.

    A failure is recorded on its request, for the page to show, and the next one still runs.
    A request left ``running`` belonged to a worker that died, since this one holds the lock.
    """
    argv = _command(command)
    results = []
    with _only_one_worker(requests.folder) as mine:
        if not mine:
            return results
        for doc_id in requests.ids():
            record = requests.get(doc_id)
            if not record:
                continue
            if record.get("state") == RUNNING:
                requests.put(doc_id, {**record, "state": FAILED, "error": "the worker stopped before finishing"})
                results.append({"doc": doc_id, "state": FAILED})
                continue
            if record.get("state") != QUEUED:
                continue
            requests.put(doc_id, {**record, "state": RUNNING, "started": _now()})
            try:
                made = _fulfil(store, doc_id, minutes=record["minutes"], command=argv, timeout=timeout)
            except Exception as e:  # recorded for the page; the next request must still run
                requests.put(doc_id, {**record, "state": FAILED, "error": str(e)[:MAX_ERROR_CHARS], "finished": _now()})
                results.append({"doc": doc_id, "state": FAILED, "error": str(e)[:MAX_ERROR_CHARS]})
            else:
                requests.put(doc_id, {**record, "state": DONE, "overview": made, "finished": _now()})
                results.append({"doc": doc_id, "state": DONE, "overview": made})
    return results
