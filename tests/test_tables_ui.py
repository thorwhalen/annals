"""What a reader sees of a wide table at phone width, measured in a real browser.

The bug these pin: a sticky first column wider than the screen covers everything, so no other
column can ever be reached. Layout is the only honest test of that, so these drive a browser;
they skip where Playwright or a browser is missing. Set ``ANNALS_TEST_BROWSER`` to a browser
executable to use one Playwright did not download. The static test below always runs.
"""

import os
from pathlib import Path

import pytest

UI = Path(__file__).parent.parent / "annals" / "data" / "ui"
TABLES_JS = (UI / "tables.js").read_text(encoding="utf-8")
STYLE_CSS = (UI / "style.css").read_text(encoding="utf-8")

PHONE = {"width": 390, "height": 844}
LONG = (
    "Quarterly reconciliation of the northern distribution centre against supplier "
    "invoices and returned goods, including late adjustments"
)


def _table(first_cell, *, rows=12, cols=8, header=None):
    head = header or "".join(f"<th>H{c}</th>" for c in range(cols))
    body = "".join(
        f"<tr><td>{first_cell} {r}</td>"
        + "".join(f"<td>r{r}c{c}</td>" for c in range(1, cols - 1))
        + f"<td>LAST-{r}</td></tr>"
        for r in range(rows)
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _page(table, *, before_tables=""):
    """A document page; ``before_tables`` runs ahead of tables.js, as the app's router does."""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>{STYLE_CSS}</style></head>"
        f'<body><main class="rendered">{table}</main><script>{before_tables}</script>'
        f"<script>{TABLES_JS}</script>"
        "<script>annalsTables.enhance(document.querySelector('.rendered'))</script></body></html>"
    )


def test_nothing_sticks_unconditionally():
    """Sticking is a class the script adds after measuring, never a rule on every cell."""
    for rule in ("th:first-child", "td:first-child"):
        assert rule not in TABLES_JS
    assert ".at-scroll th{white-space:normal;position:sticky" not in TABLES_JS
    assert ".at-stick-col .at-first{position:sticky" in TABLES_JS
    assert ".at-stick-head .at-head{position:sticky" in TABLES_JS


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=os.environ.get("ANNALS_TEST_BROWSER"))
        except sync_api.Error as e:
            pytest.skip(f"no browser to run: {e}")
        yield b
        b.close()


@pytest.fixture(params=["light", "dark"])
def phone(browser, request):
    ctx = browser.new_context(
        viewport=PHONE, color_scheme=request.param, has_touch=True, is_mobile=True
    )
    yield ctx.new_page()
    ctx.close()


@pytest.fixture
def show(phone):
    def _show(table):
        phone.set_content(_page(table))
        return phone

    return _show


def _last_column_reachable(page):
    """Scroll fully right: is the last column what a finger on it would actually touch?"""
    return page.evaluate(
        """() => {
          const s = document.querySelector('.at-scroll');
          s.scrollLeft = 1e6;
          const td = s.querySelector('tbody tr:nth-child(2) td:last-child').getBoundingClientRect();
          const hit = document.elementFromPoint(td.left + td.width / 2, td.top + td.height / 2);
          return !!hit && hit.textContent.startsWith('LAST-');
        }"""
    )


def _is_stuck(page, selector):
    return page.evaluate(
        "s => getComputedStyle(document.querySelector(s)).position === 'sticky'",
        selector,
    )


def _row_backgrounds(page):
    return page.evaluate(
        """() => [...document.querySelectorAll('.at-scroll tbody tr')].slice(0, 2)
             .map(r => getComputedStyle(r.cells[1]).backgroundColor)"""
    )


def test_long_first_column_leaves_every_column_reachable(show):
    page = show(_table(LONG))
    assert not _is_stuck(page, ".at-scroll tbody td")
    assert _last_column_reachable(page)


def test_short_first_column_sticks_within_its_cap(show):
    page = show(_table("alpha"))
    assert _is_stuck(page, ".at-scroll tbody td")
    assert _last_column_reachable(page)
    share = page.evaluate(
        """() => {
          const s = document.querySelector('.at-scroll');
          return s.querySelector('td').getBoundingClientRect().width / s.clientWidth;
        }"""
    )
    assert share <= 0.41


def test_a_table_that_fits_does_not_stick_its_column(show):
    page = show(_table("a", cols=4, rows=3))
    assert not _is_stuck(page, ".at-scroll tbody td")


def test_zooming_in_unsticks_a_column_that_no_longer_fits(show):
    page = show(_table("alpha"))
    assert _is_stuck(page, ".at-scroll tbody td")
    for _ in range(6):
        page.click('[aria-label="Zoom in"]')
    assert not _is_stuck(page, ".at-scroll tbody td")
    assert _last_column_reachable(page)


def test_a_span_in_the_first_column_never_sticks(show):
    table = _table("alpha").replace(
        "<td>alpha 1</td>", '<td rowspan="2">alpha 1</td>', 1
    )
    page = show(table)
    assert not _is_stuck(page, ".at-scroll tbody td")


def test_rows_alternate_in_opaque_shades(show):
    page = show(_table("alpha"))
    odd, even = _row_backgrounds(page)
    assert odd != even
    for colour in (odd, even):
        assert "/ 0" not in colour and "rgba(0, 0, 0, 0)" not in colour


def test_a_rowspan_in_the_body_turns_off_the_stripes(show):
    table = _table("alpha").replace("<td>r1c1</td>", '<td rowspan="2">r1c1</td>', 1)
    page = show(table)
    assert page.locator(".at-scroll.at-zebra").count() == 0


def test_a_colour_the_page_gives_its_cells_beats_the_stripes(show):
    page = show("<style>td{background-color:rgb(1,2,3)}</style>" + _table("alpha"))
    assert set(_row_backgrounds(page)) == {"rgb(1, 2, 3)"}


def test_header_sticks_unless_it_would_fill_the_box(show):
    page = show(_table("alpha", rows=60))
    assert _is_stuck(page, ".at-scroll thead th")
    tall = "".join(f"<th>{LONG} {LONG} {LONG} {LONG}</th>" for _ in range(8))
    page = show(_table("alpha", rows=60, header=tall))
    assert page.locator(".at-scroll.at-stick-head").count() == 0


def test_only_the_top_header_row_sticks(show):
    extra = "<tr><th>second</th>" + "<th>x</th>" * 7 + "</tr>"
    page = show(
        _table("alpha", rows=60).replace(
            "</tr></thead>", "</tr>" + extra + "</thead>", 1
        )
    )
    assert _is_stuck(page, ".at-scroll thead tr:nth-child(1) th:nth-child(2)")
    assert not _is_stuck(page, ".at-scroll thead tr:nth-child(2) th:nth-child(2)")


def test_tapping_a_row_marks_one_row_at_a_time(show):
    page = show(_table("alpha"))
    rows = page.locator(".at-scroll tbody tr")
    plain = _row_backgrounds(page)[0]
    rows.nth(0).locator("td").nth(1).tap()
    assert _row_backgrounds(page)[0] != plain
    rows.nth(2).locator("td").nth(1).tap()
    assert page.locator("tr.at-hit").count() == 1
    rows.nth(2).locator("td").nth(1).tap()
    assert page.locator("tr.at-hit").count() == 0


def test_tapping_a_link_in_a_cell_does_not_mark_the_row(show):
    page = show(_table("alpha").replace("r1c1", '<a href="#x">r1c1</a>', 1))
    page.locator(".at-scroll a").tap()
    assert page.locator("tr.at-hit").count() == 0


def test_a_selection_does_not_mark_the_row(show):
    page = show(_table("alpha"))
    page.evaluate(
        """() => {
          const c = document.querySelectorAll('.at-scroll tbody td')[1];
          getSelection().selectAllChildren(c);
          c.click();
        }"""
    )
    assert page.locator("tr.at-hit").count() == 0


def test_toolbar_buttons_are_thumb_sized_and_stay_on_the_page(show):
    page = show(_table("alpha"))
    sizes = page.evaluate(
        """() => [...document.querySelectorAll('.at-bar button')].map(b => {
          const r = b.getBoundingClientRect(); return [r.width, r.height, r.right];
        })"""
    )
    assert all(w >= 44 and h >= 44 and right <= PHONE["width"] for w, h, right in sizes)


def test_back_closes_expand_on_a_page_without_a_router(show):
    page = show(_table("alpha"))
    page.click('[aria-label="Expand"]')
    assert page.locator(".at-table.at-full").count() == 1
    page.evaluate("history.back()")
    page.wait_for_selector(".at-table:not(.at-full)", state="attached")
    assert page.locator("html.at-lock").count() == 0


_ROUTER = """
  window.routed = 0;
  addEventListener('popstate', () => { if (!annalsTables.closeOnBack()) window.routed++; });
"""


def test_back_from_expand_does_not_route_when_the_router_asks_first(phone):
    """A router's listener was added first, so it runs first: it must be able to stand down."""
    phone.set_content(_page(_table("alpha"), before_tables=_ROUTER))
    phone.click('[aria-label="Expand"]')
    phone.evaluate("history.back()")
    phone.wait_for_selector(".at-table:not(.at-full)", state="attached")
    assert phone.evaluate("window.routed") == 0


def test_back_routes_normally_when_nothing_is_expanded(phone):
    phone.set_content(_page(_table("alpha"), before_tables=_ROUTER))
    phone.evaluate("history.pushState({}, '')")
    phone.evaluate("history.back()")
    phone.wait_for_function("window.routed === 1")


def test_the_app_router_asks_tables_before_routing():
    app_js = (UI / "app.js").read_text(encoding="utf-8")
    assert "annalsTables.closeOnBack()" in app_js


def test_close_button_leaves_no_extra_back_entry(show):
    page = show(_table("alpha"))
    before = page.evaluate("history.length")
    page.click('[aria-label="Expand"]')
    page.click('[aria-label="Close"]')
    page.wait_for_selector(".at-table:not(.at-full)", state="attached")
    assert page.locator('[aria-label="Expand"]').count() == 1
    assert page.evaluate("history.state && history.state.atFull") in (None, False)
    assert page.evaluate("history.length") >= before


def test_fit_to_width_shows_the_whole_table_without_scrolling(show):
    page = show(_table(LONG))
    page.click('[aria-label="Fit to width"]')
    assert page.evaluate(
        """() => {
          const s = document.querySelector('.at-scroll');
          return s.scrollWidth <= s.clientWidth + 1;
        }"""
    )
