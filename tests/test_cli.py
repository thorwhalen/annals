"""The CLI prints a link; settings resolve from env and the config file."""

import io
import json
import re

from annals.__main__ import run
from annals.config import load_settings, write_config, Settings


def _run(argv, out):
    return run(argv, out=out, err=io.StringIO())


def test_publish_prints_url_then_ls_and_trash(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNALS_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://example.com/annals/")
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    src = tmp_path / "r.md"
    src.write_text("# My report\n\nbody")

    out = io.StringIO()
    assert _run(["publish", str(src), "--tags", "a,b", "--session", "test-session"], out) == 0
    url = out.getvalue().strip()
    assert re.match(r"^https://example\.com/annals/d/\d{8}-\d{6}-my-report-[0-9a-f]{4}$", url)
    doc_id = url.rsplit("/", 1)[1]

    out = io.StringIO()
    _run(["ls"], out)
    listed = json.loads(out.getvalue())
    assert listed["total"] == 1 and listed["docs"][0]["tags"] == ["a", "b"]

    out = io.StringIO()
    _run(["show", doc_id], out)
    assert json.loads(out.getvalue())["source"]["session"] == "test-session"

    out = io.StringIO()
    _run(["trash", doc_id], out)
    assert json.loads(out.getvalue()) == {"trashed": [doc_id]}
    out = io.StringIO()
    _run(["ls", "--trash"], out)
    assert json.loads(out.getvalue())["total"] == 1
    out = io.StringIO()
    _run(["restore", doc_id], out)
    assert json.loads(out.getvalue()) == {"restored": [doc_id]}


def test_publish_many_with_group_prints_group_url_first(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNALS_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://example.com/annals")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    a, b = tmp_path / "a.md", tmp_path / "b.html"
    a.write_text("# A")
    b.write_text("<title>B</title>")
    out = io.StringIO()
    assert _run(["publish", str(a), str(b), "--group", "Pair"], out) == 0
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("https://example.com/annals/g/")
    assert len(lines) == 3 and all("/annals/d/" in line for line in lines[1:])
    out = io.StringIO()
    _run(["groups"], out)
    assert json.loads(out.getvalue())["groups"][0]["n"] == 2


def test_settings_precedence(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    monkeypatch.setenv("ANNALS_CONFIG", str(cfg))
    monkeypatch.delenv("ANNALS_TARGET", raising=False)
    monkeypatch.delenv("ANNALS_BASE_URL", raising=False)
    s = load_settings()
    assert s.base_url == "http://127.0.0.1:8765/annals"
    write_config(Settings(target="tw:/root/.local/share/annals", base_url="https://apps.example.com/annals/"))
    s = load_settings()
    assert s.target == "tw:/root/.local/share/annals" and s.base_url == "https://apps.example.com/annals"
    monkeypatch.setenv("ANNALS_TARGET", "/elsewhere")
    assert load_settings().target == "/elsewhere"
    assert load_settings(target="/arg").target == "/arg"


def test_configure_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNALS_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.delenv("ANNALS_TARGET", raising=False)
    out = io.StringIO()
    _run(["configure", "--target", "host:/srv/annals", "--base-url", "https://h/annals"], out)
    got = json.loads(out.getvalue())
    assert got["target"] == "host:/srv/annals" and (tmp_path / "c.toml").exists()


def test_bad_usage_exits_nonzero():
    assert _run(["publish"], io.StringIO()) != 0


def test_unconfigured_publish_warns_on_stderr(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANNALS_TARGET", raising=False)
    monkeypatch.setenv("ANNALS_CONFIG", str(tmp_path / "none.toml"))
    monkeypatch.setenv("ANNALS_DATA_DIR", str(tmp_path / "local"))
    (tmp_path / "r.md").write_text("# R")
    assert run(["publish", str(tmp_path / "r.md")]) == 0
    out, err = capsys.readouterr()
    assert out.strip().startswith("http://127.0.0.1") and "no annals config" in err


def test_add_to_appends_to_an_existing_group(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANNALS_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://x/annals")
    for n in "abc":
        (tmp_path / f"{n}.md").write_text(f"# {n}")
    run(["publish", str(tmp_path / "a.md"), str(tmp_path / "b.md"), "--group", "Batch"])
    gid = capsys.readouterr().out.splitlines()[0].rsplit("/", 1)[-1]
    assert run(["publish", str(tmp_path / "c.md"), "--add-to", gid]) == 0
    out = capsys.readouterr().out
    assert gid in out
    from annals.store import DocStore
    assert len(DocStore(tmp_path / "data").group(gid)["docs"]) == 3
    assert len(DocStore(tmp_path / "data").list_groups()) == 1
    assert run(["publish", str(tmp_path / "c.md"), "--add-to", gid, "--group", "X"]) == 1
