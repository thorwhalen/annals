"""An html page carries its own Download PDF button, and its PDF beside it (annals.pagepdf)."""

import pytest

from annals.pagepdf import add_button, attach_pdf, declared_pdf, strip_button
from annals.store import DocStore


def _bytes(store, doc_id, rel):
    """A file of a document, as the text a stub PDF is (the store reads text)."""
    return store.read_text(doc_id, rel).encode()


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


def _page(tmp_path, body="<p>hello</p>", head="<title>Guide</title>", name="guide.html"):
    p = tmp_path / "src" / name
    p.parent.mkdir(exist_ok=True)
    p.write_text(f"<!doctype html><html><head>{head}</head><body>{body}</body></html>")
    return p


def test_an_html_page_gets_its_pdf_and_a_button_to_it(store, tmp_path, fake_pdf):
    meta = store.publish(_page(tmp_path))
    assert meta["files"] == ["guide.html", "guide.pdf"] and meta["main"] == "guide.html"
    assert _bytes(store, meta["id"], "guide.pdf") == fake_pdf
    page = store.read_text(meta["id"])
    assert 'id="annals-pdf"' in page and 'href="guide.pdf" download' in page
    # agents find it in the head too; annals' own link is not the page declaring one
    assert '<link rel="alternate" type="application/pdf" href="guide.pdf">' in page
    assert declared_pdf(page) is None
    assert "@media print{#annals-pdf{display:none" in page  # never printed itself
    assert page.index('id="annals-pdf"') > page.index("<body>")


def test_the_page_is_printed_without_the_button(store, tmp_path):
    printed = []

    def renderer(path):
        printed.append(path.read_text())
        return b"%PDF"

    store.publish(_page(tmp_path), pdf_renderer=renderer)
    assert "hello" in printed[0] and "annals-pdf" not in printed[0]


def test_a_page_that_declares_its_pdf_is_not_printed(store, tmp_path):
    head = '<link rel="alternate" type="application/pdf" href="https://x.org/g.pdf">'
    meta = store.publish(_page(tmp_path, head=head), pdf_renderer=pytest.fail)
    assert meta["files"] == ["guide.html"]
    assert 'href="https://x.org/g.pdf" download' in store.read_text(meta["id"])


def test_a_pdf_already_beside_the_page_is_used(store, tmp_path):
    page = _page(tmp_path)
    (page.parent / "guide.pdf").write_bytes(b"%PDF mine")
    meta = store.publish(page.parent, pdf_renderer=pytest.fail)
    assert _bytes(store, meta["id"], "guide.pdf") == b"%PDF mine"
    assert 'href="guide.pdf"' in store.read_text(meta["id"])


@pytest.mark.parametrize(
    "body, attr",
    [
        ('<a href="g.pdf" data-annals-pdf>My PDF</a>', ""),  # its own button
        ("<p>x</p>", ' data-annals-pdf="off"'),  # opted out
    ],
)
def test_a_page_with_its_own_button_or_opting_out_is_left_alone(store, tmp_path, body, attr):
    src = _page(tmp_path, body=body)
    src.write_text(src.read_text().replace("<body>", f"<body{attr}>"))
    meta = store.publish(src, pdf_renderer=pytest.fail)
    assert meta["files"] == ["guide.html"] and store.read_text(meta["id"]) == src.read_text()


def test_pdf_false_leaves_the_page_as_it_is(store, tmp_path):
    src = _page(tmp_path)
    meta = store.publish(src, pdf=False, pdf_renderer=pytest.fail)
    assert meta["files"] == ["guide.html"] and store.read_text(meta["id"]) == src.read_text()


def test_without_a_printer_the_button_prints(store, tmp_path):
    def broken(path):
        raise RuntimeError("no chromium here")

    meta = store.publish(_page(tmp_path), pdf_renderer=broken)
    page = store.read_text(meta["id"])
    assert meta["files"] == ["guide.html"] and "window.print()" in page
    assert 'type="application/pdf"' not in page


def test_markdown_and_text_publish_no_pdf(store):
    meta = store.publish(text="# Notes\n\nplain", title="Notes")
    assert meta["files"] == ["document.md"]


def test_a_new_version_is_printed_again_with_one_button(store, tmp_path):
    first = store.publish(_page(tmp_path, body="<p>v1</p>"))
    # the new version starts from the stored page, button and all
    new = tmp_path / "v2" / "guide.html"
    new.parent.mkdir()
    new.write_text(store.read_text(first["id"]).replace("v1", "v2"))
    printed = []
    store.publish(new, replace=first["id"], pdf_renderer=lambda p: printed.append(p.read_text()) or b"%PDF v2")
    page = store.read_text(first["id"])
    assert "annals-pdf" not in printed[0] and "v2" in printed[0]
    assert page.count('id="annals-pdf"') == 1 and page.count('type="application/pdf"') == 1
    assert _bytes(store, first["id"], "guide.pdf") == b"%PDF v2"


def test_a_share_of_the_page_offers_its_pdf_as_referenced(store, tmp_path):
    from annals.share import Shares

    meta = store.publish(_page(tmp_path))
    files = {f["rel"]: f for f in Shares(store).resources(meta["id"])["files"]}
    assert files["guide.pdf"]["referenced"]


def test_add_button_without_head_or_body():
    out = add_button("<p>bare</p>", "a.pdf")
    assert out.startswith("<!--annals-pdf-->") and out.endswith("<p>bare</p>")
    assert strip_button(out) == "<p>bare</p>"


def test_attach_pdf_in_a_subfolder(tmp_path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text("<body><p>x</p></body>")
    files = attach_pdf(tmp_path, "site/index.html", ["site/index.html"], pdf_renderer=lambda p: b"%PDF")
    assert files == ["site/index.html", "site/index.pdf"]
    assert 'href="index.pdf"' in (tmp_path / "site" / "index.html").read_text()


def test_print_with_chromium_prints_a_real_pdf(tmp_path):
    """The default printer, for real, where Playwright and its Chromium are installed."""
    pytest.importorskip("pdfdol.chromium")
    pytest.importorskip("playwright")
    from annals.pagepdf import print_with_chromium

    page = tmp_path / "p.html"
    page.write_text('<body><h1>Real</h1><img loading="lazy" src="x.png"></body>')
    try:
        pdf = print_with_chromium(page)
    except Exception as e:  # no browser downloaded
        pytest.skip(f"no Chromium: {e}")
    assert pdf.startswith(b"%PDF") and not (tmp_path / ".annals-print-p.html").exists()


def test_the_button_is_not_content_when_combined():
    from annals.combine import html_body

    page = add_button("<html><head></head><body><h1>Hi</h1></body></html>", "x.pdf")
    assert html_body(page) == "<h1>Hi</h1>"
