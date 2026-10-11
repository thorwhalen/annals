"""Named targets (``--to``) and ``copy``: opt-in second destination, same ids, no hardcoded host."""

import io
import json

import pytest

from annals.__main__ import run
from annals.config import load_settings, named_targets, write_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ANNALS_TARGET", raising=False)
    monkeypatch.delenv("ANNALS_BASE_URL", raising=False)
    monkeypatch.setenv("ANNALS_CONFIG", str(tmp_path / "cfg" / "config.toml"))
    return tmp_path


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = run(argv, out=out, err=err)
    return code, out.getvalue().strip(), err.getvalue()


def _setup(env):
    main, other = env / "main", env / "other"
    assert (
        _run(
            ["configure", "--target", str(main), "--base-url", "https://a.test/annals"]
        )[0]
        == 0
    )
    assert (
        _run(
            [
                "configure",
                "--to",
                "other",
                "--target",
                str(other),
                "--base-url",
                "https://b.test/annals/",
            ]
        )[0]
        == 0
    )
    return main, other


def test_configure_to_keeps_the_default_and_the_named_table(env):
    _setup(env)
    s = load_settings()
    assert (s.target.endswith("main"), s.base_url) == (True, "https://a.test/annals")
    assert named_targets()["other"]["base_url"] == "https://b.test/annals"
    # rewriting the default does not drop the named table
    _run(["configure", "--target", str(env / "main2")])
    assert "other" in named_targets()


def test_unknown_target_is_a_clear_error(env):
    code, _, err = _run(["publish", "-", "--to", "nope"])
    assert code == 1 and "unknown annals target 'nope'" in err


def test_publish_to_goes_only_to_the_named_target(env):
    main, other = _setup(env)
    doc = env / "r.md"
    doc.write_text("# R\n\nbody")
    code, url, _ = _run(["publish", str(doc), "--to", "other"])
    assert code == 0 and url.startswith("https://b.test/annals/d/")
    assert len(list((other / "docs").iterdir())) == 1
    assert not (main / "docs").exists()
    # without --to nothing changed
    _, url2, _ = _run(["publish", str(doc)])
    assert url2.startswith("https://a.test/annals/d/") and (main / "docs").exists()


def test_copy_a_doc_and_a_group_keeps_ids(env):
    main, other = _setup(env)
    a, b = env / "a.md", env / "b.md"
    a.write_text("# A\n\n1")
    b.write_text("# B\n\n2")
    _, out, _ = _run(["publish", str(a), str(b), "--group", "Both"])
    group_url = out.splitlines()[0]
    gid = group_url.rsplit("/", 1)[1]

    code, out, _ = _run(["copy", group_url, "--to", "other"])
    lines = out.splitlines()
    assert code == 0 and lines[0] == f"https://b.test/annals/g/{gid}"
    assert sorted(p.name for p in (other / "docs").iterdir()) == sorted(
        p.name for p in (main / "docs").iterdir()
    )
    assert json.loads((other / "groups" / f"{gid}.json").read_text())["title"] == "Both"

    # a single doc by bare id; idempotent
    doc_id = next((main / "docs").iterdir()).name
    code, out, _ = _run(["copy", doc_id, "--to", "other"])
    assert code == 0 and out == f"https://b.test/annals/d/{doc_id}"


def test_copy_refuses_same_place(env):
    _setup(env)
    code, _, err = _run(
        ["copy", "20260101-000000-x-abcd", "--to", "other", "--source", "other"]
    )
    assert code == 1 and "same place" in err
