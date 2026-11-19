"""A link finds its own annals: ``aggregate``/``show``/``references`` need no ``--to`` for a link."""

import io
import json

import pytest

from annals.__main__ import run
from annals.config import link_target


@pytest.fixture
def env(tmp_path, monkeypatch):
    for var in ("ANNALS_TARGET", "ANNALS_BASE_URL", "ANNALS_OUTBOX"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANNALS_CONFIG", str(tmp_path / "cfg" / "config.toml"))
    return tmp_path


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = run(argv, out=out, err=err)
    return code, out.getvalue().strip(), err.getvalue()


def _configure(env, *, default_outbox=False):
    args = [
        "configure",
        "--target",
        str(env / "main"),
        "--base-url",
        "https://a.test/annals",
    ]
    assert _run(args + (["--outbox"] if default_outbox else []))[0] == 0
    for name, base in [
        ("other", "https://b.test/annals"),
        ("main", "https://a.test/annals"),
    ]:
        if name == "main" and not default_outbox:
            continue  # the readable twin of an outbox default, as on a server that pushes
        code, _, err = _run(
            ["configure", "--to", name, "--target", str(env / name), "--base-url", base]
        )
        assert code == 0, err


def _publish(env, name, text, *, to=None):
    doc = env / f"{name}.md"
    doc.write_text(text)
    code, url, err = _run(["publish", str(doc), *(["--to", to] if to else [])])
    assert code == 0, err
    return url


def test_a_link_to_another_annals_is_read_there_without_to(env):
    _configure(env)
    url = _publish(env, "b", "# On B\n\nbody of b", to="other")
    assert url.startswith("https://b.test/annals/d/")
    code, text, err = _run(["aggregate", url])
    assert code == 0, err
    assert "body of b" in text
    # the bare id still means the default annals, where it is not
    code, _, err = _run(["aggregate", url.rsplit("/", 1)[1]])
    assert code == 1 and "no such document" in err


def test_show_lists_the_annals_links_a_document_makes_on_every_known_annals(env):
    _configure(env)
    a = _publish(env, "a", "# On A\n\ntext")
    b = _publish(
        env,
        "b",
        f"# On B\n\nSee **[a]({a})**, a stranger "
        "https://elsewhere.test/annals/d/20261119-075018-gone-4a58, and itself.",
        to="other",
    )
    code, out, err = _run(["show", b])
    assert code == 0, err
    meta = json.loads(out)
    assert meta["url"] == b
    assert meta["links"] == [
        a
    ]  # the unknown host is left out, as is the document itself
    code, text, _ = _run(["aggregate", meta["links"][0]])
    assert code == 0 and "text" in text


def test_a_link_on_an_unknown_host_is_looked_up_in_the_default(env):
    _configure(env)
    a = _publish(env, "a", "# On A\n\ntext of a")
    stranger = a.replace("https://a.test/", "https://c.test/")
    code, text, err = _run(["aggregate", stranger])
    assert code == 0 and "text of a" in text, err
    with pytest.raises(ValueError, match="not on an annals this machine knows"):
        link_target(stranger)  # the function itself names the places it knows


def test_a_readable_target_beats_an_outbox_with_the_same_base_url(env):
    _configure(env, default_outbox=True)
    assert link_target("https://a.test/annals/d/20261119-075018-x-4a58") == "main"
    assert link_target("https://b.test/annals/g/20261119-075018-x") == "other"


def test_an_explicit_to_wins_over_the_link(env):
    _configure(env)
    url = _publish(env, "b", "# On B\n\nbody", to="other")
    code, _, err = _run(["aggregate", url, "--to", "other"])
    assert code == 0, err
    # pointing a link at the wrong place by hand is honoured, and fails as before
    main_id = url.rsplit("/", 1)[1]
    code, _, err = _run(["aggregate", url, "--target", str(env / "main")])
    assert code == 1 and main_id in err


def test_a_longer_base_url_on_the_same_host_wins(env):
    _configure(env)
    code, _, err = _run(
        [
            "configure",
            "--to",
            "room",
            "--target",
            str(env / "room"),
            "--base-url",
            "https://a.test/annals/room",
        ]
    )
    assert code == 0, err
    assert link_target("https://a.test/annals/room/d/20261119-075018-x-4a58") == "room"
    assert link_target("https://a.test/annals/d/20261119-075018-x-4a58") is None
    with pytest.raises(
        ValueError, match="not on an annals"
    ):  # a prefix of a segment is no match
        link_target("https://a.test/annalsx/d/20261119-075018-x-4a58")
