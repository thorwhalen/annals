"""The CLI prints a link; settings resolve from env and the config file."""

import io
import json
import re

from intray.__main__ import run
from intray.config import load_settings, write_config, Settings


def _run(argv, out):
    return run(argv, out=out, err=io.StringIO())


def test_publish_prints_url_then_ls_and_trash(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAY_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("TRAY_BASE_URL", "https://example.com/tray/")
    monkeypatch.delenv("TRAY_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    src = tmp_path / "r.md"
    src.write_text("# My report\n\nbody")

    out = io.StringIO()
    assert _run(["publish", str(src), "--tags", "a,b", "--session", "test-session"], out) == 0
    url = out.getvalue().strip()
    assert re.match(r"^https://example\.com/tray/d/\d{8}-\d{6}-my-report-[0-9a-f]{4}$", url)
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
    monkeypatch.setenv("TRAY_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("TRAY_BASE_URL", "https://example.com/tray")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    a, b = tmp_path / "a.md", tmp_path / "b.html"
    a.write_text("# A")
    b.write_text("<title>B</title>")
    out = io.StringIO()
    assert _run(["publish", str(a), str(b), "--group", "Pair"], out) == 0
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("https://example.com/tray/g/")
    assert len(lines) == 3 and all("/tray/d/" in line for line in lines[1:])
    out = io.StringIO()
    _run(["groups"], out)
    assert json.loads(out.getvalue())["groups"][0]["n"] == 2


def test_settings_precedence(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    monkeypatch.setenv("TRAY_CONFIG", str(cfg))
    monkeypatch.delenv("TRAY_TARGET", raising=False)
    monkeypatch.delenv("TRAY_BASE_URL", raising=False)
    s = load_settings()
    assert s.base_url == "http://127.0.0.1:8765/tray"
    write_config(Settings(target="tw:/root/.local/share/tray", base_url="https://apps.example.com/tray/"))
    s = load_settings()
    assert s.target == "tw:/root/.local/share/tray" and s.base_url == "https://apps.example.com/tray"
    monkeypatch.setenv("TRAY_TARGET", "/elsewhere")
    assert load_settings().target == "/elsewhere"
    assert load_settings(target="/arg").target == "/arg"


def test_configure_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAY_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.delenv("TRAY_TARGET", raising=False)
    out = io.StringIO()
    _run(["configure", "--target", "host:/srv/tray", "--base-url", "https://h/tray"], out)
    got = json.loads(out.getvalue())
    assert got["target"] == "host:/srv/tray" and (tmp_path / "c.toml").exists()


def test_bad_usage_exits_nonzero():
    assert _run(["publish"], io.StringIO()) != 0
