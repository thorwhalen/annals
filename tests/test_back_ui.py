"""The page's own Back: from a document to the group or filtered list it was opened from.

A home-screen app, or a tab opened from a link, has no browser Back button, so a reader who
opened a document from a group had no way back but the top navigation (2026-11-02). These
drive the real page in a browser at tablet size; they skip where Playwright or a browser is
missing (``ANNALS_TEST_BROWSER`` names an executable Playwright did not download).
"""

import base64
import re

import pytest

from annals.store import DocStore

TABLET = {"width": 810, "height": 1080}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="module")
def site(tmp_path_factory, serve):
    tmp = tmp_path_factory.mktemp("back")
    store = DocStore(tmp / "data")
    bees = store.publish(
        text="# Bees\n\nhives", title="Bees in winter", filename="bees.md"
    )
    folder = tmp / "Renders"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        (folder / name).write_bytes(PNG)
    renders = store.publish(folder, title="Renders")
    wasps = store.publish(
        text="# Wasps\n\nnests", title="Wasps alone", filename="wasps.md"
    )
    group = store.make_group("Pollinators", [bees["id"], renders["id"]])
    base = serve(store)
    return {
        "base": base,
        "group": group,
        "bees": bees,
        "renders": renders,
        "wasps": wasps,
    }


@pytest.fixture
def tablet(chromium):
    ctx = chromium.new_context(viewport=TABLET, has_touch=True, is_mobile=True)
    yield ctx.new_page()
    ctx.close()


def _back(page):
    return page.locator("nav.back a")


def test_back_from_a_document_returns_to_its_group(tablet, site):
    tablet.goto(f"{site['base']}/g/{site['group']['id']}")
    tablet.get_by_role("link", name="Bees in winter").first.click()
    tablet.wait_for_url(f"**/d/{site['bees']['id']}")
    assert _back(tablet).inner_text() == "‹ Pollinators"
    _back(tablet).click()
    tablet.wait_for_url(f"**/g/{site['group']['id']}")
    assert tablet.locator(".doc-head h2").inner_text() == "Pollinators"


def test_back_returns_to_the_search_as_it_was(tablet, site):
    tablet.goto(f"{site['base']}/?q=Wasps")
    tablet.get_by_role("link", name="Wasps alone").first.click()
    tablet.wait_for_url(f"**/d/{site['wasps']['id']}")
    assert _back(tablet).inner_text().endswith(", filtered")
    _back(tablet).click()
    tablet.wait_for_url("**/annals/?q=Wasps")
    assert tablet.locator("input[type=search]").input_value() == "Wasps"


def test_opened_from_outside_back_leads_to_the_list(tablet, site):
    tablet.goto(f"{site['base']}/d/{site['bees']['id']}")
    assert _back(tablet).inner_text().startswith("‹ ")
    _back(tablet).click()
    tablet.wait_for_url("**/annals/")


def test_a_file_viewer_keeps_the_way_back_to_the_group(tablet, site):
    rid = site["renders"]["id"]
    tablet.goto(f"{site['base']}/g/{site['group']['id']}")
    tablet.locator(f".list a[href$='/d/{rid}']").first.click()
    tablet.wait_for_url(f"**/d/{rid}")
    tablet.locator(f"a[href*='/d/{rid}?f=']").first.click()
    tablet.wait_for_url(re.compile(r"\?f=a\.png$"))
    tablet.get_by_role("button", name="Next").click()  # replaces the entry
    tablet.locator(".filenav a").click()  # up to the document: a step back
    tablet.wait_for_url(f"**/d/{rid}")
    assert _back(tablet).inner_text() == "‹ Pollinators"
