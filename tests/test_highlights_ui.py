"""Highlights, as a reader meets them on a phone: select, keep, find, come back to the passage.

The owner asked to highlight part of a document and save it, to search the saved highlights,
to open one on its page with the passage in the middle of the screen, to see the page's other
highlights unless told otherwise, and to keep a whole document by its title (2026-11-27).
Selection, drawing and scrolling only exist in a browser, so these drive the real page at
phone width in Chromium and WebKit (every browser on an iPhone or iPad), light and dark; they
skip where Playwright or a browser is missing.
"""

import json
from pathlib import Path

import pytest

from annals.store import DocStore

PHONE = {"width": 390, "height": 844}
PARAGRAPH = (
    "Bake {i}: the dough was mixed in the evening, folded three times, left in the cold "
    "overnight and baked in a covered pot, then judged by its crumb and its crust."
)
MARKER = "the marker sentence sits in the middle"
DOC = (
    "# Bread notes\n\nWhat each loaf wants, written down after a season of baking.\n\n"
    "| Loaf | Water | Proof |\n|---|---|---|\n"
    "| Country loaf | 75 percent | 4 hours |\n| Rye | 85 percent | 2 hours |\n\n"
    "A wetter dough gives a more open crumb.\n\n"
    + "\n\n".join(PARAGRAPH.format(i=i) for i in range(1, 15))
    + f"\n\nFor centring, {MARKER} of a long page.\n\n"
    + "\n\n".join(PARAGRAPH.format(i=i) for i in range(15, 29))
    + "\n\nAt the very end: a wetter dough gives a more open crumb, again.\n"
)

#: selects the n-th occurrence of ``words`` inside the rendered document, as a finger would
SELECT = """([words, nth]) => {
  const root = document.querySelector('article.rendered');
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let seen = 0;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    for (let i = n.data.indexOf(words); i !== -1; i = n.data.indexOf(words, i + 1)) {
      if (++seen !== nth) continue;
      const r = document.createRange();
      r.setStart(n, i); r.setEnd(n, i + words.length);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      n.parentElement.scrollIntoView({ block: 'center' });
      return true;
    }
  }
  return false;
}"""
#: what the browser is drawing: {registered highlight name: [text of each range]}
PAINTED = """() => Object.fromEntries([...CSS.highlights].map(([name, hl]) => [name, [...hl].map(r => r.toString())]))"""


@pytest.fixture(scope="module", params=["chromium", "webkit"])
def browser(request):
    return request.getfixturevalue(request.param)


@pytest.fixture
def site(tmp_path, serve):
    """A fresh annals with one long document; every test starts with no highlights."""
    store = DocStore(tmp_path / "data")
    doc = store.publish(text=DOC, title="Bread notes", filename="bread.md")
    return {"base": serve(store), "doc": doc["id"], "root": Path(store.target.root)}


@pytest.fixture(params=["light", "dark"])
def phone(browser, request):
    ctx = browser.new_context(
        viewport=PHONE, color_scheme=request.param, has_touch=True, is_mobile=True
    )
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(str(e)))
    yield page
    assert page.problems == []
    ctx.close()


def _open(page, site, query=""):
    page.goto(f"{site['base']}/d/{site['doc']}{query}")
    page.wait_for_selector("article.rendered table")
    page.wait_for_function("window.Manicules !== undefined")
    page.wait_for_selector(".mn-layer", state="attached")


def _keep(page, words, nth=1):
    """Select ``words`` and tap Highlight; returns once the highlight is on the server."""
    assert page.evaluate(SELECT, [words, nth])
    page.wait_for_selector(".mn-pill:not([hidden])")
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/highlights")
    ) as made:
        page.locator(".mn-pill").tap()
    page.wait_for_selector(".mn-card:not([hidden])")
    return made.value.json()


def _dismiss(page):
    page.locator(".mn-card .mn-icon-btn").tap()
    page.wait_for_selector(".mn-card", state="hidden")


def _stored(site):
    files = list((site["root"] / "highlights").glob("*.json"))
    return json.loads(files[0].read_text()) if files else {}


def test_select_then_one_tap_keeps_the_passage_under_the_default_name(phone, site):
    _open(phone, site)
    assert phone.locator(".mn-pill").is_hidden()
    made = _keep(phone, "85 percent")
    assert made["name"] == "Bread notes-highlight-1"
    assert made["target"]["quote"]["exact"] == "85 percent"
    assert made["target"]["part"] == "body" and made["target"]["source"]["id"] == site["doc"]
    assert phone.evaluate(PAINTED)["mn-yellow"] == ["85 percent"]
    assert phone.locator(".mn-card-title").inner_text() == "Highlight saved"
    assert phone.locator(".mn-brief-quote").inner_text() == "85 percent"
    assert phone.evaluate("getSelection().isCollapsed")
    # the note says it worked and does not cover the page: the passage stays in sight
    card = phone.locator(".mn-card").bounding_box()
    assert card["height"] < PHONE["height"] * 0.3
    mark = phone.evaluate("(() => { const r = [...CSS.highlights.get('mn-yellow')][0].getBoundingClientRect(); return [r.top, r.bottom]; })()")
    assert 0 <= mark[0] and mark[1] <= card["y"]
    assert list(_stored(site)) == [made["id"]]


def test_a_note_tags_and_a_colour_are_one_tap_away_and_are_saved(phone, site):
    _open(phone, site)
    made = _keep(phone, "85 percent")
    phone.get_by_role("button", name="Add a note or tags").tap()
    phone.locator(".mn-textarea").fill("The row I keep looking for")
    phone.locator(".mn-form input[type=text]").nth(1).fill("water, rye")
    phone.locator(".mn-colour-input[value=green]").check(force=True)
    with phone.expect_response(lambda r: r.request.method == "PATCH"):
        phone.locator(".mn-form button[type=submit]").tap()
    phone.wait_for_selector(".mn-card", state="hidden")
    kept = _stored(site)[made["id"]]
    assert kept["comment"] == "The row I keep looking for"
    assert kept["tags"] == ["rye", "water"] and kept["color"] == "green"
    painted = phone.evaluate(PAINTED)
    assert painted["mn-green"] == ["85 percent"] and painted["mn-noted"] == ["85 percent"]
    # every field of the editor is 16px or more: an iPhone zooms the page on a smaller one
    phone.evaluate(SELECT, ["85 percent", 1])
    phone.evaluate("getSelection().removeAllRanges()")


def test_a_tap_on_a_highlight_shows_its_note_and_a_tap_elsewhere_puts_it_away(phone, site):
    _open(phone, site)
    made = _keep(phone, "75 percent")
    _dismiss(phone)
    phone.request.patch(
        f"{site['base']}/api/highlights/{made['id']}", data={"comment": "the country loaf"}
    )
    _open(phone, site)
    phone.wait_for_function("CSS.highlights.has('mn-noted')")
    box = phone.evaluate(
        "(() => { const r = [...CSS.highlights.get('mn-yellow')][0].getBoundingClientRect();"
        " return [r.left + r.width / 2, r.top + r.height / 2]; })()"
    )
    phone.touchscreen.tap(*box)
    phone.wait_for_selector(".mn-card:not([hidden])")
    assert phone.locator(".mn-note").inner_text() == "the country loaf"
    assert phone.evaluate(PAINTED)["mn-current"] == ["75 percent"]
    # the address names the highlight being looked at, for as long as its card is open
    assert phone.url.endswith(f"?h={made['id']}")
    phone.locator(".doc-head .meta").tap()
    phone.wait_for_selector(".mn-card", state="hidden")
    assert "mn-current" not in phone.evaluate(PAINTED)
    assert "h=" not in phone.url


def test_the_list_finds_a_highlight_and_opens_its_page_centred_on_it(phone, site):
    _open(phone, site)
    _keep(phone, "85 percent")
    _dismiss(phone)
    marked = _keep(phone, MARKER)
    _dismiss(phone)
    phone.locator("header.bar nav a", has_text="Highlights").tap()
    phone.wait_for_selector(".mn-item")
    assert phone.locator(".mn-item").count() == 2
    # typing filters at once, over the passages too
    phone.locator(".mn-search").fill("marker middle")
    assert phone.locator(".mn-item").count() == 1
    assert "q=marker+middle" in phone.url
    link = phone.locator(".mn-item-link")
    assert link.get_attribute("href").endswith(f"/d/{site['doc']}?h={marked['id']}")
    link.tap()
    phone.wait_for_selector(".mn-card:not([hidden])")
    phone.wait_for_function("CSS.highlights.has('mn-current')")
    assert phone.url.endswith(f"/d/{site['doc']}?h={marked['id']}")
    phone.wait_for_timeout(900)  # the smooth scroll settles
    where = phone.evaluate(
        "(() => { const r = [...CSS.highlights.get('mn-current')][0].getBoundingClientRect();"
        " const card = document.querySelector('.mn-card').getBoundingClientRect();"
        " return { middle: r.top + r.height / 2, cardTop: card.top, text: [...CSS.highlights.get('mn-current')][0].toString() }; })()"
    )
    assert where["text"] == MARKER
    # in the middle of what the card leaves visible, give or take a line
    assert abs(where["middle"] - where["cardTop"] / 2) < 40
    # the page's other highlight is drawn too (the default), and Back returns to the search
    assert sorted(phone.evaluate(PAINTED)["mn-yellow"]) == sorted(["85 percent", MARKER])
    phone.go_back()
    phone.wait_for_selector(".mn-search")
    assert phone.locator(".mn-search").input_value() == "marker middle"
    assert phone.url.endswith("/highlights?q=marker+middle")


def test_the_other_highlights_can_be_hidden_and_that_can_be_the_default(phone, site):
    _open(phone, site)
    _keep(phone, "85 percent")
    _dismiss(phone)
    marked = _keep(phone, MARKER)
    _dismiss(phone)
    phone.locator(".menu-btn").tap()
    phone.get_by_role("menuitem", name="Highlights").tap()
    phone.wait_for_selector(".mn-card:not([hidden])")
    assert phone.locator(".mn-row").count() == 2
    # hide them now
    phone.locator(".mn-switch .mn-check").first.uncheck()
    assert phone.evaluate(PAINTED) == {}
    phone.locator(".mn-switch .mn-check").first.check()
    # and by default: a page opened on one highlight then shows that one alone
    phone.locator(".mn-settings summary").tap()
    with phone.expect_response(lambda r: r.request.method == "PUT"):
        phone.locator(".mn-settings .mn-check").uncheck()
    assert json.loads(next((site["root"] / "highlight-settings").glob("*.json")).read_text())["showOthers"] is False
    _open(phone, site, f"?h={marked['id']}")
    phone.wait_for_function("CSS.highlights.has('mn-current')")
    assert phone.evaluate(PAINTED)["mn-yellow"] == [MARKER]


def test_the_colour_setting_recolours_what_has_no_colour_of_its_own(phone, site):
    _open(phone, site)
    _keep(phone, "85 percent")
    _dismiss(phone)
    phone.locator(".menu-btn").tap()
    phone.get_by_role("menuitem", name="Highlights").tap()
    phone.locator(".mn-settings summary").tap()
    with phone.expect_response(lambda r: r.request.method == "PUT"):
        phone.locator(".mn-settings .mn-colour-input[value=blue]").check(force=True)
    assert phone.evaluate(PAINTED) == {"mn-blue": ["85 percent"]}
    _open(phone, site)
    phone.wait_for_function("CSS.highlights.has('mn-blue')")


def test_keeping_the_page_by_its_title_lists_it_and_survives_a_rename(phone, site):
    _open(phone, site)
    phone.locator(".menu-btn").tap()
    phone.get_by_role("menuitem", name="Highlights").tap()
    with phone.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/highlights")) as made:
        phone.get_by_role("button", name="Highlight this page").tap()
    kept = made.value.json()
    assert kept["target"]["part"] == "title" and kept["target"]["whole"] is True
    assert phone.evaluate(PAINTED)["mn-yellow"] == ["Bread notes"]
    phone.request.patch(f"{site['base']}/api/docs/{site['doc']}", data={"title": "Loaves, renamed"})
    _open(phone, site)
    phone.wait_for_function("CSS.highlights.has('mn-yellow')")
    assert phone.evaluate(PAINTED)["mn-yellow"] == ["Loaves, renamed"]
    phone.goto(f"{site['base']}/highlights")
    phone.wait_for_selector(".mn-item")
    assert "Whole page" in phone.locator(".mn-item-meta").inner_text()


def test_selecting_the_title_itself_keeps_the_page_too(phone, site):
    _open(phone, site)
    phone.evaluate(
        "(() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('.doc-head h2'));"
        " const s = getSelection(); s.removeAllRanges(); s.addRange(r); })()"
    )
    phone.wait_for_selector(".mn-pill:not([hidden])")
    with phone.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/highlights")) as made:
        phone.locator(".mn-pill").tap()
    assert made.value.json()["target"]["whole"] is True


def test_remove_offers_undo_and_undo_brings_it_back(phone, site):
    _open(phone, site)
    made = _keep(phone, "85 percent")
    with phone.expect_response(lambda r: r.request.method == "DELETE"):
        phone.get_by_role("button", name="Remove").tap()
    assert _stored(site) == {} and phone.evaluate(PAINTED) == {}
    with phone.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/highlights")):
        phone.get_by_role("button", name="Undo").tap()
    assert list(_stored(site)) == [made["id"]]
    phone.wait_for_function("CSS.highlights.has('mn-yellow')")


def test_the_source_view_draws_nothing_and_the_rendered_view_draws_again(phone, site):
    _open(phone, site)
    _keep(phone, "85 percent")
    _dismiss(phone)
    phone.locator(".view-toggle").tap()
    phone.wait_for_selector("pre.source")
    phone.wait_for_function("!CSS.highlights.has('mn-yellow')")
    phone.locator(".view-toggle").tap()
    phone.wait_for_selector("article.rendered")
    phone.wait_for_function("CSS.highlights.has('mn-yellow')")


def test_the_widgets_controls_fit_a_thumb_and_the_page_never_scrolls_sideways(phone, site):
    _open(phone, site)
    _keep(phone, "85 percent")
    phone.get_by_role("button", name="Add a note or tags").tap()
    phone.wait_for_selector(".mn-form")
    sizes = phone.evaluate(
        "[...document.querySelectorAll('.mn-card button, .mn-card .mn-colour')].map(e => { const r = e.getBoundingClientRect(); return [e.textContent.trim() || e.getAttribute('aria-label') || e.className, Math.round(r.width), Math.round(r.height)]; })"
    )
    assert sizes and all(w >= 44 and h >= 44 for _, w, h in sizes), sizes
    fonts = phone.evaluate("[...document.querySelectorAll('.mn-card input[type=text], .mn-card textarea')].map(e => parseFloat(getComputedStyle(e).fontSize))")
    assert fonts and min(fonts) >= 16
    assert phone.evaluate("document.documentElement.scrollWidth") <= PHONE["width"]
    # the seven colour choices sit on one row
    tops = phone.evaluate("[...document.querySelectorAll('.mn-card .mn-colour')].map(e => Math.round(e.getBoundingClientRect().top))")
    assert len(tops) == 7 and len(set(tops)) == 1


def test_a_share_link_and_a_room_offer_no_highlights(browser, tmp_path, serve):
    store = DocStore(tmp_path / "data")
    doc = store.publish(text=DOC, title="Bread notes", filename="bread.md")
    base = serve(store, highlights=None)
    ctx = browser.new_context(viewport=PHONE)
    page = ctx.new_page()
    page.goto(f"{base}/d/{doc['id']}")
    page.wait_for_selector("article.rendered table")
    assert page.locator("header.bar nav a", has_text="Highlights").count() == 0
    page.locator(".menu-btn").click()
    assert page.get_by_role("menuitem", name="Highlights").count() == 0
    assert page.evaluate("window.Manicules === undefined")
    ctx.close()


def test_back_returns_to_the_row_a_highlight_was_opened_from(phone, site):
    _open(phone, site)
    for i in range(1, 13):  # enough rows to scroll
        phone.request.post(
            f"{site['base']}/api/highlights",
            data={"target": {"source": {"id": site["doc"], "title": "Bread notes", "url": f"d/{site['doc']}"}, "quote": {"exact": f"Bake {i}:"}}, "comment": "note " * 30},
        )
    phone.goto(f"{site['base']}/highlights")
    phone.wait_for_selector(".mn-item")
    last = phone.locator(".mn-item-link").last
    last.scroll_into_view_if_needed()
    was = phone.evaluate("window.scrollY")
    assert was > 400
    last.tap()
    phone.wait_for_selector(".mn-card:not([hidden])")
    phone.go_back()
    phone.wait_for_selector(".mn-item")
    phone.wait_for_function(f"Math.abs(window.scrollY - {was}) < 80")


def test_an_open_editor_takes_the_taps_meant_for_the_page(phone, site):
    """A stray touch on the text while a note is being typed closes the editor, keeping the
    note, and does nothing else: no link followed, no other card opened."""
    _open(phone, site)
    made = _keep(phone, "85 percent")
    phone.get_by_role("button", name="Add a note or tags").tap()
    phone.locator(".mn-textarea").fill("typed, then a stray tap")
    assert phone.locator(".mn-scrim").is_visible()
    with phone.expect_response(lambda r: r.request.method == "PATCH"):
        phone.touchscreen.tap(195, 120)
    phone.wait_for_selector(".mn-card", state="hidden")
    assert _stored(site)[made["id"]]["comment"] == "typed, then a stray tap"
    assert phone.url.endswith(f"/d/{site['doc']}")


def test_a_note_being_typed_is_saved_when_the_reader_leaves_the_page(phone, site):
    _open(phone, site)
    made = _keep(phone, "85 percent")
    phone.get_by_role("button", name="Add a note or tags").tap()
    phone.locator(".mn-textarea").fill("typed, then Back")
    with phone.expect_response(lambda r: r.request.method == "PATCH"):
        phone.evaluate("document.querySelector('header.bar h1 a').click()")
    phone.wait_for_selector(".card")
    assert _stored(site)[made["id"]]["comment"] == "typed, then Back"
