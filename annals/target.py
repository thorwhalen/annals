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
from pathlib import Path, PurePosixPath
from typing import Protocol

#: Separator between concatenated meta.json files when reading many at once over ssh.
RECORD_SEP = "\x1e"
SSH_OPTS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")
_SSH_TARGET_RE = re.compile(r"^(?P<host>[A-Za-z0-9_.@-]+):(?P<path>[~/].*)$")


class Target(Protocol):
    """What the store needs from wherever the documents live."""

    def describe(self) -> str: ...

    def put_tree(self, src_dir: Path, rel: str) -> None: ...

    def move(self, rel_src: str, rel_dst: str) -> None: ...

    def remove_tree(self, rel: str) -> None: ...

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

    def move(self, rel_src: str, rel_dst: str) -> None:
        src, dst = self._abs(rel_src), self._abs(rel_dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)

    def remove_tree(self, rel: str) -> None:
        shutil.rmtree(self._abs(rel))

    def exists(self, rel: str) -> bool:
        return self._abs(rel).exists()

    def read_text(self, rel: str) -> str:
        return self._abs(rel).read_text(encoding="utf-8")

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
            try:
                metas.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue  # a half-written document is not the reader's problem
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
        self._ssh(f"mkdir -p {shlex.quote(dst)}")
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

    def move(self, rel_src: str, rel_dst: str) -> None:
        src, dst = self._abs(rel_src), self._abs(rel_dst)
        parent = str(PurePosixPath(dst).parent)
        self._ssh(
            f"mkdir -p {shlex.quote(parent)} && mv {shlex.quote(src)} {shlex.quote(dst)}"
        )

    def remove_tree(self, rel: str) -> None:
        self._ssh(f"rm -rf {shlex.quote(self._abs(rel))}")

    def exists(self, rel: str) -> bool:
        out = self._ssh(f"test -e {shlex.quote(self._abs(rel))} && echo yes || echo no")
        return out.strip() == "yes"

    def read_text(self, rel: str) -> str:
        return self._ssh(f"cat {shlex.quote(self._abs(rel))}")

    def write_text(self, rel: str, text: str) -> None:
        path = self._abs(rel)
        parent = str(PurePosixPath(path).parent)
        q = shlex.quote(path)
        self._ssh(
            f"mkdir -p {shlex.quote(parent)} && cat > {q}.tmp && mv {q}.tmp {q}",
            stdin=text,
        )

    def list_dirs(self, rel: str) -> list[str]:
        base = shlex.quote(self._abs(rel))
        out = self._ssh(f"[ -d {base} ] && ls -1 {base} || true")
        return sorted(name for name in out.splitlines() if name)

    def list_files(self, rel: str) -> list[str]:
        base = shlex.quote(self._abs(rel))
        out = self._ssh(
            f"[ -d {base} ] && ls -1p {base} | grep -v / || true"
        )  # portable (no GNU find)
        return sorted(name for name in out.splitlines() if name)

    def local_path(self, rel: str) -> Path | None:
        return None  # remote: nothing to stream from this machine's disk

    def read_metas(self, rel: str) -> list[dict]:
        base = shlex.quote(self._abs(rel))
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
