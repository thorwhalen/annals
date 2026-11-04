"""Pick, then choose what you want back: one way to act on documents, on a group and on one.

The owner could not tell whether to go to Share, Notebook, Actions or Combine (2026-11-04):
the same documents were ticked in three panels with different rules. Now a group's cards are
ticked (none ticked means all of them), and three buttons named after what they give, Links,
One file and Listen, open one sheet each on what is picked; a document page has the same
buttons, acting on it. These drive the real page in Chromium at phone size.
"""

import re

import pytest

from annals.overview import COMBINED_TAG
from annals.store import DocStore

PHONE = {"width": 390, "height": 844}


@pytest.fixture(scope="module")
def site(tmp_path_factory, serve):
    store = DocStore(tmp_path_factory.mktemp("pick") / "data")
    bees = store.publish(
        text="# Bees\n\nAbout hives.", title="Bees", filename="bees.md"
    )
    tides = store.publish(
        text="# Tides\n\nAbout the moon.", title="Tides", filename="tides.md"
    )
    group = store.make_group("Nature", [bees["id"], tides["id"]])
    base = serve(store, overviews=True)
    return {"base": base, "store": store, "group": group, "bees": bees, "tides": tides}


@pytest.fixture
def phone(chromium):
    ctx = chromium.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    yield ctx.new_page()
    ctx.close()


def _group(page, site):
    page.goto(f"{site['base']}/g/{site['group']['id']}")
    page.locator(".selbar").wait_for()


def _sheet_title(page):
    return page.locator(".sheet h3").inner_text()


def test_a_group_offers_the_three_results_and_none_of_the_old_buttons(phone, site):
    _group(phone, site)
    bar = phone.locator(".selbar")
    assert bar.locator(".sel-count").inner_text() == "All 2 documents"
    names = [b.inner_text().strip() for b in bar.locator("button.result").all()]
    assert names == ["Links", "One file", "Listen"]
    for old in ("Share", "Notebook", "Combine"):
        assert phone.get_by_role("button", name=old, exact=True).count() == 0


def test_ticking_narrows_what_the_buttons_act_on(phone, site):
    _group(phone, site)
    phone.get_by_label("Pick “Bees”").check()
    assert phone.locator(".sel-count").inner_text() == "1 of 2 picked"
    phone.get_by_role("button", name="Links").click()
    assert _sheet_title(phone).endswith("1 of 2 documents")
    phone.get_by_role("button", name=re.compile("^A link per document")).click()
    phone.get_by_role("button", name="Make 1 link").click()
    rows = phone.locator(".link-list li")
    rows.first.wait_for()
    assert (
        rows.count() == 1 and rows.first.locator(".link-title").inner_text() == "Bees"
    )


def test_back_closes_the_sheet_and_stays_on_the_group(phone, site):
    _group(phone, site)
    phone.get_by_role("button", name="One file").click()
    phone.locator(".sheet").wait_for()
    phone.go_back()
    phone.wait_for_function("!document.querySelector('.sheet')")
    assert phone.url.endswith(f"/g/{site['group']['id']}")
    assert phone.locator(".doc-head h2").inner_text() == "Nature"


def test_one_file_of_the_picked_documents_only(phone, site):
    _group(phone, site)
    phone.get_by_label("Pick “Tides”").check()
    phone.get_by_role("button", name="One file").click()
    text = phone.locator(".sheet textarea.combine-text")
    text.wait_for()
    phone.wait_for_function(
        "document.querySelector('.sheet textarea.combine-text').value.includes('moon')"
    )
    assert "hives" not in text.input_value()


def test_a_document_has_the_same_buttons_acting_on_it(phone, site):
    phone.goto(f"{site['base']}/d/{site['bees']['id']}")
    bar = phone.locator(".actionbar")
    bar.wait_for()
    names = [b.inner_text().strip() for b in bar.locator("button.result").all()]
    assert names == ["Links", "One file", "Listen"]
    phone.get_by_role("button", name="Links").click()
    assert _sheet_title(phone) == "Links · Bees"
    # for one document, a person is the likely reader: one link, with a password field
    assert phone.get_by_label("Password (optional)").count() == 1


def test_one_review_of_several_from_a_group(phone, site):
    _group(phone, site)
    phone.get_by_role("button", name="Listen").click()
    phone.get_by_role("button", name=re.compile("^One review of all 2")).wait_for()
    assert (
        "Nothing is spent until you press Make it"
        in phone.locator(".sheet").inner_text()
    )
    phone.get_by_role("button", name="Make it").click()
    phone.get_by_text("their combined document").wait_for()
    store = site["store"]
    combined = [m for m in store.list() if COMBINED_TAG in (m.get("tags") or [])]
    assert len(combined) == 1
    assert combined[0]["id"] in store.group(site["group"]["id"])["docs"]


def test_pick_targets_are_thumb_sized(phone, site):
    _group(phone, site)
    for el in (
        phone.locator(".pick-row > .pick").all()
        + phone.locator(".selbar button.result").all()
    ):
        box = el.bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44
