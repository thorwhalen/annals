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
    assert (
        _run(["publish", str(src), "--tags", "a,b", "--session", "test-session"], out)
        == 0
    )
    url = out.getvalue().strip()
    assert re.match(
        r"^https://example\.com/annals/d/\d{8}-\d{6}-my-report-[0-9a-f]{4}$", url
    )
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
    write_config(
        Settings(
            target="tw:/root/.local/share/annals",
            base_url="https://apps.example.com/annals/",
        )
    )
    s = load_settings()
    assert (
        s.target == "tw:/root/.local/share/annals"
        and s.base_url == "https://apps.example.com/annals"
    )
    monkeypatch.setenv("ANNALS_TARGET", "/elsewhere")
    assert load_settings().target == "/elsewhere"
    assert load_settings(target="/arg").target == "/arg"


def test_configure_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNALS_CONFIG", str(tmp_path / "c.toml"))
    monkeypatch.delenv("ANNALS_TARGET", raising=False)
    out = io.StringIO()
    _run(
        ["configure", "--target", "host:/srv/annals", "--base-url", "https://h/annals"],
        out,
    )
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
    assert (
        run(["publish", str(tmp_path / "c.md"), "--add-to", gid, "--group", "X"]) == 1
    )


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
    client.post(
        f"/annals/shared/{token}/unlock", content=b"password=s3cret-pw", headers=hdr
    )
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
        Settings(
            target=str(tmp_path / "out"), base_url="https://h/annals", outbox=True
        ),
        config_path=cfg,
    )
    monkeypatch.setenv("ANNALS_CONFIG", str(cfg))
    for var in ("ANNALS_TARGET", "ANNALS_BASE_URL", "ANNALS_SHARE_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    out, err = io.StringIO(), io.StringIO()
    assert run(["share", "20260101-000000-x"], out=out, err=err) != 0
    assert "outbox" in err.getvalue() and "Share button" in err.getvalue()


def _local(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNALS_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://example.com/annals/")
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from annals.store import DocStore

    return DocStore(tmp_path / "data")


def test_an_agent_reads_a_private_link_it_was_handed(tmp_path, monkeypatch):
    """No share link needed: show and aggregate take the page's address as copied (2026-11-09)."""
    store = _local(tmp_path, monkeypatch)
    a = store.publish(text="# Bees\n\nhives", title="Bees", filename="bees.md")
    g = store.make_group("Nature", [a["id"]])
    base = "https://example.com/annals"
    out = io.StringIO()
    assert _run(["show", f"{base}/d/{a['id']}?f=bees.md#top"], out) == 0
    shown = json.loads(out.getvalue())
    assert shown["id"] == a["id"]
    assert shown["groups"][0]["url"] == f"{base}/g/{g['id']}"
    out = io.StringIO()
    assert _run(["show", f"{base}/g/{g['id']}"], out) == 0
    assert json.loads(out.getvalue())["doc_urls"] == [f"{base}/d/{a['id']}"]
    out = io.StringIO()
    assert _run(["aggregate", f"{base}/g/{g['id']}/"], out) == 0
    assert "hives" in out.getvalue()


def test_reading_refuses_an_outbox(tmp_path, monkeypatch):
    cfg = tmp_path / "c.toml"
    write_config(
        Settings(
            target=str(tmp_path / "out"), base_url="https://h/annals", outbox=True
        ),
        config_path=cfg,
    )
    monkeypatch.setenv("ANNALS_CONFIG", str(cfg))
    for var in ("ANNALS_TARGET", "ANNALS_BASE_URL", "ANNALS_SHARE_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    for cmd in ("show", "aggregate"):
        out, err = io.StringIO(), io.StringIO()
        assert run([cmd, "20260101-000000-x"], out=out, err=err) != 0
        assert "outbox" in err.getvalue()


def test_an_audio_file_takes_its_timed_text_along_as_one_document(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ANNALS_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://example.com/annals")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    names = (
        "talk.chapters.vtt",
        "talk.mp3",
        "notes.md",
        "talk.vtt",
    )  # as a shell glob lists them
    for name in names:
        (tmp_path / name).write_text("# Notes" if name.endswith(".md") else "x")
    out = io.StringIO()
    assert _run(["publish", *(str(tmp_path / n) for n in names)], out) == 0
    ids = [d["id"] for d in json.loads(out.getvalue())["docs"]]
    assert len(ids) == 2, "the audio with its transcript and chapters, and the notes"
    out = io.StringIO()
    _run(["show", ids[0]], out)
    shown = json.loads(out.getvalue())
    assert shown["kind"] == "audio" and shown["main"] == "talk.mp3"
    assert sorted(shown["files"]) == ["talk.chapters.vtt", "talk.mp3", "talk.vtt"]


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNALS_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://example.com/annals/")
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))


def _json(argv):
    out = io.StringIO()
    assert _run(argv, out) == 0
    return json.loads(out.getvalue())


def test_publish_json_is_the_contract_and_meta_lands_in_source(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    src = tmp_path / "r.md"
    src.write_text("# R\n\nbody")
    res = _json(
        [
            "publish",
            str(src),
            "--json",
            "--meta",
            "corpus=annals",
            "--meta",
            "issue=64",
            "--group",
            "G",
        ]
    )
    assert set(res) == {"id", "title", "url", "group_id", "group_url"}
    got = _json(["show", res["id"]])
    assert got["source"]["corpus"] == "annals" and got["source"]["issue"] == "64"


def test_publish_json_with_a_warning_keeps_stdout_pure(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    src = tmp_path / "r.md"
    src.write_text("# R\n\nFixed in #4.")
    out, err = io.StringIO(), io.StringIO()
    assert run(["publish", str(src), "--json"], out=out, err=err) == 0
    assert "url" in json.loads(out.getvalue()) and "warning" in err.getvalue()


def test_ls_filters_are_exact(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    for name, session, tags in [("a", "sess-1", "x"), ("b", "sess-10", "xy")]:
        f = tmp_path / f"{name}.md"
        f.write_text(f"# {name}\n\nbody")
        _json(
            [
                "publish",
                str(f),
                "--json",
                "--session",
                session,
                "--tags",
                tags,
                "--meta",
                f"kind={name}",
            ]
        )
    assert [d["title"] for d in _json(["ls", "--session", "sess-1"])["docs"]] == ["a"]
    assert [d["title"] for d in _json(["ls", "--tag", "x"])["docs"]] == ["a"]
    assert [d["title"] for d in _json(["ls", "--meta", "kind=b"])["docs"]] == ["b"]
    assert _json(["ls", "--since", "1h"])["total"] == 2
    assert _json(["ls", "--since", "2999-01-01"])["total"] == 0
    row = _json(["ls", "--session", "sess-10"])["docs"][0]
    assert set(row) == {
        "id",
        "title",
        "kind",
        "tags",
        "created",
        "updated",
        "source",
        "url",
    }
    assert row["source"]["session"] == "sess-10" and row["source"]["kind"] == "b"


def test_meta_repeats_and_a_path_may_follow_it(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    src = tmp_path / "r.md"
    src.write_text("# R\n\nbody")
    res = _json(
        ["publish", "--meta", "corpus=c", "--meta", "item=i7", str(src), "--json"]
    )
    src_meta = _json(["show", res["id"]])["source"]
    assert (src_meta["corpus"], src_meta["item"]) == ("c", "i7")


def test_meta_cannot_overwrite_recorded_provenance(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    src = tmp_path / "r.md"
    src.write_text("# R\n\nbody")
    err = io.StringIO()
    assert (
        run(["publish", str(src), "--meta", "host=x"], out=io.StringIO(), err=err) == 1
    )
    assert "cannot set 'host'" in err.getvalue()


def test_several_paths_give_docs_and_bare_links_stay_the_default(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("# A\n\nx")
    b.write_text("# B\n\ny")
    res = _json(["publish", str(a), str(b), "--json"])
    assert [set(d) for d in res["docs"]] == [{"id", "title", "url"}] * 2
    out = io.StringIO()
    _run(["publish", str(a)], out)
    assert out.getvalue().startswith("https://example.com/annals/d/")


def test_since_follows_a_replaced_document(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    src = tmp_path / "r.md"
    src.write_text("# R\n\nv1")
    first = _json(["publish", str(src), "--json"])
    src.write_text("# R\n\nv2")
    _json(["publish", str(src), "--replace", first["id"], "--json"])
    row = _json(["ls"])["docs"][0]
    assert row["updated"] and row["updated"] >= row["created"]
    assert _json(["ls", "--since", "1h"])["total"] >= 1
    err = io.StringIO()
    assert run(["ls", "--since", "yesterday-ish"], out=io.StringIO(), err=err) == 1


def test_every_operation_is_classified_and_mcp_serves_by_effect():
    from annals import mcp, tools

    names = {f.__name__ for f in tools._dispatch_funcs}
    assert set(tools.EFFECTS) == names  # a new verb must be classified
    served = {r.split(":")[1] for r in mcp._refs()}
    assert served == {n for n in names if tools.EFFECTS[n] in {"read", "write"}}
    assert not served & {
        "purge",
        "listen",
        "listen_down",
        "serve",
        "page_shell",
        "aggregate",
    }
    assert {"copy", "tag", "ls"} <= served  # what only the CLI had before
    assert "purge" in {r.split(":")[1] for r in mcp._refs({"read", "destructive"})}


def test_the_mcp_server_builds_with_the_default_and_a_wider_set(monkeypatch):
    import pytest

    pytest.importorskip("py2mcp")
    from annals import mcp

    assert mcp.mk_server() is not None
    monkeypatch.setenv(mcp.ENV_EFFECTS, "read,write,destructive,spend")
    assert mcp.mk_server() is not None


def test_tag_then_purge_from_the_command_line(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    src = tmp_path / "r.md"
    src.write_text("# R\n\nbody")
    doc = _json(["publish", str(src), "--json"])["id"]
    assert _json(["tag", doc, "a,b"]) == {"id": doc, "tags": ["a", "b"]}
    assert _json(["show", doc])["tags"] == [
        "a",
        "b",
    ]  # the owner's tags are what every read verb shows
    assert [d["id"] for d in _json(["ls", "--tag", "a"])["docs"]] == [doc]
    assert _json(["ls", "--tag", "gone"])["total"] == 0
    err = io.StringIO()
    assert (
        run(["purge", doc], out=io.StringIO(), err=err) == 1
        and "not in the trash" in err.getvalue()
    )
    other = tmp_path / "o.md"
    other.write_text("# O\n\nx")
    keep = _json(["publish", str(other), "--json"])["id"]
    _json(["trash", doc])
    err = io.StringIO()  # one id not in the bin: nothing is deleted
    assert (
        run(["purge", doc, keep], out=io.StringIO(), err=err) == 1
        and keep in err.getvalue()
    )
    assert _json(["ls", "--trash"])["total"] == 1
    assert _json(["purge", doc]) == {"purged": [doc]}
    assert _json(["ls", "--trash"])["total"] == 0


def test_ls_may_filter_on_recorded_provenance_and_refuses_a_session_conflict(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    src = tmp_path / "r.md"
    src.write_text("# R\n\nbody")
    _json(["publish", str(src), "--json", "--session", "s1"])
    assert _json(["ls", "--meta", "session=s1"])["total"] == 1
    err = io.StringIO()
    assert run(["ls", "--meta", "session=a", "--session", "b"], out=io.StringIO(), err=err) == 1
    assert "twice" in err.getvalue()


def test_references_from_the_command_line_match_the_page(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("# A\n\nBody.\n\n## References\n\n[1] Foo. https://example.com/foo\n")
    b.write_text("# B\n\nNo references here.\n")
    ids = [_json(["publish", str(p), "--json"])["id"] for p in (a, b)]
    group = _json(["publish", str(a), "--json", "--group", "G"])["group_id"]
    out = io.StringIO()
    assert _run(["references", ids[0], "--form", "urls"], out) == 0
    assert out.getvalue().strip() == "https://example.com/foo"
    out = io.StringIO()
    assert _run(["references", group], out) == 0 and "References for G" in out.getvalue()
    err = io.StringIO()
    assert run(["references", ids[1]], out=io.StringIO(), err=err) == 1 and "no references" in err.getvalue()


def test_listen_takes_several_documents_for_one_overview(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    ids = []
    for name in ("a", "b"):
        f = tmp_path / f"{name}.md"
        f.write_text(f"# {name}\n\nSome text about {name}.")
        ids.append(_json(["publish", str(f), "--json"])["id"])
    res = _json(["listen", ids[0], "--also", ids[1]])
    assert res["doc"] is None  # the combined document is made when the worker starts the job
    assert res["listen"]["state"] in {"queued", "waiting"}
    err = io.StringIO()
    assert run(["listen", ids[0], "--also", "nope-nope"], out=io.StringIO(), err=err) == 1


def test_listen_also_edge_cases_and_the_state_poll(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    ids = []
    for name in ("a", "b", "c"):
        f = tmp_path / f"{name}.md"
        f.write_text(f"# {name}\n\nSome text about {name}.")
        ids.append(_json(["publish", str(f), "--json"])["id"])
    one = _json(["listen", ids[0], "--also", ids[0]])  # the same document twice: the ordinary overview
    assert _json(["overview-state", ids[0]])["state"] == one["state"]
    err = io.StringIO()
    assert run(["listen", ids[0], "--also", ids[1], "--force"], out=io.StringIO(), err=err) == 1 and "--force" in err.getvalue()
    _json(["trash", ids[2]])
    err = io.StringIO()
    assert run(["listen", ids[0], "--also", ids[2]], out=io.StringIO(), err=err) == 1 and ids[2] in err.getvalue()


def test_references_of_several_documents_and_unknown_refs(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("# A\n\nx\n\n## References\n\n[1] One. https://example.com/one\n")
    b.write_text("# B\n\ny\n\n## References\n\n[1] Two. https://example.com/two\n")
    ia, ib = [_json(["publish", str(p), "--json"])["id"] for p in (a, b)]
    out = io.StringIO()
    assert _run(["references", ia, "--also", ib, "--form", "urls"], out) == 0
    assert out.getvalue().split() == ["https://example.com/one", "https://example.com/two"]
    err = io.StringIO()
    assert run(["references", "nope-nope"], out=io.StringIO(), err=err) == 1 and "no such document or group" in err.getvalue()


def test_export_a_markdown_file_and_what_a_share_can_offer(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    f = tmp_path / "r.md"
    f.write_text("# Report\n\nSee [other](https://x.example/y).\n")
    doc = _json(["publish", str(f), "--json"])["id"]
    out = io.StringIO()
    assert _run(["export", doc, "--format", "md"], out) == 0 and "# Report" in out.getvalue()
    dst = tmp_path / "out.md"
    assert _json(["export", doc, "--format", "md", "--output", str(dst)])["bytes"] > 0 and dst.exists()
    err = io.StringIO()
    assert run(["export", doc], out=io.StringIO(), err=err) == 1 and "--output" in err.getvalue()
    res = _json(["shareable", doc])
    assert res["main"] == "r.md" and [x["rel"] for x in res["files"]] == ["r.md"]


def test_export_makes_a_pdf_when_the_extra_is_installed(tmp_path, monkeypatch):
    import pytest

    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as e:  # not installed, or its system library is missing
        pytest.skip(str(e)[:80])
    _env(tmp_path, monkeypatch)
    f = tmp_path / "r.md"
    f.write_text("# Report\n\nbody\n")
    doc = _json(["publish", str(f), "--json"])["id"]
    dst = tmp_path / "r.pdf"
    try:
        _json(["export", doc, "--output", str(dst)])
    except OSError as e:  # the system library behind it is missing on this machine
        pytest.skip(str(e))
    assert dst.read_bytes().startswith(b"%PDF")
