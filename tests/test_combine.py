"""Combine many kinds of files into one md / html / pdf: every (kind, format) pair, the
registry seam, lazy and optional libraries, and the three surfaces (owner API, share, CLI)."""

import io
import json
import subprocess
import sys
from pathlib import Path

import pypdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from annals import combine as cb
from annals.__main__ import run
from annals.aggregate import TooLarge
from annals.api import mk_app
from annals.auth import no_auth
from annals.combine import (
    REGISTRY,
    NothingToCombine,
    Pair,
    Source,
    combine,
    html_body,
    register,
    supported,
)
from annals.render import Embedder, html_to_pdf, page_html
from annals.requirements import MissingDependency
from annals.share import ScryptHasher, Shares
from annals.share_api import mk_share_api
from annals.store import DocStore

# -- sample files ----------------------------------------------------------------------


def make_pdf(*page_texts: str) -> bytes:
    """A PDF with one page per text, made the way the server makes its own."""
    body = "".join(
        f'<div style="page-break-after: always"><p>{t}</p></div>' for t in page_texts
    )
    return html_to_pdf(page_html("Sample", body), Embedder())


def make_png(color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    return buf.getvalue()


def source_of(
    tmp_path: Path, files: dict, *, title="Doc", folder=None, name="doc"
) -> Source:
    """A document directory with ``files`` (str or bytes), as a Source."""
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(
            content if isinstance(content, bytes) else content.encode()
        )
    meta = {
        "id": name,
        "title": title,
        "kind": "folder"
        if (folder if folder is not None else len(files) > 1)
        else "md",
        "files": list(files),
        "sizes": {rel: (d / rel).stat().st_size for rel in files},
    }
    return Source(
        meta=meta,
        files=list(files),
        read_text=lambda rel: (d / rel).read_text(),
        open_path=lambda rel: d / rel,
    )


def pdf_text(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(data)).pages)


@pytest.fixture
def pdfs():
    return {
        "01-one.pdf": make_pdf("alpha page", "beta page"),
        "02-two.pdf": make_pdf("gamma page"),
    }


# -- to PDF: pdf+pdf is page concatenation; the rest is rendered ------------------------


def test_pdf_plus_pdf_to_pdf_concatenates_pages_with_bookmarks(tmp_path, pdfs):
    out = combine([source_of(tmp_path, pdfs, title="Set")], "pdf", title="All")
    assert (out.sections, out.skipped, out.ext, out.media_type) == (
        2,
        (),
        "pdf",
        "application/pdf",
    )
    reader = pypdf.PdfReader(io.BytesIO(out.data))
    assert len(reader.pages) == 3
    text = pdf_text(out.data)
    assert text.index("alpha") < text.index("beta") < text.index("gamma")
    assert [o.title for o in reader.outline] == ["Set/01-one.pdf", "Set/02-two.pdf"]
    assert (
        reader.outline[1].page is not None
        and reader.get_destination_page_number(reader.outline[1]) == 2
    )
    assert reader.metadata.title == "All"


def test_md_html_text_and_image_become_pdf_pages_in_order(tmp_path):
    src = source_of(
        tmp_path,
        {
            "1.md": "# Heading\n\nmarkdown body",
            "2.html": "<h1>Web</h1><p>html body</p><script>evil()</script>",
            "3.txt": "plain body",
        },
        title="Mixed",
    )
    out = combine([src], "pdf", title="T")
    # 3.txt is a companion of the pages, so it is not a section of its own
    assert out.sections == 2
    text = pdf_text(out.data)
    assert "markdown body" in text and "html body" in text and "evil" not in text
    texts = combine(
        [source_of(tmp_path, {"a.txt": "just text", "b.txt": "more text"}, name="t")],
        "pdf",
    )
    assert texts.sections == 2 and "just text" in pdf_text(texts.data)
    imgs = combine(
        [
            source_of(
                tmp_path,
                {"a.png": make_png(), "b.png": make_png((0, 0, 200))},
                name="i",
            )
        ],
        "pdf",
    )
    assert imgs.sections == 2 and len(pypdf.PdfReader(io.BytesIO(imgs.data)).pages) == 2


def test_markdown_images_of_the_document_are_inside_its_pdf(tmp_path):
    src = source_of(
        tmp_path,
        {"r.md": "# R\n\n![fig](fig.png)\n", "fig.png": make_png()},
        title="R",
        folder=True,
    )
    data = combine([src], "pdf").data
    assert (
        pypdf.PdfReader(io.BytesIO(data)).pages[0].images
    )  # the figure is embedded, not linked


# -- to Markdown -----------------------------------------------------------------------


def test_every_kind_to_markdown(tmp_path):
    pdf = make_pdf("extracted words")
    src = [
        source_of(tmp_path, {"a.md": "# A\n\nmd words"}, name="a", title="A"),
        source_of(
            tmp_path,
            {"b.html": "<h1>Bee</h1><p>html <b>words</b></p><script>x()</script>"},
            name="b",
            title="B",
        ),
        source_of(tmp_path, {"c.txt": "plain `tick` words"}, name="c", title="C"),
        source_of(tmp_path, {"d.pdf": pdf}, name="d", title="D"),
    ]
    out = combine(src, "md", title="Bundle")
    text = out.data.decode()
    assert (
        out.sections == 4
        and out.ext == "md"
        and text.startswith("# Bundle\n\n**Contents**")
    )
    assert "md words" in text and "extracted words" in text
    assert "words**" in text and "x()" not in text  # html -> markdown, scripts gone
    assert "```\nplain `tick` words\n```" in text  # text -> a code block
    assert "## a.md" in text and "## d.pdf" in text


def test_pdf_pages_with_hashes_do_not_become_headings(tmp_path):
    out = combine(
        [source_of(tmp_path, {"p.pdf": make_pdf("# not a heading")}, name="p")], "md"
    )
    assert "\n# not a heading" not in out.data.decode().split("## p.pdf")[1]


def test_image_to_markdown_is_unsupported_and_says_what_is(tmp_path):
    src = [
        source_of(tmp_path, {"a.md": "words"}, name="a"),
        source_of(tmp_path, {"p.png": make_png()}, name="p"),
    ]
    out = combine(src, "md")
    assert out.sections == 1
    (skip,) = out.skipped
    assert (
        skip.label == "p.png"
        and "Markdown" in skip.reason
        and "markdown, html, text and PDF" in skip.reason
    )


# -- to html -----------------------------------------------------------------------------


def test_every_kind_to_one_web_page(tmp_path):
    src = [
        source_of(
            tmp_path,
            {"a.md": "# A\n\nmd words\n\n![x](x.png)", "x.png": make_png()},
            name="a",
            title="A",
            folder=True,
        ),
        source_of(
            tmp_path,
            {
                "b.html": "<h1>Bee</h1><p onclick='x()'>html words</p><img src='http://evil/x.png' alt='ext'>"
            },
            name="b",
            title="B",
        ),
        source_of(tmp_path, {"c.txt": "plain <b>words</b>"}, name="c", title="C"),
        source_of(tmp_path, {"d.pdf": make_pdf("pdf words")}, name="d", title="D"),
        source_of(tmp_path, {"e.png": make_png()}, name="e", title="E"),
    ]
    out = combine(src, "html", title="Page")
    page = out.data.decode()
    assert out.sections == 5 and out.media_type.startswith("text/html")
    for words in ("md words", "html words", "pdf words"):
        assert words in page
    assert "&lt;b&gt;words" in page  # text is shown, not interpreted
    assert (
        page.count("data:image/") >= 2
    )  # the document's figure and the image file, inline
    assert "onclick" not in page and "evil" not in page  # nothing live, no remote image
    assert "Content-Security-Policy" in page and '<a href="#s1">' in page
    # headings of embedded files sit below the section's own
    assert "<h1>Bee" not in page and "<h3>Bee" in page


def test_html_body_keeps_words_and_drops_everything_that_runs():
    dirty = (
        "<head><title>t</title><style>p{}</style></head><body onload='x()'>"
        "<script>alert(1)</script><iframe src=//e></iframe><form><input></form>"
        "<a href='javascript:alert(1)'>bad</a><a href='https://ok.example/p'>good</a>"
        "<div class=c id=i><p>text<br>more<ul><li>one</ul></div><img src='x.png' alt='A'>"
    )
    out = html_body(dirty)
    assert (
        "alert" not in out
        and "iframe" not in out
        and "<form" not in out
        and "onload" not in out
    )
    assert "<a>bad</a>" in out and '<a href="https://ok.example/p">good</a>' in out
    assert "class=" not in out and "id=" not in out
    assert out.count("<ul>") == out.count("</ul>") and out.count("<div>") == out.count(
        "</div>"
    )  # balanced
    assert "<img" not in out and out.endswith(
        "</div>A"
    )  # an image nobody vouched for: its alt text
    assert html_body("<div><p>unclosed") == "<div><p>unclosed</p></div>"


# -- what cannot go in, and what is damaged ------------------------------------------------


def test_nothing_usable_says_what_the_format_is_made_from(tmp_path):
    video = source_of(tmp_path, {"clip.mp4": b"\x00\x00"}, name="v", title="V")
    for fmt, label in (("pdf", "PDF"), ("html", "web page"), ("md", "Markdown")):
        with pytest.raises(NothingToCombine) as e:
            combine([video], fmt)
        msg = str(e.value)
        assert "video" in msg and label in msg and "made from" in msg
    with pytest.raises(NothingToCombine, match="hold no files"):
        combine([], "md")


def test_unknown_format_is_a_value_error(tmp_path):
    with pytest.raises(ValueError, match="format must be one of md, html, pdf"):
        combine([source_of(tmp_path, {"a.md": "x"})], "docx")


def test_a_damaged_or_protected_pdf_is_left_out_not_fatal(tmp_path, pdfs):
    locked = pypdf.PdfWriter()
    locked.add_blank_page(100, 100)
    locked.encrypt("secret")
    buf = io.BytesIO()
    locked.write(buf)
    files = {
        **pdfs,
        "03-bad.pdf": b"%PDF-1.4 not really",
        "04-locked.pdf": buf.getvalue(),
    }
    for fmt in ("pdf", "md"):
        out = combine([source_of(tmp_path, files, name=f"d{fmt}")], fmt)
        assert out.sections == 2
        reasons = {s.label.split("/")[-1]: s.reason for s in out.skipped}
        assert (
            "damaged" in reasons["03-bad.pdf"]
            and "password" in reasons["04-locked.pdf"]
        )


def test_a_scanned_pdf_has_no_text_to_extract(tmp_path):
    blank = pypdf.PdfWriter()
    blank.add_blank_page(100, 100)
    buf = io.BytesIO()
    blank.write(buf)
    src = [
        source_of(tmp_path, {"s.pdf": buf.getvalue()}, name="s"),
        source_of(tmp_path, {"a.md": "x"}, name="a"),
    ]
    out = combine(src, "md")
    assert out.sections == 1 and "no text" in out.skipped[0].reason


def test_size_caps(tmp_path, pdfs):
    with pytest.raises(TooLarge, match="bytes of text"):
        combine(
            [source_of(tmp_path, {"a.md": "x" * 50}, name="a")], "md", max_text_bytes=10
        )
    with pytest.raises(TooLarge, match="bytes of files"):
        combine([source_of(tmp_path, pdfs)], "pdf", max_input_bytes=100)


# -- the seam: a new pair is one decorated function -------------------------------------------


def test_a_new_pair_registers_without_touching_anything_else(tmp_path):
    registry = dict(REGISTRY)
    try:

        @register("file", "md")
        def _unknown_to_md(item, ctx):
            return "custom: " + item.rel

        out = combine([source_of(tmp_path, {"x.weird": "data"}, name="w")], "md")
        assert "custom: x.weird" in out.data.decode()
        assert "file" in supported()["md"]["kinds"]
    finally:
        REGISTRY.clear()
        REGISTRY.update(registry)
    # or per call, leaving the global table alone
    own = {("file", "md"): Pair("file", "md", lambda item, ctx: "local")}
    assert (
        b"local"
        in combine(
            [source_of(tmp_path, {"x.weird": "d"}, name="w2")], "md", registry=own
        ).data
    )


def test_supported_lists_kinds_per_format():
    s = supported()
    assert set(s) == {"md", "html", "pdf"}
    assert set(s["pdf"]["kinds"]) == {"md", "html", "text", "pdf", "image"}
    assert set(s["md"]["kinds"]) == {
        "md",
        "html",
        "text",
        "pdf",
    }  # no image -> markdown


# -- heavy libraries are lazy and optional --------------------------------------------------------


def test_importing_the_package_loads_no_heavy_library():
    code = (
        "import sys, annals.combine, annals.render, annals.export;"
        "bad = [m for m in ('weasyprint','pypdf','pdfdol','markdownify','markdown_it','PIL') if m in sys.modules];"
        "print(bad)"
    )
    out = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]", out.stdout


def test_a_missing_library_is_named_with_the_fix_before_any_work(
    tmp_path, monkeypatch, pdfs
):
    ran = []
    real = REGISTRY[("pdf", "pdf")]
    monkeypatch.setitem(
        REGISTRY,
        ("pdf", "pdf"),
        Pair("pdf", "pdf", lambda i, c: ran.append(1) or real.fn(i, c), real.requires),
    )
    import annals.requirements as req

    monkeypatch.setattr(
        req, "missing_modules", lambda mods: [m for m in mods if m == "pypdf"]
    )
    with pytest.raises(MissingDependency) as e:
        combine([source_of(tmp_path, pdfs)], "pdf")
    msg = str(e.value)
    assert (
        "Combining into a PDF needs pypdf" in msg and "pip install 'annals[pdf]'" in msg
    )
    assert ran == []  # nothing was converted first


# -- the owner's API ---------------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


@pytest.fixture
def owner(store):
    return TestClient(mk_app(store=store, authorizer=no_auth), follow_redirects=False)


@pytest.fixture
def folder_of_pdfs(store, tmp_path, pdfs):
    d = tmp_path / "pdf"
    d.mkdir()
    for name, data in pdfs.items():
        (d / name).write_bytes(data)
    return store.publish(d, title="pdf")


def test_the_report_nine_pdfs_in_a_folder_document_combine_to_pdf_and_md(
    owner, folder_of_pdfs
):
    """The reported case: a document that is a folder of PDFs, 'Combine' said no markdown."""
    doc = folder_of_pdfs["id"]
    pdf = owner.get("/annals/api/aggregate", params={"doc": doc, "format": "pdf"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert (
        pdf.headers["x-annals-sections"] == "2"
        and "x-annals-skipped" not in pdf.headers
    )
    assert pdf.headers["content-disposition"].startswith("inline")
    assert len(pypdf.PdfReader(io.BytesIO(pdf.content)).pages) == 3
    dl = owner.get(
        "/annals/api/aggregate", params={"doc": doc, "format": "pdf", "download": 1}
    )
    assert dl.headers["content-disposition"].startswith(
        'attachment; filename="pdf.pdf"'
    )
    md = owner.get("/annals/api/aggregate", params={"doc": doc})  # default format
    assert md.status_code == 200 and "gamma page" in md.text
    html = owner.get("/annals/api/aggregate", params={"doc": doc, "format": "html"})
    assert (
        html.status_code == 200 and "sandbox" in html.headers["content-security-policy"]
    )
    assert "alpha page" in html.text


def test_groups_endpoint_takes_a_format_and_reports_what_it_left_out(
    owner, store, folder_of_pdfs
):
    clip = store.publish(text="not video", filename="clip.mp4", title="Clip")
    note = store.publish(text="# Note\nwords", title="Note")
    g = store.make_group("Mixed", [folder_of_pdfs["id"], clip["id"], note["id"]])
    r = owner.get(f"/annals/api/groups/{g['id']}/aggregate", params={"format": "pdf"})
    assert r.status_code == 200 and r.headers["x-annals-sections"] == "3"
    from urllib.parse import unquote

    skipped = json.loads(unquote(r.headers["x-annals-skipped"]))
    assert skipped["n"] == 1 and skipped["listed"][0]["label"] == "clip.mp4"
    assert "video" in skipped["listed"][0]["reason"]


def test_nothing_combinable_is_404_with_the_message_and_bad_format_400(owner, store):
    clip = store.publish(text="not video", filename="clip.mp4")
    r = owner.get("/annals/api/aggregate", params={"doc": clip["id"], "format": "pdf"})
    assert r.status_code == 404 and "PDF is made from" in r.json()["detail"]
    assert (
        owner.get(
            "/annals/api/aggregate", params={"doc": clip["id"], "format": "docx"}
        ).status_code
        == 400
    )


def test_missing_library_is_501_with_the_install_hint(
    owner, folder_of_pdfs, monkeypatch
):
    import annals.requirements as req

    monkeypatch.setattr(
        req, "missing_modules", lambda mods: [m for m in mods if m == "weasyprint"]
    )
    r = owner.get(
        "/annals/api/aggregate", params={"doc": folder_of_pdfs["id"], "format": "pdf"}
    )
    assert r.status_code == 200  # PDFs alone do not need it
    store = owner.app.state.store
    note = store.publish(text="# N\nbody", title="N")
    r = owner.get("/annals/api/aggregate", params={"doc": note["id"], "format": "pdf"})
    assert r.status_code == 501 and "pip install 'annals[pdf]'" in r.json()["detail"]


def test_formats_endpoint(owner):
    body = owner.get("/annals/api/combine/formats").json()
    assert set(body["formats"]) == {"md", "html", "pdf"}
    assert "image" in body["formats"]["pdf"]["kinds"]


def test_the_listing_says_which_kinds_a_document_holds(owner, store, folder_of_pdfs):
    g = store.make_group("G", [folder_of_pdfs["id"]])
    items = owner.get(f"/annals/api/groups/{g['id']}").json()["items"]
    assert items[0]["held_kinds"] == ["pdf"] and items[0]["has_markdown"] is False


def test_pdf_jobs_share_the_concurrency_limit(
    owner, store, folder_of_pdfs, monkeypatch
):
    import annals.export as ex

    note = store.publish(text="# Plain\nwords", title="Plain")
    monkeypatch.setattr(ex, "_pdf_active", ex.PDF_CONCURRENCY)
    pdf = {"doc": folder_of_pdfs["id"], "format": "pdf"}
    r = owner.get("/annals/api/aggregate", params=pdf)
    assert r.status_code == 503 and "retry-after" in r.headers
    # reading the text of PDFs is heavy too; plain text is not, and does not wait for them
    assert (
        owner.get(
            "/annals/api/aggregate", params={"doc": folder_of_pdfs["id"]}
        ).status_code
        == 503
    )
    assert (
        owner.get("/annals/api/aggregate", params={"doc": note["id"]}).status_code
        == 200
    )


# -- the share's endpoint: only what the link includes -------------------------------------------------


def test_share_combines_only_included_files_to_pdf(store, folder_of_pdfs):
    shares = Shares(store, hasher=ScryptHasher(n=2**4))
    secret = store.publish(text="# Secret", title="Secret")
    g = store.make_group("Pair", [folder_of_pdfs["id"], secret["id"]])
    rec = shares.create(g["id"], include=[folder_of_pdfs["id"]])
    client = TestClient(
        mk_share_api(shares=shares, thumbnailer=None), follow_redirects=False
    )
    r = client.get(f"/{rec['token']}/aggregate", params={"format": "pdf"})
    assert r.status_code == 200 and r.headers["x-annals-sections"] == "2"
    assert "Secret" not in pdf_text(r.content)
    assert set(client.get(f"/{rec['token']}/combine/formats").json()["formats"]) == {
        "md",
        "html",
        "pdf",
    }
    assert (
        client.get(f"/{rec['token']}/aggregate", params={"format": "html"}).status_code
        == 200
    )


# -- the CLI ------------------------------------------------------------------------------------------------


def test_cli_aggregate_to_a_pdf_file_and_to_stdout(
    tmp_path, monkeypatch, folder_of_pdfs, store
):
    monkeypatch.setenv("ANNALS_TARGET", str(store.target.root))
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    doc = folder_of_pdfs["id"]
    dest = tmp_path / "all.pdf"
    out, err = io.StringIO(), io.StringIO()
    assert (
        run(
            ["aggregate", doc, "--format", "pdf", "--output", str(dest)],
            out=out,
            err=err,
        )
        == 0
    )
    assert json.loads(out.getvalue()) == {
        "path": str(dest),
        "format": "pdf",
        "sections": 2,
        "bytes": dest.stat().st_size,
        "skipped": 0,
    }
    assert len(pypdf.PdfReader(str(dest)).pages) == 3
    out = io.StringIO()
    assert (
        run(["aggregate", doc], out=out, err=io.StringIO()) == 0
    )  # markdown on stdout, as before
    assert "gamma page" in out.getvalue()
    out = io.StringIO()
    assert run(["aggregate", doc, "--format", "html"], out=out, err=io.StringIO()) == 0
    assert out.getvalue().startswith("<!doctype html>")


def test_cli_errors_are_one_line(tmp_path, monkeypatch, folder_of_pdfs, store):
    monkeypatch.setenv("ANNALS_TARGET", str(store.target.root))
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    err = io.StringIO()
    assert (
        run(
            ["aggregate", folder_of_pdfs["id"], "--format", "pdf"],
            out=io.StringIO(),
            err=err,
        )
        == 1
    )
    assert "--output" in err.getvalue()
    err = io.StringIO()
    assert (
        run(
            ["aggregate", folder_of_pdfs["id"], "--format", "docx"],
            out=io.StringIO(),
            err=err,
        )
        == 1
    )
    assert "format must be one of" in err.getvalue()
    clip = store.publish(text="x", filename="clip.mp4")
    err = io.StringIO()
    assert (
        run(["aggregate", clip["id"], "--format", "md"], out=io.StringIO(), err=err)
        == 1
    )
    assert "video" in err.getvalue()


# -- found by the adversarial review: each one a case that once went wrong ---------------------


def test_a_share_gets_an_svg_as_raw_sends_it_filtered(store, tmp_path):
    secret = store.publish(text="# Private", title="Private")
    d = tmp_path / "fig"
    d.mkdir()
    (d / "fig.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg"><text>SECRETSVG {secret["id"]}</text></svg>'
    )
    (d / "n.md").write_text("# Note\n\n![f](fig.svg)")
    doc = store.publish(d, title="Fig")
    shares = Shares(store, hasher=ScryptHasher(n=2**4))
    g = store.make_group("G", [doc["id"], secret["id"]])
    rec = shares.create(g["id"], include=[doc["id"]])
    client = TestClient(
        mk_share_api(shares=shares, thumbnailer=None), follow_redirects=False
    )
    raw = client.get(f"/{rec['token']}/raw/{doc['id']}/fig.svg").text
    assert secret["id"] not in raw
    page = client.get(f"/{rec['token']}/aggregate", params={"format": "html"}).text
    import base64
    import re

    for b64 in re.findall(r"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)", page):
        assert secret["id"] not in base64.b64decode(b64).decode()
    assert "data:image/svg+xml" in page  # it is shown, filtered


def test_the_sanitiser_keeps_content_after_void_elements_forms_and_missing_end_tags():
    assert html_body("<p>a</p><embed src=x><p>b</p>") == "<p>a</p><p>b</p>"
    assert "Whole page" in html_body("<form id=f><h1>Whole page</h1><input></form>")
    assert (
        html_body("<html><head><meta charset=x><body><p>body text</p></html>")
        == "<p>body text</p>"
    )
    assert 'colspan="100"' in html_body(
        '<table><tr><td colspan="100000">x</td></tr></table>'
    )
    assert "colspan" not in html_body('<td colspan="javascript:1">x</td>')
    deep = html_body("<div>" * 5000 + "x")
    assert (
        deep.count("<div>") == cb.MAX_HTML_DEPTH
        and deep.count("</div>") == cb.MAX_HTML_DEPTH
    )


def test_annals_file_in_the_text_is_not_turned_into_an_image(tmp_path):
    src = [
        source_of(
            tmp_path, {"a.html": '<p>see "annals-file:0" here</p>'}, name="a", title="A"
        ),
        source_of(tmp_path, {"b.png": make_png()}, name="b", title="B"),
    ]
    page = combine(src, "html").data.decode()
    assert 'see "annals-file:0" here' in page and page.count("data:image/png") == 1


def test_one_bad_file_never_sinks_the_bundle(tmp_path, pdfs):
    # a PDF that opens but whose pages cannot be joined, and html too deep to convert
    good = pdfs["01-one.pdf"]
    broken = (
        good.replace(b"/Type /Pages", b"/Type /Nope")
        if b"/Type /Pages" in good
        else good[: len(good) // 2]
    )
    files = {"01.pdf": good, "02.pdf": broken, "03.pdf": pdfs["02-two.pdf"]}
    out = combine([source_of(tmp_path, files, name="p")], "pdf")
    assert out.sections >= 2
    deep = "<div>" * 20000 + "words" + "</div>" * 20000
    src = [
        source_of(tmp_path, {"d.html": deep}, name="d"),
        source_of(tmp_path, {"a.md": "fine"}, name="m"),
    ]
    for fmt in ("md", "pdf", "html"):
        assert combine(src, fmt).sections >= 1


def test_a_missing_library_leaves_out_only_the_kind_that_needs_it(
    tmp_path, monkeypatch
):
    import annals.requirements as req

    monkeypatch.setattr(
        req, "missing_modules", lambda mods: [m for m in mods if m == "markdownify"]
    )
    src = [
        source_of(tmp_path, {"a.md": "kept"}, name="a"),
        source_of(tmp_path, {"b.html": "<p>x</p>"}, name="b"),
    ]
    out = combine(src, "md")
    assert out.sections == 1 and "kept" in out.data.decode()
    assert (
        "markdownify" in out.skipped[0].reason
        and "pip install" in out.skipped[0].reason
    )
    with pytest.raises(MissingDependency):  # nothing left but what needs it
        combine(src[1:], "md")


def test_renderings_of_a_markdown_file_are_not_sections_of_their_own(tmp_path):
    src = source_of(
        tmp_path,
        {
            "report.md": "# R\n\nwords",
            "report.html": "<h1>R</h1><p>words</p>",
            "report.pdf": make_pdf("words"),
            "other.pdf": make_pdf("more"),
        },
        title="Rep",
    )
    out = combine([src], "md")
    assert out.sections == 2  # report.md and other.pdf; report.html/.pdf render the md


def test_a_large_text_file_is_left_out_not_fatal(tmp_path):
    big = "x" * (cb.MAX_TEXT_FILE_BYTES + 1)
    src = [
        source_of(tmp_path, {"big.jsonl": big}, name="b", title="Big"),
        source_of(tmp_path, {"a.md": "ok"}, name="a"),
    ]
    out = combine(src, "md", max_text_bytes=None)
    assert out.sections == 1 and "too large" in out.skipped[0].reason


def test_markdown_pages_of_a_folder_do_not_each_list_the_folders_media(tmp_path):
    src = source_of(
        tmp_path,
        {"a.md": "# A", "b.md": "# B", "clip.mp4": b"\0\0", "x.png": make_png()},
        title="F",
        folder=True,
    )
    page = combine([src], "html").data.decode()
    assert "More in this document" not in page and page.count("<h2>") >= 3


def test_the_skipped_header_stays_small(tmp_path):
    from annals.combine import Skipped, skipped_header

    many = [Skipped("é" * 100, "ü" * 300) for _ in range(40)]
    header = skipped_header(many)
    assert len(header) < 3500 and header.isascii() and json.loads(header)["n"] == 40


def test_a_huge_pdf_is_not_read_for_its_text(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "MAX_TEXT_PAGES", 1)
    out = combine(
        [
            source_of(tmp_path, {"a.pdf": make_pdf("one", "two")}, name="a"),
            source_of(tmp_path, {"b.md": "x"}, name="b"),
        ],
        "md",
    )
    assert out.sections == 1 and "too many" in out.skipped[0].reason
