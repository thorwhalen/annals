"""Groups and documents share one list by date: a new document is never under the groups.

The bug this pins (2026-11-04): sorted newest first, the list drew every group (82 of them)
before any document, whatever their dates, so a document published a minute ago was nowhere
to be seen on a phone. Measured in a real browser at phone size (skips without one).
"""

from unittest.mock import patch

import pytest

from annals.store import DocStore

PHONE = {"width": 390, "height": 844}
OLD = "2026-01-0{}T10:00:00+00:00"


@pytest.fixture(scope="module")
def site(tmp_path_factory, serve):
    store = DocStore(tmp_path_factory.mktemp("order") / "data")
    with patch("annals.store.now_iso", return_value=OLD.format(1)):
        old = store.publish(text="# Old", title="An old note", filename="old.md")
        for i in range(30):
            store.make_group(f"Old group {i:02}", [old["id"]])
    with patch("annals.store.now_iso", return_value=OLD.format(5)):
        added = store.publish(text="# Added", title="Added later", filename="added.md")
        store.make_group("Grown group", [added["id"]])
    new = store.publish(text="# New", title="Just published", filename="new.md")
    return {"base": serve(store), "new": new}


@pytest.fixture
def phone(chromium):
    ctx = chromium.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    yield ctx.new_page()
    ctx.close()


def _titles(page):
    page.wait_for_selector(".list .card")
    return page.locator(".list .card .title").all_inner_texts()


def test_a_new_document_tops_the_list_above_older_groups(phone, site):
    phone.goto(site["base"] + "/")
    titles = _titles(phone)
    assert titles[0] == "Just published"
    box = phone.locator(".list .card").first.bounding_box()
    assert box["y"] + box["height"] <= PHONE["height"]  # on the first screen of a phone


def test_a_group_is_dated_by_its_newest_member(phone, site):
    phone.goto(site["base"] + "/")
    titles = _titles(phone)
    # "Grown group" was made with its member on day 5: above every day-1 group and note
    assert titles.index("Grown group") < titles.index("Old group 00")
    assert titles.index("Added later") < titles.index("An old note")


def test_oldest_first_puts_the_new_document_last(phone, site):
    phone.goto(site["base"] + "/")
    phone.locator("select[aria-label=Sort]").select_option("oldest")
    titles = _titles(phone)
    assert titles[0] in {"An old note"} | {f"Old group {i:02}" for i in range(30)}
    assert "Just published" not in titles[:10]
