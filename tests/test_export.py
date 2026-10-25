"""Downloads of a document as .md and .pdf: same access as the page, images inside."""

import re

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from annals.api import mk_api, mk_app
from annals.auth import BasicAuth
from annals.export import export_filename, resolve_ref
from annals.share import Shares, ScryptHasher
from annals.share_api import mk_share_api
from annals.store import DocStore

pytest.importorskip("weasyprint")
pytest.importorskip("markdown_it")
pypdf = pytest.importorskip("pypdf")

HOST = "testserver"


@pytest.fixture
def doc(tmp_path):
    store = DocStore(tmp_path / "data")
    src = tmp_path / "report"
    (src / "img").mkdir(parents=True)
    for name, colour in (("a.png", (200, 30, 30)), ("b.png", (30, 30, 200))):
        Image.new("RGB", (60, 40), colour).save(src / "img" / name)
    (src / "clip.mp4").write_bytes(b"not really a video")
    (src / "talk.mp3").write_bytes(b"not really audio")
    (src / "private.txt").write_text("secret notes")
    (src / "report.md").write_text(
        "# Quarterly Report: Q3!\n\nSome **bold** text.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "![first](img/a.png)\n\n![second](img/b.png)\n\n![the clip](clip.mp4)\n\n"
        "![remote](https://evil.example/x.png)\n\n<script>alert(1)</script>\n\n"
        "[notes](private.txt) [up](../../etc/passwd) [web](https://example.org)\n"
    )
    return store, store.publish(src, title="Quarterly Report: Q3!")


def _read(pdf: bytes):
    """(text, link urls, image count, title) of a PDF."""
    import io

    reader = pypdf.PdfReader(io.BytesIO(pdf))
    links = [
        str(a.get_object()["/A"]["/URI"])
        for page in reader.pages
        for a in (page.get("/Annots") or [])
        if "/A" in a.get_object() and "/URI" in a.get_object()["/A"]
    ]
    text = "\n".join(page.extract_text() for page in reader.pages)
    images = sum(len(page.images) for page in reader.pages)
    return text, links, images, (reader.metadata or {}).get("/Title")


def test_filenames_are_readable_slugs():
    assert export_filename("Quarterly Report: Q3!", "pdf") == "quarterly-report-q3.pdf"
    assert export_filename("", "md") == "doc.md"


def test_resolve_ref_stays_inside_the_document():
    files = ["report.md", "img/a.png"]
    assert resolve_ref("img/a.png", rel="report.md", files=files) == "img/a.png"
    assert resolve_ref("../a.png", rel="img/x.md", files=["a.png"]) == "a.png"
    assert resolve_ref("../../etc/passwd", rel="report.md", files=files) is None
    assert resolve_ref("https://x/img/a.png", rel="report.md", files=files) is None
    assert resolve_ref("/img/a.png", rel="report.md", files=files) is None
    assert resolve_ref("img/nope.png", rel="report.md", files=files) is None


def test_owner_markdown_download(doc):
    store, meta = doc
    c = TestClient(mk_api(store=store, thumbnailer=None))
    r = c.get(f"/export/{meta['id']}", params={"format": "md"})
    assert r.status_code == 200
    assert 'filename="quarterly-report-q3.md"' in r.headers["content-disposition"]
    assert r.text.startswith("# Quarterly Report")


def test_owner_pdf_has_title_images_and_media_links(doc):
    store, meta = doc
    c = TestClient(mk_api(store=store, thumbnailer=None), base_url=f"http://{HOST}")
    base = f"http://{HOST}/api/annals"
    r = c.get(f"/export/{meta['id']}", params={"format": "pdf", "base": base})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert 'filename="quarterly-report-q3.pdf"' in r.headers["content-disposition"]
    text, links, images, title = _read(r.content)
    assert images == 2 and title == "Quarterly Report: Q3!"
    assert text.startswith("Quarterly Report: Q3!")
    assert f"{base}/raw/{meta['id']}/clip.mp4" in links  # a link to the video
    assert f"{base}/raw/{meta['id']}/talk.mp3" in links  # unreferenced audio is listed
    assert (
        "https://evil.example/x.png" in links
    )  # a remote image is a link, never fetched
    assert "alert(1)" in text  # raw html is shown as text, not run


def test_a_base_on_another_host_is_not_printed(doc):
    store, meta = doc
    c = TestClient(mk_api(store=store, thumbnailer=None))
    r = c.get(
        f"/export/{meta['id']}",
        params={"format": "pdf", "base": "https://phish.example/x"},
    )
    assert r.status_code == 200
    assert not any("phish.example" in u for u in _read(r.content)[1])


def test_bad_requests(doc):
    store, meta = doc
    c = TestClient(mk_api(store=store, thumbnailer=None))
    assert c.get(f"/export/{meta['id']}", params={"format": "docx"}).status_code == 400
    assert (
        c.get(f"/export/{meta['id']}", params={"file": "private.txt"}).status_code
        == 404
    )
    assert c.get("/export/nope").status_code == 404


def test_the_owner_gate_covers_the_export(doc):
    store, meta = doc
    app = mk_app(store=store, authorizer=BasicAuth("owner", "pw"))
    c = TestClient(app)
    assert c.get(f"/api/export/{meta['id']}").status_code in (401, 403)


@pytest.fixture
def share_client(doc):
    store, meta = doc
    shares = Shares(store, hasher=ScryptHasher(n=2**4))
    rec = shares.create(
        meta["id"], include=["img/a.png", "clip.mp4"], exclude=[], expires="never"
    )
    app = mk_share_api(shares=shares, thumbnailer=None)
    return TestClient(app, base_url=f"http://{HOST}"), meta, rec


def test_share_pdf_has_only_the_shared_images(share_client):
    c, meta, rec = share_client
    link = f"http://{HOST}/{rec['token']}"
    r = c.get(
        f"/{rec['token']}/export/{meta['id']}", params={"format": "pdf", "base": link}
    )
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    text, links, images, _ = _read(r.content)
    assert images == 1
    assert f"{link}/raw/{meta['id']}/clip.mp4" in links
    assert "talk.mp3" not in text and "private.txt" not in text  # not shared, not named


def test_share_markdown_is_the_filtered_text(share_client):
    c, meta, rec = share_client
    r = c.get(f"/{rec['token']}/export/{meta['id']}", params={"format": "md"})
    assert r.status_code == 200
    assert "img/a.png" in r.text and "img/b.png" not in r.text
    assert "private.txt" not in r.text


def test_share_export_needs_a_live_link_and_a_shared_file(share_client):
    c, meta, rec = share_client
    assert c.get(f"/nosuchtokennosuchtoken00/export/{meta['id']}").status_code == 404
    assert (
        c.get(
            f"/{rec['token']}/export/{meta['id']}", params={"file": "private.txt"}
        ).status_code
        == 404
    )
    assert c.get(f"/{rec['token']}/export/other-doc").status_code == 404
