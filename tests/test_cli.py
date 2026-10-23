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


def test_share_shares_unshare(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from annals.api import mk_app
    from annals.auth import no_auth
    from annals.store import DocStore

    monkeypatch.setenv("ANNALS_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://example.com/annals/")
    monkeypatch.delenv("ANNALS_SHARE_BASE_URL", raising=False)
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    src = tmp_path / "rep"
    src.mkdir()
    (src / "report.md").write_text("# R\n\n![x](x.png) ![y](y.png)")
    (src / "x.png").write_bytes(b"x")
    (src / "y.png").write_bytes(b"y")
    out = io.StringIO()
    _run(["publish", str(src)], out)
    doc_url = out.getvalue().strip()

    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO("s3cret-pw\n"))
    code = run(
        ["share", doc_url, "--password", "-", "--expires", "7d", "--include", "x.png"],
        out=out,
        err=err,
    )
    assert code == 0, err.getvalue()
    link = out.getvalue().strip()
    assert re.match(r"^https://example\.com/annals/shared/[A-Za-z0-9_-]{22}/$", link)
    assert "password-protected" in err.getvalue() and "2 files" in err.getvalue()
    token = link.rstrip("/").rsplit("/", 1)[1]

    # what the CLI wrote is what the server serves
    client = TestClient(mk_app(store=DocStore(tmp_path / "data"), authorizer=no_auth))
    hdr = {"content-type": "application/x-www-form-urlencoded"}
    client.post(f"/annals/shared/{token}/unlock", content=b"password=s3cret-pw", headers=hdr)
    doc_id = doc_url.rsplit("/", 1)[1]
    assert client.get(f"/annals/shared/{token}/raw/{doc_id}/x.png").status_code == 200
    assert client.get(f"/annals/shared/{token}/raw/{doc_id}/y.png").status_code == 404

    out = io.StringIO()
    _run(["shares"], out)
    listed = json.loads(out.getvalue())["shares"]
    assert [s["id"] for s in listed] == [token] and listed[0]["protected"]

    out = io.StringIO()
    _run(["unshare", link], out)
    assert json.loads(out.getvalue()) == {"revoked": [token]}
    assert client.get(f"/annals/shared/{token}/share").status_code == 404


def test_share_base_url_resolution(tmp_path, monkeypatch):
    monkeypatch.delenv("ANNALS_SHARE_BASE_URL", raising=False)
    cfg = tmp_path / "c.toml"
    s = load_settings(target="/x", base_url="https://h/annals", config_path=cfg)
    assert s.share_base_url == "https://h/annals/shared"
    monkeypatch.setenv("ANNALS_SHARE_BASE_URL", "https://h/api/annals_share/")
    s = load_settings(target="/x", base_url="https://h/annals", config_path=cfg)
    assert s.share_base_url == "https://h/api/annals_share"
    write_config(s, config_path=cfg)
    monkeypatch.delenv("ANNALS_SHARE_BASE_URL")
    assert load_settings(config_path=cfg).share_base_url == "https://h/api/annals_share"


def test_share_refuses_an_outbox(tmp_path, monkeypatch):
    cfg = tmp_path / "c.toml"
    write_config(
        Settings(target=str(tmp_path / "out"), base_url="https://h/annals", outbox=True),
        config_path=cfg,
    )
    monkeypatch.setenv("ANNALS_CONFIG", str(cfg))
    for var in ("ANNALS_TARGET", "ANNALS_BASE_URL", "ANNALS_SHARE_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    out, err = io.StringIO(), io.StringIO()
    assert run(["share", "20260101-000000-x"], out=out, err=err) != 0
    assert "outbox" in err.getvalue() and "Share button" in err.getvalue()
