"""A share link's page carries its text (for fetchers that run no script), and the share
answers as one Markdown file and one PDF, under the share's own token, expiry and revocation."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import annals.share_page as share_page
from annals.share import ScryptHasher, Shares, share_links
from annals.share_api import mk_share_api
from annals.share_page import alternate_urls, description_of
from annals.store import DocStore


class Clock:
    def __init__(self, t=datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def shares(store, clock):
    return Shares(store, hasher=ScryptHasher(n=2**4), clock=clock)


@pytest.fixture
def client(shares):
    return TestClient(mk_share_api(shares=shares, thumbnailer=None), follow_redirects=False)


@pytest.fixture
def report(store, tmp_path):
    """A report with an included image, an excluded note, and a private page it names."""
    src = tmp_path / "report"
    (src / "img").mkdir(parents=True)
    (src / "img" / "a.png").write_bytes(b"\x89PNG a")
    (src / "private.txt").write_text("secret notes")
    other = store.publish(text="# Other\n\nprivate page", title="Other")
    (src / "report.md").write_text(
        "# Findings\n\nThe capture rate rose by **twelve percent** in October.\n\n"
        "![chart](img/a.png)\n\n[notes](private.txt) and [web](https://example.org)\n\n"
        f"see [other](/annals/d/{other['id']}) or {other['id']}\n"
    )
    meta = store.publish(src, title="Report")
    return meta, other


def _text(page: str) -> str:
    """What a fetcher without script reads: the page with its scripts dropped."""
    return re.sub(r"<script\b.*?</script>", "", page, flags=re.S)


def test_a_document_share_page_carries_its_text(client, shares, report):
    meta, other = report
    rec = shares.create(meta["id"], include=["img/a.png"])
    link = f"/{rec['token']}"
    page = client.get(link + "/")
    assert page.status_code == 200
    body = _text(page.text)
    assert "twelve percent" in body and "<strong>" in body
    assert f'src="{link}/raw/{meta["id"]}/img/a.png"' in body
    # what the share leaves out stays out of the page too
    assert "private.txt" not in body and "secret notes" not in body
    assert other["id"] not in body and "private page" not in body
    assert "https://example.org" in body
    assert '<meta name="description" content="Findings The capture rate rose' in body
    assert f'<link rel="alternate" type="text/markdown" href="{link}/share.md"' in body
    assert f'href="{link}/share.pdf"' in body
    # no script on the page (a fetcher that runs script would replace the text with the
    # viewer); the viewer is a link away
    assert "<script" not in page.text and "script-src" not in page.headers["content-security-policy"]
    assert f'href="{link}/?viewer">open in the viewer</a>' in body
    viewer = client.get(link + "/?viewer")
    assert "window.ANNALS" in viewer.text and "app.js" in viewer.text


def test_a_group_share_page_carries_every_document_in_order(client, shares, store):
    a = store.publish(text="# Alpha\n\nfirst body text", title="Alpha doc")
    b = store.publish(text="# Beta\n\nsecond body text", title="Beta doc")
    c = store.publish(text="# Gamma\n\nnot shared", title="Gamma doc")
    g = store.make_group("Trio", [a["id"], b["id"], c["id"]])
    rec = shares.create(g["id"], include=[a["id"], b["id"]])
    link = f"/{rec['token']}"
    body = _text(client.get(link + "/").text)
    assert body.index("first body text") < body.index("second body text")
    assert "not shared" not in body and "Gamma" not in body
    assert f'<a href="{link}/d/{a["id"]}">Alpha doc</a>' in body
    # one document's page: only it, its own alternates
    one = _text(client.get(f"{link}/d/{b['id']}").text)
    assert "second body text" in one and "first body text" not in one
    assert f'href="{link}/d/{b["id"]}.md"' in one
    # a document outside the share: no page, and nothing of it
    out = client.get(f"{link}/d/{c['id']}")
    assert out.status_code == 404 and "not shared" not in out.text


def test_the_share_as_one_markdown_file(client, shares, store):
    a = store.publish(text="# Alpha\n\nfirst body text", title="Alpha doc")
    b = store.publish(text="# Beta\n\nsecond body text", title="Beta doc")
    g = store.make_group("Pair", [a["id"], b["id"]])
    rec = shares.create(g["id"])
    link = f"/{rec['token']}"
    md = client.get(f"{link}/share.md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/plain")  # shown, not downloaded
    assert "first body text" in md.text and "second body text" in md.text
    assert "attachment" not in md.headers.get("content-disposition", "")
    one = client.get(f"{link}/d/{b['id']}.md")
    assert one.status_code == 200 and "second body text" in one.text
    assert "first body text" not in one.text
    assert client.get(f"{link}/share.docx").status_code == 404
    assert client.get(f"{link}/d/nope.md").status_code == 404


def test_the_share_as_one_pdf(client, shares, report):
    pytest.importorskip("weasyprint")
    meta, _ = report
    rec = shares.create(meta["id"], include=["img/a.png"])
    pdf = client.get(f"/{rec['token']}/share.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_every_representation_ends_with_the_link(client, shares, report, clock):
    meta, _ = report
    rec = shares.create(meta["id"], expires="1d")
    link = f"/{rec['token']}"
    paths = ["/", "/share.md", "/share.pdf", f"/d/{meta['id']}", f"/d/{meta['id']}.md"]
    clock.t += timedelta(days=2)
    for p in paths:
        r = client.get(link + p)
        assert r.status_code == 410, p
        assert "twelve percent" not in r.text
    rec = shares.create(meta["id"])
    shares.revoke(rec["token"])
    for p in paths:
        r = client.get(f"/{rec['token']}{p}")
        assert r.status_code == 404, p
        assert "twelve percent" not in r.text


def test_a_locked_link_shows_no_text_until_unlocked(client, shares, report):
    meta, _ = report
    rec = shares.create(meta["id"], password="correct horse battery")
    link = f"/{rec['token']}"
    page = client.get(link + "/")
    assert page.status_code == 401 and "twelve percent" not in page.text
    assert client.get(f"{link}/share.md").status_code == 401
    client.post(f"{link}/unlock", data={"password": "correct horse battery", "next": f"{link}/"})
    assert "twelve percent" in client.get(link + "/").text


HTML_PAGE = (
    "<html><head><title>T</title><style>p{color:red}</style></head><body>"
    "<h1>Heading words</h1><p onclick='steal()'>Body words</p><img src='img/a.png'>"
    "<script>steal()</script></body></html>"
)


def test_an_html_document_is_served_as_itself_sandboxed(client, shares, store, tmp_path):
    src = tmp_path / "site"
    (src / "img").mkdir(parents=True)
    (src / "index.html").write_text(HTML_PAGE)
    (src / "img" / "a.png").write_bytes(b"\x89PNG")
    d = store.publish(src, title="Site")
    rec = shares.create(d["id"])
    link = f"/{rec['token']}"
    for path in ("/", f"/d/{d['id']}"):
        r = client.get(link + path)
        assert r.status_code == 200 and "Body words" in r.text and "color:red" in r.text
        assert r.headers["content-security-policy"].startswith("sandbox ")
        assert "allow-same-origin" not in r.headers["content-security-policy"]
        assert f'<head><base href="{link}/raw/{d["id"]}/">' in r.text
    assert client.get(f"{link}/raw/{d['id']}/img/a.png").status_code == 200


def test_in_a_group_an_html_document_is_its_words_never_its_script(client, shares, store):
    md = store.publish(text="# Notes\n\nplain words", title="Notes")
    page = store.publish(text=HTML_PAGE, title="Page", filename="page.html")
    rec = shares.create(store.make_group("Mixed", [md["id"], page["id"]])["id"])
    link = f"/{rec['token']}"
    body = client.get(link + "/").text
    assert "plain words" in body and "Heading words" in body and "Body words" in body
    assert "steal" not in body and "onclick" not in body and "color:red" not in body
    assert f'<a href="{link}/d/{page["id"]}">Open the page as designed</a>' in body


def test_a_folder_of_images_shows_them(client, shares, store, tmp_path):
    src = tmp_path / "renders"
    src.mkdir()
    for n in ("one.png", "two.png"):
        (src / n).write_bytes(b"\x89PNG")
    d = store.publish(src, title="Renders")
    rec = shares.create(d["id"])
    body = _text(client.get(f"/{rec['token']}/").text)
    assert body.count("<img ") == 2 and f"/raw/{d['id']}/one.png" in body


def test_a_large_share_links_what_does_not_fit(client, shares, store, monkeypatch):
    monkeypatch.setattr(share_page, "STATIC_MAX_BYTES", 10)
    a = store.publish(text="# Alpha\n\nfirst body text", title="Alpha doc")
    b = store.publish(text="# Beta\n\nsecond body text", title="Beta doc")
    rec = shares.create(store.make_group("Pair", [a["id"], b["id"]])["id"])
    link = f"/{rec['token']}"
    body = _text(client.get(link + "/").text)
    assert "first body text" in body and "second body text" not in body
    assert "More in this share" in body and f'href="{link}/d/{b["id"]}"' in body


def test_alternates_and_description():
    assert [u for u, _, _ in alternate_urls("/s/T/")] == ["/s/T/share.md", "/s/T/share.pdf"]
    assert alternate_urls("/s/T", "d1")[0][0] == "/s/T/d/d1.md"
    content = '<h1>Title</h1><p class="muted">Also as <a>Markdown</a>.</p><p>Words &amp; more</p>'
    assert description_of(content, skip="Title") == "Words & more"
    assert description_of("<p>" + "x" * 500 + "</p>", n=10).endswith("…")


def test_share_links_name_the_three_forms():
    assert share_links(None, "T") == {}
    assert share_links("https://h/s", "T") == {
        "page": "https://h/s/T/",
        "markdown": "https://h/s/T/share.md",
        "pdf": "https://h/s/T/share.pdf",
    }
