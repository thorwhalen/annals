"""The transport seam: LocalTarget verbs, path safety, and the commands SshTarget sends."""

import json
from types import SimpleNamespace

import pytest

from annals import target as target_mod
from annals.target import LocalTarget, SshTarget, check_rel, parse_target


@pytest.mark.parametrize("rel", ["/etc/passwd", "a/../../b", ".."])
def test_check_rel_refuses_escapes(rel):
    with pytest.raises(ValueError):
        check_rel(rel)


def test_local_target_roundtrip(tmp_path):
    t = LocalTarget(tmp_path / "root")
    src = tmp_path / "src"
    src.mkdir()
    (src / "meta.json").write_text(json.dumps({"id": "d1"}))
    (src / "body.md").write_text("hi")
    t.put_tree(src, "docs/d1")
    assert t.list_dirs("docs") == ["d1"]
    assert t.list_files("docs/d1") == ["body.md", "meta.json"]
    assert t.read_metas("docs") == [{"id": "d1"}]
    t.write_text("docs/d1/note.txt", "n")
    assert t.read_text("docs/d1/note.txt") == "n"
    assert not list((tmp_path / "root" / "docs" / "d1").glob("*.tmp"))
    t.move("docs/d1", "trash/d1")
    assert not t.exists("docs/d1") and t.exists("trash/d1")
    dst = tmp_path / "copy"
    t.get_tree("trash/d1", dst)
    assert (dst / "body.md").read_text() == "hi"
    t.remove_tree("trash/d1")
    assert t.list_dirs("trash") == []


def test_local_target_missing_dirs_list_empty(tmp_path):
    t = LocalTarget(tmp_path)
    assert t.list_dirs("nope") == [] and t.list_files("nope") == []
    assert t.read_metas("nope") == []


def test_local_target_skips_half_written_meta(tmp_path):
    t = LocalTarget(tmp_path)
    (tmp_path / "docs" / "bad").mkdir(parents=True)
    (tmp_path / "docs" / "bad" / "meta.json").write_text("{not json")
    assert t.read_metas("docs") == []


def test_local_target_refuses_symlinked_document_and_escaping_local_path(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "link").symlink_to(outside)
    t = LocalTarget(root)
    with pytest.raises(ValueError, match="symlinked"):
        t.get_tree("docs/link", tmp_path / "dst")
    assert t.local_path("docs/link") is None
    assert t.local_path("docs") == (root / "docs").resolve()


def test_parse_target(tmp_path):
    assert isinstance(parse_target("tw:/srv/annals"), SshTarget)
    assert isinstance(parse_target(tmp_path), LocalTarget)
    assert isinstance(parse_target(str(tmp_path)), LocalTarget)
    assert isinstance(parse_target("relative/dir"), LocalTarget)
    # an existing local directory wins over the host:path reading
    (tmp_path / "x:").mkdir()
    ssh = parse_target("tw:/srv/annals")
    assert (ssh.host, ssh.root) == ("tw", "/srv/annals")


@pytest.fixture
def ssh_calls(monkeypatch):
    """Record every subprocess call; ``ssh`` returns the queued stdout."""
    calls, outputs = [], []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        out = outputs.pop(0) if outputs else ""
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    monkeypatch.setattr(target_mod.subprocess, "run", run)
    return SimpleNamespace(calls=calls, outputs=outputs)


def _script(call):
    cmd, _ = call
    assert cmd[0] == "ssh" and "BatchMode=yes" in cmd
    return cmd[-1]


def test_ssh_verbs_quote_paths(ssh_calls):
    t = SshTarget("tw", "/srv/an nals")
    t.remove_tree("trash/d1")
    assert _script(ssh_calls.calls[-1]) == "rm -rf '/srv/an nals/trash/d1'"
    t.move("docs/a", "trash/a")
    assert "mv '/srv/an nals/docs/a' '/srv/an nals/trash/a'" in _script(
        ssh_calls.calls[-1]
    )
    t.write_text("docs/a/meta.json", "{}")
    cmd, kw = ssh_calls.calls[-1]
    assert kw["input"] == "{}" and ".tmp" in cmd[-1]


def test_ssh_exists_list_and_metas(ssh_calls):
    t = SshTarget("tw", "/srv/a")
    ssh_calls.outputs += ["yes\n", "b\na\n", "x.md\n", '{"id": "1"}\x1e{broken\x1e']
    assert t.exists("docs/a") is True
    assert t.list_dirs("docs") == ["a", "b"]
    assert t.list_files("docs/a") == ["x.md"]
    assert t.read_metas("docs") == [{"id": "1"}]
    assert t.local_path("docs") is None


def test_ssh_failure_raises_with_stderr(monkeypatch):
    monkeypatch.setattr(
        target_mod.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(returncode=255, stdout="", stderr="denied"),
    )
    with pytest.raises(RuntimeError, match="denied"):
        SshTarget("tw", "/srv/a").exists("docs")


def test_ssh_rsync_commands(ssh_calls, tmp_path):
    t = SshTarget("tw", "/srv/a")
    t.put_tree(tmp_path, "docs/d1")
    rsync = ssh_calls.calls[-1][0]
    assert rsync[0] == "rsync" and rsync[-1] == "tw:/srv/a/docs/d1/"
    t.get_tree("docs/d1", tmp_path / "out")
    rsync = ssh_calls.calls[-1][0]
    assert "--no-links" in rsync and rsync[-2] == "tw:/srv/a/docs/d1/"


def test_ssh_rejects_unsafe_rel():
    with pytest.raises(ValueError):
        SshTarget("tw", "/srv/a").remove_tree("../etc")


def test_ssh_home_relative_root_is_expanded_by_the_remote_shell(ssh_calls):
    t = SshTarget("tw", "~/annals data")
    t.remove_tree("docs/d1")
    # quoted, ``~`` would be a literal directory name, unlike rsync's reading of it
    assert _script(ssh_calls.calls[-1]) == "rm -rf ~/'annals data/docs/d1'"
    t.write_text("docs/a.txt", "x")
    script = _script(ssh_calls.calls[-1])
    assert "cat > ~/'annals data/docs/a.txt'.tmp" in script


def test_local_read_text_refuses_a_symlink_leaving_the_root(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cret")
    root = tmp_path / "root"
    (root / "docs" / "d1").mkdir(parents=True)
    (root / "docs" / "d1" / "a.md").symlink_to(secret)
    (root / "docs" / "d1" / "ok.md").write_text("fine")
    t = LocalTarget(root)
    with pytest.raises(ValueError, match="outside"):
        t.read_text("docs/d1/a.md")
    assert t.read_text("docs/d1/ok.md") == "fine"
