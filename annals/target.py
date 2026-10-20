"""The transport seam: a document tree lands in a directory, here or on another machine.

A ``Target`` is the handful of filesystem verbs the store needs (put a directory, move,
remove, read and write a text file, list sub-directories, read every ``meta.json`` under a
directory). Two implementations:

* :class:`LocalTarget`: a directory on this machine, plain ``pathlib``/``shutil``.
* :class:`SshTarget`: ``host:path`` on another machine, through the system ``ssh`` and
  ``rsync`` in batch mode (no prompts, so an agent never hangs). The host is whatever the
  user's ``~/.ssh/config`` resolves, so an alias such as ``tw`` works.

:func:`parse_target` picks one from a string. An HTTP target (a bearer-token ingest
endpoint) is the declared replacement for the ssh one and is not built yet.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol

#: Separator between concatenated meta.json files when reading many at once over ssh.
RECORD_SEP = "\x1e"
#: the note a lock directory is created with (see :meth:`Target.make_lock`)
LOCK_NOTE = "lock.json"
SSH_OPTS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")
_SSH_TARGET_RE = re.compile(r"^(?P<host>[A-Za-z0-9][A-Za-z0-9_.@-]*):(?P<path>[~/].*)$")


def _q(path: str) -> str:
    """``shlex.quote`` for a remote shell, leaving a leading ``~/`` for the shell to expand.

    Quoted, ``~`` is a literal directory name; rsync expands it remotely, so the
    two transports would otherwise disagree about where ``host:~/x`` is. Only the
    current user's ``~/`` is supported: ``~user/x`` stays literal on the ssh side.
    """
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    return shlex.quote(path)


class Target(Protocol):
    """What the store needs from wherever the documents live."""

    def describe(self) -> str: ...

    def put_tree(self, src_dir: Path, rel: str) -> None: ...

    def get_tree(self, rel: str, dst_dir: Path) -> None: ...

    def move(self, rel_src: str, rel_dst: str) -> None:
        """Rename; fails when the source is gone or the destination already exists."""
        ...

    def remove_tree(self, rel: str) -> None: ...

    def make_lock(self, rel: str, note: str) -> None:
        """Create directory ``rel`` holding ``lock.json`` (``note``) as one step; fail if
        it exists. An atomic test-and-set: a lock that is never seen without its note."""
        ...

    def file_sizes(self, rel: str, files: list[str]) -> dict[str, int]:
        """The byte size of each of ``files`` under ``rel`` that is a regular file."""
        ...

    def exists(self, rel: str) -> bool: ...

    def read_text(self, rel: str) -> str: ...

    def write_text(self, rel: str, text: str) -> None: ...

    def list_dirs(self, rel: str) -> list[str]: ...

    def read_metas(self, rel: str) -> list[dict]: ...

    def list_files(self, rel: str) -> list[str]: ...

    def local_path(self, rel: str) -> Path | None:
        """The file on this machine's disk, when the documents are local (to stream it)."""
        ...


def check_rel(rel: str) -> str:
    """Refuse anything that could escape the root; the store only ever passes safe paths."""
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"unsafe relative path: {rel!r}")
    return str(p)


class LocalTarget:
    """A directory on this machine."""

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()

    def describe(self) -> str:
        return str(self.root)

    def _abs(self, rel: str) -> Path:
        return self.root / check_rel(rel)

    def put_tree(self, src_dir: Path, rel: str) -> None:
        dst = self._abs(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_dir, dst)

    def get_tree(self, rel: str, dst_dir: Path) -> None:
        src = self._abs(rel)
        if src.is_symlink():
            raise ValueError(f"refusing to read a symlinked document: {rel}")
        shutil.copytree(src, dst_dir, symlinks=True, dirs_exist_ok=True)

    def move(self, rel_src: str, rel_dst: str) -> None:
        src, dst = self._abs(rel_src), self._abs(rel_dst)
        if dst.exists():
            raise FileExistsError(rel_dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dst)

    def remove_tree(self, rel: str) -> None:
        shutil.rmtree(self._abs(rel))

    def make_lock(self, rel: str, note: str) -> None:
        path = self._abs(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        prep = Path(tempfile.mkdtemp(prefix=".lockprep-", dir=path.parent))
        (prep / LOCK_NOTE).write_text(note, encoding="utf-8")
        try:  # a rename onto a lock (never empty) fails: only one taker wins
            os.rename(prep, path)
        except OSError:
            shutil.rmtree(prep, ignore_errors=True)
            raise

    def file_sizes(self, rel: str, files: list[str]) -> dict[str, int]:
        base = self._abs(rel)
        out = {}
        for f in files:
            path = base / check_rel(f)
            if path.is_file() and not path.is_symlink():
                out[f] = path.stat().st_size
        return out

    def exists(self, rel: str) -> bool:
        return self._abs(rel).exists()

    def read_text(self, rel: str) -> str:
        path = self.local_path(rel)
        if path is None:  # a symlink pointing out of the root
            raise ValueError(f"refusing to read outside the root: {rel}")
        return path.read_text(encoding="utf-8")

    def write_text(self, rel: str, text: str) -> None:
        path = self._abs(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def list_dirs(self, rel: str) -> list[str]:
        base = self._abs(rel)
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if p.is_dir())

    def list_files(self, rel: str) -> list[str]:
        base = self._abs(rel)
        return (
            sorted(p.name for p in base.iterdir() if p.is_file())
            if base.is_dir()
            else []
        )

    def local_path(self, rel: str) -> Path | None:
        """``rel`` under the root, resolved; ``None`` if it escapes the root (a symlink)."""
        path = self._abs(rel).resolve()
        return path if path.is_relative_to(self.root.resolve()) else None

    def read_metas(self, rel: str) -> list[dict]:
        base = self._abs(rel)
        if not base.is_dir():
            return []
        metas = []
        for meta_path in base.glob("*/meta.json"):
            if meta_path.parent.name.startswith("."):
                continue  # work in progress (a replacement being applied), like ssh's glob
            try:
                metas.append(
                    json.loads(
                        self.read_text(f"{rel}/{meta_path.parent.name}/meta.json")
                    )
                )
            except (OSError, ValueError):
                continue  # half-written, or a symlink out of the root: not the reader's problem
        return metas


class SshTarget:
    """``host:path`` on another machine, via the system ssh and rsync in batch mode."""

    def __init__(self, host: str, root: str):
        self.host = host
        self.root = root.rstrip("/") or "/"

    def describe(self) -> str:
        return f"{self.host}:{self.root}"

    def _abs(self, rel: str) -> str:
        return f"{self.root}/{check_rel(rel)}"

    def _ssh(self, script: str, *, stdin: str | None = None) -> str:
        cmd = ["ssh", *SSH_OPTS, self.host, script]
        proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ssh {self.host} failed ({proc.returncode}): {proc.stderr.strip()[:500]}"
            )
        return proc.stdout

    def put_tree(self, src_dir: Path, rel: str) -> None:
        dst = self._abs(rel)
        self._ssh(f"mkdir -p {_q(dst)}")
        cmd = [
            "rsync",
            "-a",
            "--delete",
            "-e",
            "ssh " + " ".join(SSH_OPTS),
            f"{src_dir}/",
            f"{self.host}:{dst}/",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"rsync to {self.host} failed: {proc.stderr.strip()[:500]}"
            )

    def get_tree(self, rel: str, dst_dir: Path) -> None:
        dst_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "rsync",
            "-a",
            "--no-links",
            "-e",
            "ssh " + " ".join(SSH_OPTS),
            f"{self.host}:{self._abs(rel)}/",
            f"{dst_dir}/",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"rsync from {self.host} failed: {proc.stderr.strip()[:500]}"
            )

    def move(self, rel_src: str, rel_dst: str) -> None:
        src, dst = self._abs(rel_src), self._abs(rel_dst)
        parent = str(PurePosixPath(dst).parent)
        self._ssh(
            f"[ ! -e {_q(dst)} ] && mkdir -p {_q(parent)} && mv {_q(src)} {_q(dst)}"
        )

    def remove_tree(self, rel: str) -> None:
        self._ssh(f"rm -rf {_q(self._abs(rel))}")

    def make_lock(self, rel: str, note: str) -> None:
        path = self._abs(rel)
        parent = _q(str(PurePosixPath(path).parent))
        self._ssh(  # one remote shell: the note follows the mkdir within a millisecond
            f"mkdir -p {parent} && mkdir {_q(path)} && cat > {_q(path + '/' + LOCK_NOTE)}",
            stdin=note,
        )

    def file_sizes(self, rel: str, files: list[str]) -> dict[str, int]:
        if not files:
            return {}
        base = self._abs(rel)
        paths = " ".join(_q(f"{base}/{check_rel(f)}") for f in files)
        out = self._ssh(
            f'for f in {paths}; do if [ -f "$f" ] && [ ! -L "$f" ]; then wc -c < "$f"; '
            f"else echo -1; fi; done"
        )  # one line per file, in order: no file name is parsed back
        sizes = [int(x) for x in out.split()]
        return {f: n for f, n in zip(files, sizes) if n >= 0}

    def exists(self, rel: str) -> bool:
        out = self._ssh(f"test -e {_q(self._abs(rel))} && echo yes || echo no")
        return out.strip() == "yes"

    def read_text(self, rel: str) -> str:
        return self._ssh(f"cat {_q(self._abs(rel))}")

    def write_text(self, rel: str, text: str) -> None:
        path = self._abs(rel)
        parent = str(PurePosixPath(path).parent)
        q = _q(path)
        self._ssh(
            f"mkdir -p {_q(parent)} && cat > {q}.tmp && mv {q}.tmp {q}",
            stdin=text,
        )

    def list_dirs(self, rel: str) -> list[str]:
        base = _q(self._abs(rel))
        out = self._ssh(f"[ -d {base} ] && ls -1A {base} || true")  # as local: hidden too
        return sorted(name for name in out.splitlines() if name)

    def list_files(self, rel: str) -> list[str]:
        base = _q(self._abs(rel))
        out = self._ssh(
            f"[ -d {base} ] && ls -1p {base} | grep -v / || true"
        )  # portable (no GNU find)
        return sorted(name for name in out.splitlines() if name)

    def local_path(self, rel: str) -> Path | None:
        return None  # remote: nothing to stream from this machine's disk

    def read_metas(self, rel: str) -> list[dict]:
        base = _q(self._abs(rel))
        script = (
            f"[ -d {base} ] || exit 0; for f in {base}/*/meta.json; do "
            f'[ -f "$f" ] && cat "$f" && printf "{RECORD_SEP}"; done; true'
        )
        out = self._ssh(script)
        metas = []
        for chunk in out.split(RECORD_SEP):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                metas.append(json.loads(chunk))
            except json.JSONDecodeError:
                continue
        return metas


def parse_target(spec: str | Path) -> Target:
    """``host:/path`` becomes an :class:`SshTarget`; anything else a :class:`LocalTarget`."""
    if isinstance(spec, Path):
        return LocalTarget(spec)
    m = _SSH_TARGET_RE.match(spec)
    if m and not Path(spec).exists():
        return SshTarget(m.group("host"), m.group("path"))
    return LocalTarget(spec)
