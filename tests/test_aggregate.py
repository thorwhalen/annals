"""One markdown file from many: the text mechanism, the owner's and the share's endpoints, the CLI."""

import io

import pytest
from fastapi.testclient import TestClient

from annals.__main__ import run
from annals.aggregate import (
    TooLarge,
    aggregate_markdown,
    demote_headings,
    doc_markdown_files,
    numbered_first,
    unwrap_lines,
)
from annals.api import mk_app
from annals.auth import no_auth
from annals.share import REMOVED_ID, ScryptHasher, Shares
from annals.share_api import mk_share_api
from annals.store import DocStore


# -- the text mechanism ---------------------------------------------------------------


def test_numbered_first_keeps_folders_together_and_the_rest_in_order():
    paths = ["zeta.md", "B/x.md", "3-c.md", "A/2.md", "1-a.md", "A/1.md", "B/01-w.md"]
    assert numbered_first(paths) == [
        "1-a.md",
        "3-c.md",
        "zeta.md",
        "B/01-w.md",
        "B/x.md",
        "A/1.md",
        "A/2.md",
    ]
    assert numbered_first(["10-b", "9-a", "09-z"]) == ["09-z", "9-a", "10-b"]


def test_demote_caps_at_six_and_leaves_code_and_hashtags_alone():
    text = "###### Deep\n#hashtag\n~~~\n## in code\n~~~\n    # indented code? no: still a heading"
    out = demote_headings(text, 2).split("\n")
    assert out[0] == "###### Deep" and out[1] == "#hashtag"
    assert out[3] == "## in code"
    assert demote_headings("# A", 0) == "# A"


def test_setext_only_after_a_plain_paragraph_line():
    assert demote_headings("Title\n=====\n\ntext") == "## Title\n\ntext"
    # a thematic break after a blank line, or after a list item, is not a heading
    assert demote_headings("a\n\n---") == "a\n\n---"
    assert demote_headings("- item\n---") == "- item\n---"


@pytest.mark.parametrize(
    "text",
    [
        "| a | b |\n|---|---|\n| 1 | 2 |",
        "a | b\n--|--\n1 | 2",
        "> quoted\n> more",
        "<div>\nhtml\n</div>",
        "```\nline one\nline two\n```",
        "Ends with a break  \nnext line",
        "Ends with a backslash\\\nnext line",
        "# Heading\ntext under it",
        "[ref]: https://example.org\n[ref2]: https://example.org",
        "$$\nx = 1\n$$",
    ],
)
def test_unwrap_leaves_structure_alone(text):
    assert unwrap_lines(text) == text


def test_unwrap_joins_paragraphs_and_list_items_only():
    text = "One\ntwo\nthree.\n\n1. first\n   wraps\n2. second\n\nAfter the list\nwraps too."
    assert unwrap_lines(text) == (
        "One two three.\n\n1. first wraps\n2. second\n\nAfter the list wraps too."
    )


def test_aggregate_layout():
    md = aggregate_markdown(
        [
            ("notes.md", "---\ntitle: front\n---\n# Notes\nwrapped\nline"),
            ("02-b.md", "Body B"),
            ("01-a.md", "# A\n## A.1"),
        ],
        title="Bundle",
    )
    assert md.startswith(
        "# Bundle\n\n**Contents**\n\n- [01-a.md](#01-amd)\n- [02-b.md](#02-bmd)\n- [notes.md](#notesmd)\n"
    )
    sections = md.split("\n## ")
    assert [s.split("\n", 1)[0] for s in sections[1:]] == [
        "01-a.md",
        "A",
        "02-b.md",
        "notes.md",
        "Notes",
    ]
    assert "### A.1" in md and "wrapped line" in md and "front" not in md
    assert md.endswith("\n") and not md.endswith("\n\n")


def test_aggregate_options_and_repeated_paths():
    md = aggregate_markdown(
        {"b.md": "# B\nx\ny", "a.md": "A"},
        order=None,
        demote=0,
        unwrap=False,
        toc=False,
    )
    assert md == "## b.md\n\n# B\nx\ny\n\n## a.md\n\nA\n"
    twice = aggregate_markdown([("r.md", "1"), ("r.md", "2")], title="T")
    assert (
        "- [r.md](#rmd)\n- [r.md (2)](#rmd-2)" in twice and "## r.md (2)\n\n2" in twice
    )


def test_doc_markdown_files_names_skips_and_caps():
    docs = [
        ({"id": "d1", "title": "Solo", "kind": "md"}, ["01-solo.md", "img.png"]),
        (
            {"id": "d2", "title": "A/B report", "kind": "folder"},
            ["x.md", "y.md", "z.txt"],
        ),
        ({"id": "d3", "title": "Gone", "kind": "md"}, ["gone.md"]),
    ]
    texts = {("d1", "01-solo.md"): "s", ("d2", "x.md"): "x", ("d2", "y.md"): "y"}
    read = lambda i, rel: texts[(i, rel)]  # noqa: E731  (d3 is a KeyError: skipped)
    assert list(doc_markdown_files(docs, read=read)) == [
        ("01-solo.md", "s"),
        ("A-B report/x.md", "x"),
        ("A-B report/y.md", "y"),
    ]
    with pytest.raises(TooLarge):
        list(doc_markdown_files(docs, read=read, max_bytes=2))


# -- the owner's endpoint -------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


@pytest.fixture
def bundle(store, tmp_path):
    """A group: a markdown page, a folder with two pages and an image, an image, a binned page."""
    folder = tmp_path / "Chapters"
    folder.mkdir()
    (folder / "02-two.md").write_text("# Two\nsecond\nchapter")
    (folder / "01-one.md").write_text("# One")
    (folder / "pic.png").write_bytes(b"\x89PNG")
    intro = store.publish(
        text="# Intro\n\nhello", title="Intro", filename="00-intro.md"
    )
    chapters = store.publish(folder, title="Chapters")
    pic = tmp_path / "pic.png"
    pic.write_bytes(b"\x89PNG")
    image = store.publish(pic)
    binned = store.publish(text="# Binned", title="Binned", filename="binned.md")
    store.trash(binned["id"])
    g = store.make_group(
        "My bundle", [chapters["id"], intro["id"], image["id"], binned["id"]]
    )
    return g, intro, chapters


@pytest.fixture
def owner(store):
    return TestClient(mk_app(store=store, authorizer=no_auth), follow_redirects=False)


def test_owner_aggregate(owner, bundle):
    g, *_ = bundle
    r = owner.get(f"/annals/api/groups/{g['id']}/aggregate")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert r.headers["x-annals-sections"] == "3"
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["content-disposition"].startswith(
        'inline; filename="my-bundle.md"'
    )
    text = r.text
    assert text.startswith(
        "# My bundle\n\n**Contents**\n\n- [00-intro.md](#00-intromd)\n"
    )
    heads = [line for line in text.split("\n") if line.startswith("## ")]
    assert heads == [
        "## 00-intro.md",
        "## Intro",
        "## Chapters/01-one.md",
        "## One",
        "## Chapters/02-two.md",
        "## Two",
    ]
    assert "second chapter" in text and "Binned" not in text

    dl = owner.get(f"/annals/api/groups/{g['id']}/aggregate?download=1&demote=0")
    assert dl.headers["content-type"].startswith("text/markdown")
    assert dl.headers["content-disposition"].startswith(
        'attachment; filename="my-bundle.md"'
    )
    assert "\n# Intro\n" in dl.text


def test_owner_aggregate_errors(owner, store):
    assert (
        owner.get("/annals/api/groups/20200101-000000-nope-0000/aggregate").status_code
        == 404
    )
    assert owner.get("/annals/api/groups/not-an-id/aggregate").status_code == 404
    pic = store.publish(text="plain", filename="a.txt")
    g = store.make_group("No md", [pic["id"]])
    r = owner.get(f"/annals/api/groups/{g['id']}/aggregate")
    assert r.status_code == 404 and "no markdown" in r.json()["detail"]


def test_owner_aggregate_size_cap(owner, store, monkeypatch):
    import annals.export

    a = store.publish(text="x" * 50, title="A", filename="a.md")
    g = store.make_group("Big", [a["id"]])
    real = annals.export.aggregate_response
    monkeypatch.setattr(
        "annals.api.aggregate_response",
        lambda *a, **k: real(*a, **{**k, "max_bytes": 10}),
    )
    assert owner.get(f"/annals/api/groups/{g['id']}/aggregate").status_code == 413


# -- the share's endpoint: only what the link includes, filtered ------------------------


@pytest.fixture
def shares(store):
    return Shares(store, hasher=ScryptHasher(n=2**4))


@pytest.fixture
def recipient(shares):
    return TestClient(
        mk_share_api(shares=shares, thumbnailer=None), follow_redirects=False
    )


def test_share_aggregate_is_the_scope_filtered(recipient, shares, store):
    private = store.publish(text="# Private", title="Private", filename="private.md")
    a = store.publish(
        text=f"# A\nsee {private['id']}\nand [p](/annals/d/{private['id']})",
        title="A",
        filename="a.md",
    )
    b = store.publish(text="# B secret", title="B", filename="b.md")
    g = store.make_group("Pair", [a["id"], b["id"], private["id"]])
    rec = shares.create(g["id"], include=[a["id"]])
    r = recipient.get(f"/{rec['token']}/aggregate")
    assert r.status_code == 200 and r.headers["x-annals-sections"] == "1"
    assert "## a.md" in r.text and "secret" not in r.text and "Private" not in r.text
    assert private["id"] not in r.text and REMOVED_ID in r.text
    assert r.headers["referrer-policy"] == "no-referrer"
    dl = recipient.get(f"/{rec['token']}/aggregate?download=1")
    assert dl.headers["content-disposition"].startswith(
        'attachment; filename="pair.md"'
    )


def test_share_aggregate_gate_and_revocation(recipient, shares, store):
    a = store.publish(text="# A", title="A", filename="a.md")
    g = store.make_group("Locked", [a["id"]])
    rec = shares.create(g["id"], password="long-enough-pw")
    assert recipient.get(f"/{rec['token']}/aggregate").status_code == 401
    open_rec = shares.create(g["id"])
    assert recipient.get(f"/{open_rec['token']}/aggregate").status_code == 200
    shares.revoke(open_rec["token"])
    assert recipient.get(f"/{open_rec['token']}/aggregate").status_code == 404
    assert recipient.get("/nope/aggregate").status_code == 404


def test_share_aggregate_leaves_out_excluded_files(recipient, shares, store, tmp_path):
    folder = tmp_path / "Pages"
    folder.mkdir()
    (folder / "index.md").write_text("# Index")
    (folder / "z-draft.md").write_text("# Draft, not for sharing")
    doc = store.publish(folder, title="Pages")
    rec = shares.create(doc["id"], exclude=["z-draft.md"])
    r = recipient.get(f"/{rec['token']}/aggregate")
    assert r.status_code == 200 and "Index" in r.text and "Draft" not in r.text


# -- the CLI ----------------------------------------------------------------------------


def test_cli_aggregate(bundle, store, monkeypatch, tmp_path):
    g, *_ = bundle
    monkeypatch.setenv("ANNALS_TARGET", str(store.target.local_path(".")))
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    out = io.StringIO()
    assert run(["aggregate", g["id"]], out=out, err=io.StringIO()) == 0
    assert out.getvalue().startswith("# My bundle\n\n**Contents**\n")
    out = io.StringIO()
    link = f"https://example.com/annals/g/{g['id']}"
    assert (
        run(
            ["aggregate", link, "--order", "given", "--no-toc", "--demote", "0"],
            out=out,
            err=io.StringIO(),
        )
        == 0
    )
    text = out.getvalue()
    assert "**Contents**" not in text and "\n# One\n" in text
    assert text.index("Chapters/01-one.md") < text.index(
        "00-intro.md"
    )  # the group's order
    err = io.StringIO()
    assert (
        run(["aggregate", g["id"], "--order", "bogus"], out=io.StringIO(), err=err) == 1
    )
    assert "order must be one of" in err.getvalue()
