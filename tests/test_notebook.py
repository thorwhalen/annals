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
    assert markdown_html("# Hi", render=lambda t, r: "<p>custom</p>") == "<p>custom</p>"
    monkeypatch.setattr(notebook, "_default_markdown_renderer", lambda: None)
    assert markdown_html("<b>x</b>") == "<pre>&lt;b&gt;x&lt;/b&gt;</pre>"


def test_markdown_html_rewrites_links_and_images():
    out = markdown_html(
        "[keep](a) [drop](b) ![img](c) ![gone](d)",
        rewrite_url=lambda u: {"a": "/A", "c": "/C"}.get(u),
    )
    assert '<a href="/A">keep</a>' in out and "drop" in out and 'href="b"' not in out
    assert 'src="/C"' in out and "gone" not in out


def test_source_page_is_plain():
    page = source_page("A <title>", "<p>body</p>")
    assert "<title>A &lt;title&gt;</title>" in page
    assert "<base" not in page and "<script" not in page


# -- the owner's flow: tick documents, get one link each, paste, revoke ------------------


def test_owner_makes_source_links_for_chosen_documents(owner, bundle):
    g, intro, chapters, image, private = bundle
    made = owner.post(
        "/annals/api/shares",
        json={"ref": g["id"], "include": [intro["id"], chapters["id"], image["id"]],
              "expires": "1d", "files": "sources"},
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
    # a file the page shows is linked absolutely (no <base>), to the share's raw file
    chap = anon.get(out["sources"][1]["url"]).text
    assert f'src="/annals/shared/{made["token"]}/raw/{chapters["id"]}/pic.png"' in chap
    assert "<base" not in chap
    assert out["protected"] is False and out["expires"]

    link = made["url"]
    # the private page was not ticked: no source, no raw file
    assert anon.get(f"{link}source/{private['id']}/{private['main']}").status_code == 404
    # an image is not a source page, even when it is shared
    assert anon.get(f"{link}source/{chapters['id']}/pic.png").status_code == 404
    # the image alone was ticked but has no page: a notebook share holds none of its files
    assert anon.get(f"{link}raw/{image['id']}/{image['main']}").status_code == 404
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


# -- what the adversarial review found ----------------------------------------------------


def _source_share(owner, store, text, *, files=None, extra=()):
    """A group of one page (plus ``extra`` docs, unshared), shared for a notebook."""
    doc = store.publish(text=text, title="Page", filename="page.md")
    g = store.make_group("G", [doc["id"], *extra])
    made = owner.post(
        "/annals/api/shares",
        json={"ref": g["id"], "include": [doc["id"]], "files": files or "sources"},
    ).json()
    return doc, made


def test_rendered_links_the_text_filter_missed_are_removed(owner, store):
    secret = store.publish(text="# Secret", title="Secret")
    sid = secret["id"]
    tricky = (
        f"[a](\nhttps://testserver/annals/d/{sid})\n\n"
        f"[r]: \n   https://testserver/also-secret\n\nsee [r]\n\n"
        "<HTTPS://TESTSERVER/annals/secret>\n\n"
        "[ok](https://example.org/x) [toc](#intro) [js](javascript:alert(1))\n\n"
        f"bare {sid.replace('-', chr(92) + '-')} and {sid.replace('-', '&#45;')}\n"
    )
    doc, made = _source_share(owner, store, tricky, extra=[sid])
    page = TestClient(owner.app).get(f"{made['url']}source/{doc['id']}/page.md").text
    assert "testserver" not in page.lower() and "also-secret" not in page
    assert sid not in page and "javascript:" not in page
    assert 'href="https://example.org/x"' in page and 'href="#intro"' in page


def test_sibling_pages_link_to_their_source_page(owner, store, tmp_path):
    folder = tmp_path / "Book"
    folder.mkdir()
    (folder / "01-a.md").write_text("# A\n\n[next](02-b.md#top)")
    (folder / "02-b.md").write_text("# B")
    (folder / "secret.csv").write_text("x,y")
    book = store.publish(folder, title="Book")
    g = store.make_group("G", [book["id"]])
    made = owner.post(
        "/annals/api/shares", json={"ref": g["id"], "files": "sources"}
    ).json()
    anon = TestClient(owner.app)
    page = anon.get(f"{made['url']}source/{book['id']}/01-a.md").text
    assert f'href="{made["url"]}source/{book["id"]}/02-b.md#top"' in page
    # a folder's other files are not in a notebook share
    assert anon.get(f"{made['url']}raw/{book['id']}/secret.csv").status_code == 404


def test_html_source_runs_nothing(owner, store, tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<html><head><title>P</title></head><body><script>x()</script>Hi</body></html>")
    doc = store.publish(page, title="P")
    g = store.make_group("G", [doc["id"]])
    made = owner.post("/annals/api/shares", json={"ref": g["id"], "files": "sources"}).json()
    r = TestClient(owner.app).get(f"{made['url']}source/{doc['id']}/page.html")
    csp = r.headers["content-security-policy"]
    assert r.status_code == 200 and csp.startswith("sandbox;") and "script-src" not in csp
    assert "connect-src" not in csp and "default-src 'none'" in csp


def test_password_and_expiry_hold_on_source_routes(owner, store):
    doc = store.publish(text="# P", title="P", filename="p.md")
    g = store.make_group("G", [doc["id"]])
    locked = owner.post(
        "/annals/api/shares", json={"ref": g["id"], "password": "a-long-password"}
    ).json()
    anon = TestClient(owner.app, follow_redirects=False)
    assert anon.get(f"{locked['url']}source/{doc['id']}/p.md").status_code == 401
    assert anon.get(f"{locked['url']}sources").status_code == 401
    assert owner.get(f"/annals/api/shares/{locked['token']}/sources").json()["protected"]


def test_a_huge_page_is_sent_as_text_not_rendered(owner, store, monkeypatch):
    monkeypatch.setattr(notebook, "RENDER_MAX_BYTES", 50)
    doc, made = _source_share(owner, store, "# Big\n\n" + "word " * 40)
    page = TestClient(owner.app).get(f"{made['url']}source/{doc['id']}/page.md").text
    assert "<pre># Big" in page and "<h1>" not in page


def test_bad_files_option_and_empty_doc_filter(owner, bundle):
    g, *_ = bundle
    bad = owner.post("/annals/api/shares", json={"ref": g["id"], "files": "some"})
    assert bad.status_code == 422
    r = owner.get(f"/annals/api/groups/{g['id']}/aggregate?doc=")
    assert r.status_code == 200 and r.headers["x-annals-sections"] == "4"
