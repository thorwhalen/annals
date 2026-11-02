"""A group's documents as separate notebook sources: one plain web page per text file."""

import pytest
from fastapi.testclient import TestClient

from annals import notebook
from annals.api import mk_app
from annals.auth import no_auth
from annals.notebook import markdown_html, notebook_sources, source_page, source_url
from annals.store import DocStore


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


@pytest.fixture
def bundle(store, tmp_path):
    """A group: a page, a folder of two pages and an image, an image alone, a private page."""
    folder = tmp_path / "Chapters"
    folder.mkdir()
    (folder / "02-two.md").write_text("# Two\n\nsecond")
    (folder / "01-one.md").write_text("# One\n\n![pic](pic.png)")
    (folder / "pic.png").write_bytes(b"\x89PNG")
    private = store.publish(text="# Private\n\nnot for you", title="Private")
    intro = store.publish(
        text=f"# Intro\n\nhello, see [private](/annals/d/{private['id']})\n\n"
        "<script>alert(1)</script>\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
        title="Intro",
        filename="00-intro.md",
    )
    chapters = store.publish(folder, title="Chapters")
    pic = tmp_path / "pic.png"
    pic.write_bytes(b"\x89PNG")
    image = store.publish(pic, title="A picture")
    g = store.make_group(
        "Bundle", [intro["id"], chapters["id"], image["id"], private["id"]]
    )
    return g, intro, chapters, image, private


@pytest.fixture
def owner(store):
    return TestClient(mk_app(store=store, authorizer=no_auth), follow_redirects=False)


# -- the mechanism, text in, rows out ---------------------------------------------------


def test_notebook_sources_rows_titles_and_skips():
    scope = [
        ({"id": "d1", "title": "Solo"}, ["solo.md", "img.png"]),
        ({"id": "d2", "title": "Book"}, ["b/10-ten.md", "b/2-two.md", "page.html"]),
        ({"id": "d3", "title": "Pics"}, ["a.png", "b.mp3"]),
    ]
    out = notebook_sources(scope, link="/s/tok/")
    assert [(r["doc"], r["file"], r["title"]) for r in out["sources"]] == [
        ("d1", "solo.md", "Solo"),
        ("d2", "b/2-two.md", "Book · b/2-two.md"),
        ("d2", "b/10-ten.md", "Book · b/10-ten.md"),
        ("d2", "page.html", "Book · page.html"),
    ]
    assert out["sources"][0]["url"] == "/s/tok/source/d1/solo.md"
    assert out["skipped"] == [{"doc": "d3", "title": "Pics", "kinds": ["audio", "image"]}]


def test_source_url_quotes_each_segment():
    assert (
        source_url("https://x/s/t", "d", "a b/c#d.md")
        == "https://x/s/t/source/d/a%20b/c%23d.md"
    )


def test_markdown_html_seam_and_fallback(monkeypatch):
    assert markdown_html("# Hi", render=lambda t: "<p>custom</p>") == "<p>custom</p>"
    monkeypatch.setattr(notebook, "_default_markdown_renderer", lambda: None)
    assert markdown_html("<b>x</b>") == "<pre>&lt;b&gt;x&lt;/b&gt;</pre>"


def test_source_page_is_plain():
    page = source_page("A <title>", "<p>body</p>", base_href="/raw/d/")
    assert "<title>A &lt;title&gt;</title>" in page
    assert '<base href="/raw/d/">' in page and "<script" not in page


# -- the owner's flow: tick documents, get one link each, paste, revoke ------------------


def test_owner_makes_source_links_for_chosen_documents(owner, bundle):
    g, intro, chapters, image, private = bundle
    made = owner.post(
        "/annals/api/shares",
        json={"ref": g["id"], "include": [intro["id"], chapters["id"], image["id"]], "expires": "1d"},
    ).json()
    out = owner.get(f"/annals/api/shares/{made['token']}/sources").json()
    titles = [s["title"] for s in out["sources"]]
    assert titles == ["Intro", "Chapters · 01-one.md", "Chapters · 02-two.md"]
    assert [s["doc"] for s in out["skipped"]] == [image["id"]]

    anon = TestClient(owner.app, follow_redirects=False)
    first = anon.get(out["sources"][0]["url"])
    assert first.status_code == 200
    assert first.headers["content-type"] == "text/html; charset=utf-8"
    assert "script-src" not in first.headers["content-security-policy"]
    body = first.text
    assert "<title>Intro</title>" in body and "<h1>Intro</h1>" in body
    assert "<table>" in body
    # raw html in the markdown is shown, never run; a private page's link is removed
    assert "<script" not in body and "&lt;script&gt;" in body
    assert private["id"] not in body and "link not shared" in body
    # relative files resolve to the shared raw files
    chap = anon.get(out["sources"][1]["url"]).text
    assert f'<base href="/annals/shared/{made["token"]}/raw/{chapters["id"]}/">' in chap

    link = made["url"]
    # the private page was not ticked: no source, no raw file
    assert anon.get(f"{link}source/{private['id']}/{private['main']}").status_code == 404
    # an image is not a source page, even when it is shared
    assert anon.get(f"{link}source/{chapters['id']}/pic.png").status_code == 404
    # the recipient's side lists the same sources, with links relative to the host
    mine = anon.get(f"{link}sources").json()
    assert [s["url"] for s in mine["sources"]] == [s["url"] for s in out["sources"]]

    owner.delete(f"/annals/api/shares/{made['token']}")
    assert anon.get(out["sources"][0]["url"]).status_code == 404
    assert owner.get(f"/annals/api/shares/{made['token']}/sources").status_code == 404


def test_source_links_need_a_public_share_address(store, bundle):
    g, intro, *_ = bundle
    from annals.api import mk_api

    api = TestClient(mk_api(store=store, share_base_url=""))
    made = api.post("/shares", json={"ref": g["id"], "include": [intro["id"]]}).json()
    assert api.get(f"/shares/{made['token']}/sources").status_code == 409


# -- Combine over a selection -----------------------------------------------------------


def test_owner_aggregate_of_chosen_documents(owner, bundle):
    g, intro, chapters, image, private = bundle
    base = f"/annals/api/groups/{g['id']}/aggregate"
    r = owner.get(f"{base}?doc={chapters['id']}&doc={image['id']}")
    assert r.status_code == 200 and r.headers["x-annals-sections"] == "2"
    assert "Intro" not in r.text and "## Chapters/01-one.md" in r.text
    assert owner.get(base).headers["x-annals-sections"] == "4"
    assert owner.get(f"{base}?doc=20200101-000000-nope").status_code == 422
