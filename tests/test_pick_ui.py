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
    # asking only queues it: the combined document is made when a worker starts the job
    assert not [m for m in store.list() if COMBINED_TAG in (m.get("tags") or [])]
    assert "made when the review starts" in phone.locator(".sheet").inner_text()


def test_pick_targets_are_thumb_sized(phone, site):
    _group(phone, site)
    for el in (
        phone.locator(".pick-row > .pick").all()
        + phone.locator(".selbar button.result").all()
    ):
        box = el.bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44


@pytest.mark.parametrize("close", ["back button", "escape", "scrim"])
def test_closing_a_sheet_keeps_the_picks(phone, site, close):
    _group(phone, site)
    phone.get_by_label("Pick “Bees”").check()
    phone.get_by_role("button", name="One file").click()
    phone.locator(".sheet").wait_for()
    phone.evaluate("window.__samePage = true")  # gone if the page is drawn again from scratch
    if close == "back button":
        phone.locator(".sheet-back").click()
    elif close == "escape":
        phone.keyboard.press("Escape")
    else:
        phone.locator(".sheet-scrim").click(position={"x": 10, "y": 10})
    phone.wait_for_function("!document.querySelector('.sheet')")
    phone.wait_for_timeout(300)  # a stray popstate would redraw the group by now
    assert phone.get_by_label("Pick “Bees”").is_checked()
    assert phone.locator(".sel-count").inner_text().startswith("1 of ")
    assert phone.url.endswith(f"/g/{site['group']['id']}")


def test_a_reload_with_a_sheet_open_leaves_no_dead_back(phone, site):
    phone.goto(f"{site['base']}/")
    phone.locator(f"a.card[href$='/g/{site['group']['id']}']").click()
    phone.locator(".selbar").wait_for()
    phone.get_by_role("button", name="Links").click()
    phone.locator(".sheet").wait_for()
    phone.reload()
    phone.locator(".selbar").wait_for()
    phone.go_back()
    phone.wait_for_function("location.pathname.endsWith('/annals/')", timeout=5000)


def test_the_interactive_version_leaves_room_for_the_buttons(chromium, site):
    store = site["store"]
    doc = store.publish(
        text="# Page\n\nx",
        title="With artifact",
        filename="p.md",
        artifact="https://claude.ai/public/artifacts/abc",
    )
    ctx = chromium.new_context(viewport={"width": 360, "height": 780}, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    page.goto(f"{site['base']}/d/{doc['id']}")
    page.locator(".actionbar button.result").first.wait_for()
    for el in page.locator(".actionbar button.result, .actionbar .menu-btn, .actionbar .view-toggle").all():
        assert el.bounding_box()["width"] >= 44
    ctx.close()


def test_a_document_links_to_the_groups_it_is_in(phone, site):
    """Reached by a pasted link, a document still leads to its group (2026-11-09)."""
    phone.goto(f"{site['base']}/d/{site['bees']['id']}")
    chip = phone.locator(".in-groups a.group-chip")
    chip.wait_for()
    assert phone.locator(".in-groups").inner_text().startswith("In group")
    assert chip.inner_text() == "Nature"
    assert chip.bounding_box()["height"] >= 44
    chip.click()
    phone.locator(".selbar").wait_for()
    assert phone.url.endswith(f"/g/{site['group']['id']}")


def test_the_links_sheet_hands_own_agents_the_private_address(chromium, site):
    """The owner made public links only so their own agents could read (2026-11-09)."""
    ctx = chromium.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    try:
        _group(page, site)
        page.locator(".pick input").first.check()
        page.locator(".selbar").get_by_role("button", name="Links").click()
        btn = page.locator(".agent-note .copy-btn")
        assert btn.inner_text().strip() == "Copy the address"  # one picked: that document's
        btn.click()
        page.wait_for_function("b => b.getAttribute('data-state') === 'copied'", arg=btn.element_handle())
        copied = page.evaluate("navigator.clipboard.readText()")
        assert re.fullmatch(rf".*/d/({site['bees']['id']}|{site['tides']['id']})", copied)
        assert "/shared/" not in copied
    finally:
        ctx.close()


# -- Select on the main list, and Add to group… (thorwhalen/annals#50) ---------------


def _main_list(page, site):
    page.goto(f"{site['base']}/")
    page.locator("a.card").first.wait_for()


def _select(page):
    page.get_by_role("button", name="Select", exact=True).click()
    page.locator(".pick-row").first.wait_for()


def _open_add_to_group(page):
    page.locator(".selbar").get_by_role("button", name="More").click()
    page.get_by_role("menuitem", name=re.compile("^Add to group")).click()


def _no_sideways_scroll(page):
    return not page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )


def test_select_on_the_main_list_ticks_without_opening(phone, site):
    _main_list(phone, site)
    _select(phone)
    phone.locator(".pick-row", has_text="Bees").locator(".card").click()
    assert phone.url.rstrip("/").endswith("/annals")  # still on the list
    assert phone.get_by_label("Pick “Bees”").is_checked()
    assert phone.locator(".sel-count").inner_text() == "1 picked"
    names = [b.inner_text().strip() for b in phone.locator(".selbar button.result").all()]
    assert names == ["Links", "One file", "Listen"]
    toggle = phone.get_by_role("button", name="Select", exact=True)
    assert toggle.get_attribute("aria-pressed") == "true"  # the label stays, the state is pressed
    toggle.click()
    assert toggle.get_attribute("aria-pressed") == "false"
    assert phone.locator(".selbar").is_hidden() and phone.locator(".pick-row").count() == 0


def test_one_file_of_a_pick_from_the_list(phone, site):
    _main_list(phone, site)
    _select(phone)
    phone.get_by_label("Pick “Tides”").check()
    phone.locator(".selbar").get_by_role("button", name="One file").click()
    phone.wait_for_function(
        "document.querySelector('.sheet textarea.combine-text')?.value.includes('moon')"
    )
    assert "hives" not in phone.locator(".sheet textarea.combine-text").input_value()


def test_links_of_a_list_pick_asks_for_a_group_first(phone, site):
    _main_list(phone, site)
    _select(phone)
    phone.get_by_label("Pick “Bees”").check()
    phone.locator(".selbar").get_by_role("button", name="Links").click()
    assert "a group is made" in phone.locator(".sheet").inner_text()
    assert phone.get_by_role("button", name="Make the group").count() == 1


def test_add_to_group_makes_a_group_of_the_picked_documents(phone, site):
    store = site["store"]
    _main_list(phone, site)
    _select(phone)
    phone.get_by_label("Pick “Bees”").check()
    phone.get_by_label("Pick “Tides”").check()
    _open_add_to_group(phone)
    title = phone.get_by_label("Name of the new group")
    assert title.input_value().endswith("1 more")
    title.fill("Made by hand")
    phone.get_by_role("button", name="Make the group").click()
    phone.locator(".add-open").wait_for()
    made = [g for g in store.list_groups() if g["title"] == "Made by hand"]
    assert len(made) == 1 and set(made[0]["docs"]) == {site["bees"]["id"], site["tides"]["id"]}
    phone.locator(".add-open").click()
    phone.locator(".doc-head h2").wait_for()
    assert phone.locator(".doc-head h2").inner_text() == "Made by hand"


def test_add_to_an_existing_group(phone, site):
    store = site["store"]
    extra = store.publish(text="# Extra\n\nmore", title="Extra", filename="extra.md")
    target = store.make_group("Target", [site["bees"]["id"]])
    _main_list(phone, site)
    _select(phone)
    phone.get_by_label("Pick “Extra”").check()
    _open_add_to_group(phone)
    phone.locator(".add-pick", has_text="Target").click()
    phone.locator(".add-open").wait_for()
    assert store.group(target["id"])["docs"] == [site["bees"]["id"], extra["id"]]


def test_add_to_group_from_a_groups_bar(phone, site):
    store = site["store"]
    source = store.make_group("Source", [site["bees"]["id"], site["tides"]["id"]])
    phone.goto(f"{site['base']}/g/{source['id']}")
    phone.locator(".selbar").wait_for()
    phone.get_by_label("Pick “Tides”").check()
    _open_add_to_group(phone)
    phone.get_by_label("Name of the new group").fill("From a group")
    phone.get_by_role("button", name="Make the group").click()
    phone.locator(".add-open").wait_for()
    made = [g for g in store.list_groups() if g["title"] == "From a group"]
    assert made and made[0]["docs"] == [site["tides"]["id"]]
    # the group the pick came from is not offered as a place to add to
    assert phone.locator(".add-pick", has_text="Source").count() == 0


def test_select_mode_does_not_scroll_sideways_and_has_thumb_sized_targets(phone, site):
    _main_list(phone, site)
    _select(phone)
    phone.get_by_label("Pick “Bees”").check()
    assert _no_sideways_scroll(phone)
    for el in phone.locator(".select-btn, .pick-row > .pick, .selbar button.result").all():
        box = el.bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44
    _open_add_to_group(phone)
    phone.locator(".add-title").wait_for()
    assert _no_sideways_scroll(phone)


# -- review fixes for #50 -------------------------------------------------------------


def test_a_failed_make_is_shown_in_the_sheet_and_keeps_the_form(phone, site):
    phone.route(
        "**/api/groups",
        lambda route: route.fulfill(
            status=422, content_type="application/json", body='{"detail": "no such document: x"}'
        )
        if route.request.method == "POST"
        else route.continue_(),
    )
    _main_list(phone, site)
    _select(phone)
    phone.get_by_label("Pick “Bees”").check()
    _open_add_to_group(phone)
    phone.get_by_role("button", name="Make the group").click()
    alert = phone.locator(".sheet [role=alert]")
    phone.wait_for_function("document.querySelector('.sheet [role=alert]').textContent.includes('no such document')")
    assert alert.is_visible()
    assert phone.get_by_label("Name of the new group").is_visible()  # the form stays to try again
    # a toast, when there is one, is above the sheet
    assert phone.evaluate("parseInt(getComputedStyle(document.querySelector('.toast') || document.body).zIndex) || 0") >= 0
    assert phone.evaluate(
        "(() => { const t = document.createElement('div'); t.className = 'toast'; document.body.appendChild(t);"
        " const z = +getComputedStyle(t).zIndex; t.remove(); return z > +getComputedStyle(document.querySelector('.sheet')).zIndex; })()"
    )


def test_enter_in_the_name_field_makes_the_group(phone, site):
    store = site["store"]
    _main_list(phone, site)
    _select(phone)
    phone.get_by_label("Pick “Bees”").check()
    _open_add_to_group(phone)
    title = phone.get_by_label("Name of the new group")
    title.focus()
    assert phone.evaluate("(() => { const t = document.querySelector('.add-title'); return t.selectionStart === 0 && t.selectionEnd === t.value.length; })()")
    title.fill("By enter")
    title.press("Enter")
    phone.locator(".add-open").wait_for()
    assert [g for g in store.list_groups() if g["title"] == "By enter"]


def test_select_mode_and_picks_survive_back_and_forward(phone, site):
    _main_list(phone, site)
    _select(phone)
    phone.get_by_label("Pick “Bees”").check()
    phone.locator(".pick-row", has_text="Tides").locator(".pick").click()  # also ticks Tides
    phone.get_by_label("Pick “Tides”").uncheck()
    phone.goto(f"{site['base']}/d/{site['bees']['id']}")
    phone.go_back()
    phone.locator(".pick-row").first.wait_for()
    assert phone.get_by_label("Pick “Bees”").is_checked()
    assert not phone.get_by_label("Pick “Tides”").is_checked()
    assert phone.locator(".sel-count").inner_text() == "1 picked"
    # the search box is a refinement of this entry: the picks stay when it changes what is shown
    phone.get_by_label("Search").fill("Tides")
    phone.wait_for_function("document.querySelectorAll('.pick-row').length === 1")
    assert phone.locator(".sel-count").inner_text() == "1 picked, 1 not shown"


def test_all_picks_only_what_is_shown_and_group_cards_leave_select_mode(phone, site):
    _main_list(phone, site)
    assert phone.locator(f"a.card[href$='/g/{site['group']['id']}']").count() == 1
    _select(phone)
    assert phone.locator(f"a.card[href$='/g/{site['group']['id']}']").count() == 0
    assert "group" not in phone.locator(".count").inner_text()
    phone.get_by_label("Pick all shown documents").check()
    n = phone.locator(".pick-row").count()
    assert phone.locator(".sel-count").inner_text() == f"{n} picked"
    phone.get_by_label("Pick all shown documents").uncheck()
    assert phone.locator(".sel-count").inner_text() == "Tap documents to pick them"
    # one tab stop per row: the card link is out of the tab order
    assert phone.locator(".pick-row a.card[tabindex='-1'][aria-hidden='true']").count() == n


def test_links_of_a_list_pick_says_a_group_is_made_then_shows_its_links(phone, site):
    store = site["store"]
    _main_list(phone, site)
    _select(phone)
    phone.get_by_label("Pick “Bees”").check()
    phone.locator(".selbar").get_by_role("button", name="Links").click()
    assert "a group is made" in phone.locator(".sheet").inner_text()
    phone.get_by_label("Name of the new group").fill("For links")
    phone.get_by_role("button", name="Make the group").click()
    phone.locator(".sheet .links-body").wait_for()  # the new group's own Links, not a dead end
    assert [g for g in store.list_groups() if g["title"] == "For links"]
    phone.wait_for_function("!document.querySelector('.selbar') || document.querySelector('.selbar').hidden")


def test_existing_groups_can_be_filtered_and_marked_when_they_have_the_pick(phone, site):
    store = site["store"]
    for i in range(14):  # past the length a list gets a filter box at
        store.make_group(f"Filler {i}", [site["tides"]["id"]])
    _main_list(phone, site)
    _select(phone)
    phone.get_by_label("Pick “Tides”").check()
    _open_add_to_group(phone)
    phone.get_by_label("Find a group").fill("Filler 3")
    phone.wait_for_function("document.querySelectorAll('.add-pick').length === 1")
    pick = phone.locator(".add-pick")
    assert pick.get_attribute("aria-disabled") == "true"  # it already has Tides
    assert "already has these" in pick.inner_text()
