"""The copy control: one button beside every value worth copying, answering on itself.

On a phone the notebook links could be seen but not easily copied (2026-11-04). Every
generated link, password and code block now has the same copy button, which copies inside
the tap and turns into a check reading "Copied". These drive the real page in Chromium at
phone size with clipboard access granted; they skip where Playwright or a browser is missing.
"""

import pytest

from annals.store import DocStore

PHONE = {"width": 390, "height": 844}
CODE = "annals publish report.md --session demo"


@pytest.fixture(scope="module")
def site(tmp_path_factory, serve):
    store = DocStore(tmp_path_factory.mktemp("copy") / "data")
    cmd = store.publish(
        text=f"# Commands\n\nRun this:\n\n```bash\n{CODE}\n```\n",
        title="Commands",
        filename="cmd.md",
    )
    bees = store.publish(text="# Bees\n\nhives", title="Bees", filename="bees.md")
    tides = store.publish(text="# Tides\n\nmoon", title="Tides", filename="tides.md")
    group = store.make_group("Nature", [bees["id"], tides["id"]])
    return {"base": serve(store), "cmd": cmd, "group": group}


@pytest.fixture
def phone(chromium):
    ctx = chromium.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    yield ctx.new_page()
    ctx.close()


def _clipboard(page):
    return page.evaluate("navigator.clipboard.readText()")


def _tap_copy(page, btn):
    btn.click()
    page.wait_for_function(
        "b => b.getAttribute('data-state') === 'copied'", arg=btn.element_handle()
    )


def test_a_code_block_copies_its_text_and_says_so(phone, site):
    phone.goto(f"{site['base']}/d/{site['cmd']['id']}")
    btn = phone.locator(".rendered .code-wrap .copy-btn")
    btn.wait_for()
    assert btn.get_attribute("aria-label") == "Copy code"
    _tap_copy(phone, btn)
    assert _clipboard(phone).strip() == CODE
    assert btn.get_attribute("aria-label") == "Copied"
    # back to its resting state, ready for another copy
    phone.wait_for_function(
        "b => b.getAttribute('data-state') === 'idle'",
        arg=btn.element_handle(),
        timeout=5000,
    )


def test_copy_targets_are_thumb_sized(phone, site):
    phone.goto(f"{site['base']}/d/{site['cmd']['id']}")
    btn = phone.locator(".code-wrap .copy-btn")
    btn.wait_for()
    box = btn.bounding_box()
    assert box["width"] >= 44 and box["height"] >= 44


def test_each_page_link_has_its_own_copy_button(phone, site):
    phone.goto(f"{site['base']}/g/{site['group']['id']}")
    phone.get_by_role("button", name="Notebook").click()
    phone.get_by_role("button", name="Make links for 2").click()
    rows = phone.locator(".link-list li")
    rows.first.wait_for()
    assert rows.count() == 2
    first_url = rows.first.locator("input.copy-value").input_value()
    assert "/source/" in first_url
    _tap_copy(phone, rows.first.locator(".copy-btn"))
    assert _clipboard(phone) == first_url
    # and all of them at once, one per line, for the notebook's Website source
    _tap_copy(phone, phone.get_by_role("button", name="Copy all 2 links"))
    assert len(_clipboard(phone).splitlines()) == 2


def test_a_share_link_and_its_password_each_copy(phone, site):
    phone.goto(f"{site['base']}/d/{site['cmd']['id']}")
    phone.get_by_role("button", name="Share").click()
    phone.get_by_label("Password (optional)").fill("tide-pool-2026")
    phone.get_by_role("button", name="Create link").click()
    fields = phone.locator(".share-result .copy-field")
    fields.nth(1).wait_for()
    url = fields.nth(0).locator("input").input_value()
    assert "/shared/" in url
    _tap_copy(phone, fields.nth(0).locator(".copy-btn"))
    assert _clipboard(phone) == url
    _tap_copy(phone, fields.nth(1).locator(".copy-btn"))
    assert _clipboard(phone) == "tide-pool-2026"
