"""Publishing warns about issues and messages a document mentions without a link, and still publishes."""

import io

from annals.__main__ import run
from annals.linkcheck import unlinked_mentions


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNALS_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://example.com/annals/")
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))


def test_mentions_found_and_links_respected():
    doc = "\n".join(
        [
            "# Catch-up, 2026-10-04 → 2026-11-07",
            "- Jahrl asked on 10-29 in #tech-app-test what was missing.",
            "- Jahrl [asked on 10-29](https://x.slack.com/archives/C1/p1793282410143959).",
            "- Open: o/r#3 and #4; done: [o/r#5](https://github.com/o/r/issues/5).",
            "```",
            "Karl asked on 10-29, see #9",
            "```",
        ]
    )
    got = [(m.line, m.kind) for m in unlinked_mentions(doc)]
    assert got == [(2, "message"), (4, "issue"), (4, "issue")]


def test_publish_warns_on_stderr_and_still_prints_the_link(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    src = tmp_path / "r.md"
    src.write_text("# R\n\nKarl asked in a thread on 11-06; tracked in o/r#4.\n")
    out, err = io.StringIO(), io.StringIO()
    assert run(["publish", str(src)], out=out, err=err) == 0
    assert out.getvalue().startswith("https://example.com/annals/d/")
    assert "r.md: 2 mentions without a link" in err.getvalue()


def test_publish_without_link_check_is_silent(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    src = tmp_path / "r.md"
    src.write_text("# R\n\nKarl asked in a thread on 11-06.\n")
    out, err = io.StringIO(), io.StringIO()
    assert run(["publish", str(src), "--no-link-check"], out=out, err=err) == 0
    assert "without a link" not in err.getvalue()
