"""One file in the real page: a folder of PDFs (the reported case) is offered, made as a PDF by
default, and switches to Markdown or a web page; what it left out is said. Chromium, phone size."""

import pytest

from annals.render import Embedder, html_to_pdf, page_html
from annals.store import DocStore

PHONE = {"width": 390, "height": 844}


def _pdf(text: str) -> bytes:
    return html_to_pdf(page_html("S", f"<p>{text}</p>"), Embedder())


@pytest.fixture(scope="module")
def site(tmp_path_factory, serve):
    root = tmp_path_factory.mktemp("combine-ui")
    store = DocStore(root / "data")
    folder = root / "pdfs"
    folder.mkdir()
    (folder / "01-one.pdf").write_bytes(_pdf("alpha words"))
    (folder / "02-two.pdf").write_bytes(_pdf("beta words"))
    pdfs = store.publish(folder, title="pdf")
    clip = store.publish(text="x", filename="clip.mp4", title="Clip")
    group = store.make_group("Mixed", [pdfs["id"], clip["id"]])
    return {"base": serve(store), "pdfs": pdfs, "group": group}


@pytest.fixture
def phone(chromium):
    ctx = chromium.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    yield ctx.new_page()
    ctx.close()


def _open_one_file(page, url):
    page.goto(url)
    page.locator("button.result[data-result=file]").first.click()
    page.locator(".sheet .combine-panel").wait_for()


def test_a_folder_of_pdfs_combines_to_a_pdf_to_save_or_open(phone, site):
    _open_one_file(phone, f"{site['base']}/d/{site['pdfs']['id']}")
    panel = phone.locator(".sheet .combine-panel")
    panel.get_by_text("2 files").wait_for()
    assert "Could not combine" not in panel.inner_text()
    assert panel.locator("button[aria-pressed=true]").inner_text().strip() == "PDF"
    save = panel.get_by_role("link", name="Download PDF")
    assert save.get_attribute("download") == "pdf.pdf"
    assert save.get_attribute("href").startswith("blob:")


def test_the_same_pick_switches_to_markdown_text_and_a_web_page(phone, site):
    _open_one_file(phone, f"{site['base']}/d/{site['pdfs']['id']}")
    panel = phone.locator(".sheet .combine-panel")
    panel.get_by_role("button", name="Markdown").click()
    phone.locator(".sheet textarea.combine-text").wait_for()
    phone.wait_for_function(
        "document.querySelector('.sheet textarea.combine-text').value.includes('beta words')"
    )
    panel.get_by_role("button", name="Web page").click()
    panel.get_by_role("link", name="Download .html").wait_for()


def test_a_group_says_what_it_left_out_and_why(phone, site):
    _open_one_file(phone, f"{site['base']}/g/{site['group']['id']}")
    panel = phone.locator(".sheet .combine-panel")
    panel.get_by_text("1 file left out").wait_for()
    assert "clip.mp4" in panel.inner_text() and "video" in panel.inner_text()
