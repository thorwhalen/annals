"""Spoken overviews of a document: the request a page makes, and the worker that fulfils it.

A reader asks for an overview from a document's page. That writes one small JSON file under
the data root (``overviews/<doc id>.json``). A worker on the same machine reads the document
from the store, runs a command that makes the overview, and publishes the result as a
document of its own. The page polls the request's state.

annals does not know how an overview is made. The command is the seam: any program that
takes a text file and writes one HTML page, named in ``ANNALS_OVERVIEW_COMMAND`` or passed to
:func:`work`, with ``{source}``, ``{minutes}`` and ``{out}`` filled in, and ``{url}``, the source document's
page, so the overview can link to what it was based on::

    my-overview {source} --minutes {minutes} --player-to {out} --source-url {url}

The feature is off unless the host turns it on (``mk_api(overviews=True)``), because making
an overview spends money. For the same reason, a current overview is not made again unless
forced, a crash after publishing does not pay twice, ``work`` stops at a daily limit, and a
request nobody fulfilled expires rather than spending money whenever a worker next wakes.

Run the worker on a timer. Finished request files stay in the folder and the worker writes
there, so a watcher on the folder would keep waking it.

>>> html_to_text("<title>x</title><p>One &amp; two</p><script>no()</script><p>Three</p>")
'One & two\\n\\nThree'
>>> [c["characters"] for c in choices()]
[2700, 4500, 6300]
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Sequence

ENV_COMMAND = "ANNALS_OVERVIEW_COMMAND"
FOLDER = "overviews"
LOCK_NAME = ".lock"
SPEND_LOG = "spend.jsonl"
ENV_DAILY_LIMIT = "ANNALS_OVERVIEW_DAILY_LIMIT"
#: at most this many overviews are started in any 24 hours, whoever asks
DFLT_DAILY_LIMIT = 20
#: a request still queued after this long is dropped: nobody is waiting for it now
QUEUED_EXPIRY_S = 3600
#: a request still running after this long has lost its worker
RUNNING_MARGIN_S = 600
KILL_GRACE_S = 5
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
_SKIPPED_TAGS = frozenset({"script", "style", "title", "template", "noscript", "svg"})
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
        if (
            tag == "body"
        ):  # end tags are optional in HTML, so nothing skipped runs past this
            self.skipping = 0
        elif tag in _SKIPPED_TAGS:
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


def _older_than(stamp, seconds: float) -> bool:
    """Whether an ISO time is further back than ``seconds``. An unreadable one counts as old."""
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - when > timedelta(seconds=seconds)


def _lost(record: dict) -> str | None:
    """Why an active request will never finish by itself, or ``None`` if it still may."""
    if record.get("state") == QUEUED and _older_than(
        record.get("requested"), QUEUED_EXPIRY_S
    ):
        return "no worker picked this up"
    if record.get("state") == RUNNING and _older_than(
        record.get("started"), DFLT_TIMEOUT_S + RUNNING_MARGIN_S
    ):
        return "the worker stopped before finishing"
    return None


def valid_minutes(minutes) -> bool:
    """Whether this is a length on offer. Exactly an int: not ``True``, and not ``3.0``."""
    return type(minutes) is int and minutes in MINUTES


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
            record = json.loads(self._path(doc_id).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None
        return record if isinstance(record, dict) else None

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

    def started_today(self) -> int:
        """How many overviews were started in the last 24 hours."""
        try:
            lines = (self.folder / SPEND_LOG).read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return 0
        return sum(
            not _older_than(line.split()[0] if line.split() else None, 24 * 3600)
            for line in lines
        )

    def note_start(self, doc_id: str) -> None:
        """Logged before the money is spent, so a crash still counts against the limit."""
        with open(self.folder / SPEND_LOG, "a", encoding="utf-8") as f:
            f.write(f"{_now()} {doc_id}\n")


def state_of(store, requests: Requests, meta: dict) -> dict:
    """What a page shows for a document: its request's state and what it can start."""
    record = requests.get(meta["id"]) or {}
    state = record.get("state", NONE)
    overview = record.get("overview")
    error = record.get("error")
    if lost := _lost(record):
        state, error = FAILED, lost
    if state == DONE:
        try:
            if not isinstance(overview, str) or store.meta(overview).get("in_trash"):
                state, overview = NONE, None
        except (KeyError, ValueError, OSError):  # deleted since it was made
            state, overview = NONE, None
    return {
        "state": state,
        "minutes": record.get("minutes", DFLT_MINUTES),
        "overview": overview,
        "error": error if state == FAILED else None,
        "stale": state == DONE and record.get("version") != meta.get("version"),
        "choices": choices(),
    }


#: a failed request is still listed as unmade for this long, so a retry is offered where
#: the reader looks for the overview (the Audio tab), not only on the document
FAILED_SHOWN_S = 7 * 24 * 3600


def unmade(store, requests: Requests) -> list[dict]:
    """The overviews asked for and not (yet) made: being made, or failed recently; newest first.

    Each is ``state_of`` its document plus ``doc``, ``title``, ``created`` (the document's),
    ``requested`` and ``finished`` (the last try's). A request whose document is gone, binned
    or no longer speakable is left out: nothing can be retried.
    """
    out = []
    for doc_id in reversed(requests.ids()):
        try:
            meta = store.meta(doc_id)
        except (KeyError, ValueError, OSError):
            continue
        if not eligible(meta):
            continue
        record = requests.get(doc_id) or {}
        state = state_of(store, requests, meta)
        when = record.get("finished") or record.get("requested")
        if state["state"] in ACTIVE or (
            state["state"] == FAILED and not _older_than(when, FAILED_SHOWN_S)
        ):
            out.append(
                {
                    **state,
                    "doc": doc_id,
                    "title": meta.get("title") or doc_id,
                    "created": meta.get("created"),
                    "requested": record.get("requested"),
                    "finished": record.get("finished"),
                }
            )
    return out


def request(
    store,
    requests: Requests,
    doc_id: str,
    *,
    minutes: int = DFLT_MINUTES,
    force: bool = False,
) -> dict:
    """Ask for an overview of a document. Raises ``ValueError`` if it cannot be asked for.

    Asking again while one is being made changes nothing, and neither does asking for one
    that exists and is current unless ``force``, so a repeat costs nothing.
    """
    meta = store.meta(doc_id)
    if not eligible(meta):
        raise ValueError("this document cannot be spoken")
    if not valid_minutes(minutes):
        raise ValueError(f"minutes must be one of {list(MINUTES)}")
    current = state_of(store, requests, meta)
    if current["state"] in ACTIVE:
        return current
    if current["state"] == DONE and not current["stale"] and not force:
        return current
    requests.put(
        doc_id,
        {
            "state": QUEUED,
            "force": force,
            "minutes": minutes,
            "version": meta.get("version"),
            "requested": _now(),
        },
    )
    return state_of(store, requests, meta)


#: marks a document made by putting several documents' text in one, for one review of them all
COMBINED_TAG = "combined"
COMBINED_SESSION = "annals combine"
COMBINE_LOCK = ".combine.lock"


def combined_key(docs: Sequence[dict]) -> str:
    """Names a set of documents at their current versions, in any order.

    >>> combined_key([{"id": "b", "version": 2}, {"id": "a"}]) == combined_key([{"id": "a"}, {"id": "b", "version": 2}])
    True
    """
    import hashlib

    parts = sorted(f"{m['id']}@{m.get('version') or 1}" for m in docs)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _members(store, docs: Sequence[dict]) -> list[dict]:
    """``docs`` with each combined document replaced by the documents it combines, once each.

    So a group's "all", which includes a combined document made from it earlier, names the
    same set as before, and nothing is spoken (or paid for) twice.
    """
    out, seen = [], set()

    def add(meta):
        if meta["id"] not in seen and not meta.get("in_trash"):
            seen.add(meta["id"])
            out.append(meta)

    for meta in docs:
        src = meta.get("source") or {}
        if COMBINED_TAG in (meta.get("tags") or []) and isinstance(
            src.get("combines"), list
        ):
            for i in src["combines"]:
                try:
                    add(store.meta(i))
                except (KeyError, ValueError):
                    continue
        else:
            add(meta)
    return out


def _combined_pairs(store, docs: Sequence[dict], *, max_bytes: int | None):
    """``(path, text)`` for each document's speakable text: its page, or a folder's markdown.

    Past ``max_bytes`` of text in all, :class:`annals.aggregate.TooLarge`.
    """
    from annals.aggregate import TooLarge, doc_markdown_files

    total = 0
    for meta in docs:
        if meta.get("kind") == "folder":
            pairs = doc_markdown_files(
                [(meta, meta.get("files", []))], read=store.read_text
            )
        elif eligible(meta):
            label = (meta.get("title") or meta["id"]).replace("/", "-").strip()
            try:
                pairs = [(f"{label}.md", _source_text(store, meta))]
            except (KeyError, OSError, ValueError):
                continue
        else:
            continue
        for path, text in pairs:
            total += len(text.encode("utf-8"))
            if max_bytes is not None and total > max_bytes:
                raise TooLarge(f"more than {max_bytes} bytes of text to combine")
            yield path, text


@contextmanager
def _combine_lock(store):
    """One combination at a time, so two presses never make two documents (and two bills)."""
    import fcntl

    folder = Path(store.target.root) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / COMBINE_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def combined_document(
    store,
    docs: Sequence[dict],
    *,
    title: str,
    group: str | None = None,
    max_bytes: int | None = None,
) -> dict:
    """One document holding the text of ``docs``, so a review of it covers them all.

    A combined document among ``docs`` counts as the documents it combines. The same
    documents at the same versions give the same document back, so asking twice makes one.
    A new one is added to ``group`` when given. Raises ``ValueError`` when none of ``docs``
    has text to speak, or past ``max_bytes`` of text.
    """
    from annals.aggregate import TooLarge, aggregate_markdown

    docs = _members(store, docs)
    key = combined_key(docs)
    with _combine_lock(store):
        for meta in store.list():
            src = meta.get("source") or {}
            if src.get("combines_key") == key and COMBINED_TAG in (
                meta.get("tags") or []
            ):
                return meta
        try:
            pairs = list(_combined_pairs(store, docs, max_bytes=max_bytes))
        except TooLarge as e:
            raise ValueError(str(e)) from None
        if not pairs:
            raise ValueError("none of these documents has text to speak")
        text = aggregate_markdown(pairs, title=title, order=None)
        meta = store.publish(
            text=text,
            title=title,
            filename="combined.md",
            tags=[COMBINED_TAG],
            source={
                "session": COMBINED_SESSION,
                "combines": [m["id"] for m in docs],
                "combines_key": key,
                **({"group": group} if group else {}),
            },
        )
        if group:
            store.add_to_group(group, [meta["id"]])
        return meta


def request_combined(
    store,
    requests: Requests,
    docs: Sequence[dict],
    *,
    title: str,
    group: str | None = None,
    minutes: int = DFLT_MINUTES,
    max_bytes: int | None = None,
) -> dict:
    """Ask for ONE overview of several documents: of the document combining their text.

    Returns ``{"doc": <combined document id>, "listen": <its overview state>}``. Raises
    ``ValueError`` as :func:`request` does, or when there is nothing to speak.
    """
    if not valid_minutes(minutes):
        raise ValueError(f"minutes must be one of {list(MINUTES)}")
    meta = combined_document(store, docs, title=title, group=group)
    return {
        "doc": meta["id"],
        "listen": request(store, requests, meta["id"], minutes=minutes),
    }


#: where a command that answers in JSON (``claude -p --output-format json``) says what went wrong
_REASON_KEYS = ("error", "message", "result")


def _readable(line: str) -> str:
    """The line, with a JSON object at its end replaced by the reason inside it, if it has one.

    A failed ``claude -p`` run surfaces as ``RuntimeError: claude -p exited 1: {...}``, its
    JSON envelope whole, with the reason far into it; cut to the first characters, the reader
    saw only token counts.

    >>> _readable('RuntimeError: claude -p exited 1: {"usage": {}, "is_error": true, "result": "Not logged in"}')
    'RuntimeError: claude -p exited 1: Not logged in'
    >>> _readable("ValueError: no {braces} here")
    'ValueError: no {braces} here'
    """
    at = line.find("{")
    if at < 0:
        return line
    try:
        said = json.loads(line[at:])
    except ValueError:
        return line
    if isinstance(said, dict):
        for key in _REASON_KEYS:
            if isinstance(said.get(key), str) and said[key].strip():
                return (line[:at] + said[key].strip()).strip()
    return line


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return _readable(lines[-1])[:MAX_ERROR_CHARS] if lines else ""


def _source_text(store, meta: dict) -> str:
    text = store.read_text(meta["id"])
    return html_to_text(text) if meta.get("kind") == "html" else text


def _already_made(store, doc_id: str, version) -> str | None:
    """A published overview of this version: what a worker that died after publishing left."""
    for meta in store.list():
        src = meta.get("source") or {}
        if (
            src.get("of") == doc_id
            and src.get("of_version") == version
            and TAG in (meta.get("tags") or [])
        ):
            return meta["id"]
    return None


def _run(argv: Sequence[str], *, cwd: str, timeout: float) -> tuple[int, str]:
    """Run ``argv`` in its own process group; return its exit code and what it last said.

    Output goes to a file, so a daemon left holding the pipe cannot hang this. A timeout stops
    the whole group, because a generator's children are what bill.
    """
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as said:
        proc = subprocess.Popen(
            argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=said, stderr=subprocess.STDOUT,
            start_new_session=True,
        )  # fmt: skip

        def stop(sig):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                pass

        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop(signal.SIGTERM)
            try:
                proc.wait(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                pass
            stop(signal.SIGKILL)
            proc.wait()
            raise RuntimeError(f"gave up after {int(timeout)} seconds") from None
        stop(signal.SIGTERM)  # nothing of a finished run keeps running
        said.seek(0)
        return code, _last_line(said.read())


def _fulfil(
    store,
    doc_id: str,
    *,
    minutes: int,
    command: Sequence[str],
    timeout: float,
    doc_url: Callable[[str], str] = str,
    force: bool = False,
) -> tuple[str, object]:
    """Make the overview and publish it; return the new document's id and the version spoken."""
    meta = store.meta(doc_id)
    if not eligible(meta):
        raise RuntimeError("this document can no longer be spoken")
    version = meta.get("version")
    if not force and (made := _already_made(store, doc_id, version)):
        return made, version
    text = _source_text(store, meta).strip()
    if not text:
        raise RuntimeError("this document has no text to speak")
    with tempfile.TemporaryDirectory(prefix="annals-overview-") as tmp:
        source = Path(tmp) / "source.md"
        title = meta.get("title") or doc_id
        source.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
        out = Path(tmp) / "overview.html"
        fill = {
            "source": str(source),
            "minutes": str(minutes),
            "out": str(out),
            "url": doc_url(doc_id),
        }
        argv = [arg.format(**fill) for arg in command]
        try:
            code, said = _run(argv, cwd=tmp, timeout=timeout)
        except OSError as e:
            raise RuntimeError(
                f"could not run the overview command: {e.strerror}"
            ) from None
        if code:
            raise RuntimeError(said or f"the overview command exited {code}")
        if not out.is_file() or not out.stat().st_size:
            raise RuntimeError("the overview command wrote no page")
        made = store.publish(
            out, title=f"Listen: {title}", tags=[TAG],
            source={"session": "annals overview", "of": doc_id, "of_version": version},
        )  # fmt: skip
    return made["id"], version


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
    """The command as a list of arguments, checked now rather than after money is spent."""
    command = command or os.environ.get(ENV_COMMAND)
    if not command:
        raise ValueError(f"no overview command: pass one, or set {ENV_COMMAND}")
    argv = shlex.split(command) if isinstance(command, str) else list(command)
    probe = {
        "source": "\0source",
        "minutes": "\0minutes",
        "out": "\0out",
        "url": "\0url",
    }
    try:
        filled = " ".join(arg.format(**probe) for arg in argv)
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(f"the overview command has a bad placeholder: {e}") from None
    if probe["source"] not in filled or probe["out"] not in filled:
        raise ValueError("the overview command must name {source} and {out}")
    return argv


def _daily_limit(limit: int | None) -> int:
    if limit is not None:
        return limit
    return int(os.environ.get(ENV_DAILY_LIMIT) or DFLT_DAILY_LIMIT)


def _step(
    store,
    requests: Requests,
    doc_id: str,
    *,
    argv,
    timeout: float,
    limit: int,
    doc_url=str,
) -> dict | None:
    """Take one request as far as it goes; return what happened, or ``None`` if nothing did."""
    record = requests.get(doc_id)
    if not record:
        return None
    state = record.get("state")
    if state not in ACTIVE:
        return None

    def fail(why: str) -> dict:
        why = str(why)[:MAX_ERROR_CHARS]
        requests.put(
            doc_id, {**record, "state": FAILED, "error": why, "finished": _now()}
        )
        return {"doc": doc_id, "state": FAILED, "error": why}

    if (
        state == RUNNING
    ):  # this worker holds the lock, so whoever was running it is gone
        return fail("the worker stopped before finishing")
    if why := _lost(record):
        return fail(why)
    minutes = record.get("minutes")
    if not valid_minutes(minutes):
        return fail(f"not a length on offer: {minutes!r}")
    if requests.started_today() >= limit:
        return fail(f"the limit of {limit} overviews a day was reached")
    requests.note_start(doc_id)
    requests.put(doc_id, {**record, "state": RUNNING, "started": _now()})
    try:
        made, version = _fulfil(
            store,
            doc_id,
            minutes=minutes,
            command=argv,
            timeout=timeout,
            doc_url=doc_url,
            force=record.get("force") is True,
        )
    except Exception as e:  # recorded for the page; the next request must still run
        return fail(e)
    requests.put(
        doc_id,
        {
            **record,
            "state": DONE,
            "overview": made,
            "version": version,
            "finished": _now(),
        },
    )
    return {"doc": doc_id, "state": DONE, "overview": made}


def work(
    store,
    requests: Requests,
    *,
    command: str | Sequence[str] | None = None,
    timeout: float = DFLT_TIMEOUT_S,
    daily_limit: int | None = None,
    doc_url: Callable[[str], str] = str,
) -> list[dict]:
    """Fulfil every queued request, one at a time, until none is left; return what happened.

    A failure is recorded on its request, for the page to show, and the next one still runs.
    A request made while this runs is picked up before it exits. ``doc_url`` turns a document
    id into its page, for ``{url}``.
    """
    argv = _command(command)
    limit = _daily_limit(daily_limit)
    results: list[dict] = []
    seen: set[str] = set()
    with _only_one_worker(requests.folder) as mine:
        if not mine:
            return results
        while fresh := [i for i in requests.ids() if i not in seen]:
            for doc_id in fresh:
                seen.add(doc_id)
                try:
                    happened = _step(
                        store,
                        requests,
                        doc_id,
                        argv=argv,
                        timeout=timeout,
                        limit=limit,
                        doc_url=doc_url,
                    )
                except Exception as e:  # one damaged request must not stop the others
                    happened = {
                        "doc": doc_id,
                        "state": FAILED,
                        "error": str(e)[:MAX_ERROR_CHARS],
                    }
                if happened:
                    results.append(happened)
    return results
