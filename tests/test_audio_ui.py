"""The Audio tab, at phone size: find an overview, listen, and see what is left, on any device.

The owner listens on a phone or tablet and wants to track what they still have to listen to
(2026-11-09). The overview here is built like a real one (@zodal/speech): its audio is an
``Audio()`` made from a blob and never added to the page, inside the sandboxed frame. Two
browser contexts stand for two devices sharing the server's record.
"""

import base64
import io
import os
import struct
import wave

import pytest

from annals.overview import TAG
from annals.store import DocStore

PHONE = {"width": 390, "height": 844}
SECONDS = 20
RATE = 4
#: a folder to save screenshots in, to look at the layout by eye (unset: none are taken)
SHOTS = os.environ.get("ANNALS_TEST_SHOTS")


def _silence_wav(seconds=SECONDS, rate=8000) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * rate * seconds)
    return base64.b64encode(buf.getvalue()).decode()


PLAYER = """<!doctype html><html><head><meta charset="utf-8"><title>Bees</title></head><body>
<button id="play">Play</button> <button id="pause">Pause</button> <button id="end">To the end</button>
<!-- played at RATE times speed, so the test hears the whole clip in a few seconds -->
<script>
  var bytes = Uint8Array.from(atob("%s"), function (c) { return c.charCodeAt(0); });
  var player = new Audio(URL.createObjectURL(new Blob([bytes], {type: "audio/wav"})));
  player.playbackRate = %s;
  window.player = player;
  document.getElementById("play").onclick = function () { player.play(); };
  document.getElementById("pause").onclick = function () { player.pause(); };
  document.getElementById("end").onclick = function () { player.currentTime = player.duration - 0.6; player.play(); };
</script></body></html>"""


@pytest.fixture(scope="module")
def site(tmp_path_factory, serve):
    store = DocStore(tmp_path_factory.mktemp("audio") / "data")
    over = store.publish(text=PLAYER % (_silence_wav(), RATE), title="Listen: Bees", filename="overview.html", tags=[TAG])
    store.publish(text="# Tides", title="Tides", filename="tides.md")
    return {"base": serve(store), "over": over}


@pytest.fixture
def device(chromium):
    contexts = []

    def make():
        ctx = chromium.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        contexts.append(ctx)
        return ctx.new_page()

    yield make
    for c in contexts:
        c.close()


def _no_sideways_scroll(page):
    assert page.evaluate("document.documentElement.scrollWidth") <= PHONE["width"]


def _status_line(page):
    return page.locator(".listening [role=status]")


def test_listen_on_one_device_and_see_what_is_left_on_another(device, site):
    phone = device()
    phone.goto(f"{site['base']}/audio")
    row = phone.locator(".audio-row")
    row.first.wait_for()
    assert row.count() == 1  # only the overview, not the markdown document
    assert "Bees" in row.inner_text() and "Not started" in row.inner_text()
    assert phone.locator(".status-filter").inner_text().split("\n")[0] == "All 1"
    _no_sideways_scroll(phone)

    row.locator("a.card").click()
    _status_line(phone).wait_for()
    assert "Not started" in _status_line(phone).inner_text()
    frame = phone.frame_locator("iframe.frame")
    frame.locator("#play").click()
    phone.wait_for_timeout(1800)  # about 7 s of the clip at RATE
    frame.locator("#pause").click()
    phone.wait_for_function("document.querySelector('.listening [role=status]').textContent.indexOf('In progress') === 0")
    assert "stopped at 0:0" in _status_line(phone).inner_text()
    _no_sideways_scroll(phone)

    tablet = device()  # another device: the same record, from the server
    tablet.goto(f"{site['base']}/audio?status=started")
    tablet.locator(".audio-row").first.wait_for()
    assert "In progress" in tablet.locator(".audio-row").inner_text()
    tablet.locator(".audio-row a.card").click()
    _status_line(tablet).wait_for()
    assert tablet.get_by_role("button", name="Start over").count() == 1
    tframe = tablet.frame_locator("iframe.frame")
    tframe.locator("#play").click()  # picks up where the phone stopped
    tablet.wait_for_timeout(500)
    assert tframe.locator("body").evaluate("() => window.player.currentTime") >= 5
    # the rest of it here: between the two devices it was heard whole, so it counts as a listen
    tablet.wait_for_function("document.querySelector('.listening [role=status]').textContent.indexOf('Done') === 0", timeout=15000)
    assert "heard to the end once" in _status_line(tablet).inner_text()

    phone.goto(f"{site['base']}/audio")
    phone.locator(".audio-row").first.wait_for()
    phone.get_by_role("button", name="Done 1").click()
    assert "1× to the end" in phone.locator(".audio-row").inner_text()
    phone.get_by_role("button", name="Not started 0").click()
    assert phone.locator(".audio-list .empty").count() == 1


def test_dragging_to_the_end_is_not_a_listen(device, serve, tmp_path):
    store = DocStore(tmp_path / "data")
    over = store.publish(text=PLAYER % (_silence_wav(), RATE), title="Listen: Wasps", filename="overview.html", tags=[TAG])
    phone = device()
    phone.goto(f"{serve(store)}/d/{over['id']}")
    _status_line(phone).wait_for()
    phone.frame_locator("iframe.frame").locator("#end").click()
    phone.wait_for_timeout(1500)
    assert "to the end" not in _status_line(phone).inner_text()
    assert not _status_line(phone).inner_text().startswith("Done")


def test_mark_done_from_the_list_and_search(device, site):
    phone = device()
    phone.goto(f"{site['base']}/audio")
    phone.locator(".audio-row").first.wait_for()
    mark = phone.locator(".audio-row .mark")
    if mark.get_attribute("aria-pressed") == "true":  # the other test may have finished it
        mark.click()
        phone.wait_for_function("document.querySelector('.audio-row .mark').getAttribute('aria-pressed') === 'false'")
    phone.locator(".audio-row .mark").click()
    phone.wait_for_function("document.querySelector('.audio-row .mark').getAttribute('aria-pressed') === 'true'")
    assert "Done" in phone.locator(".audio-row").inner_text()
    phone.get_by_role("searchbox", name="Search the overviews").fill("wasps")
    phone.locator(".audio-list .empty").wait_for()
    assert "Clear the search" in phone.locator(".audio-list .empty").inner_text()
    _no_sideways_scroll(phone)


def test_an_overview_that_failed_shows_why_and_can_be_asked_for_again(device, serve, tmp_path):
    from annals import overview

    store = DocStore(tmp_path / "data")
    src = store.publish(text="# Moths", title="Moths at night", filename="moths.md")["id"]
    why = 'RuntimeError: claude -p exited 1: {"result": "' + "x" * 250 + '"}'  # long and unbroken, as the real one
    overview.Requests(store.target.root).put(src, {"state": overview.FAILED, "minutes": 5, "requested": overview._now(), "finished": overview._now(), "error": why})
    phone = device()
    phone.goto(f"{serve(store, overviews=True)}/audio")
    row = phone.locator(".unmade-row")
    row.wait_for()
    text = row.inner_text()
    assert "Moths at night" in text and "Did not work" in text and "tried just now" in text and "document from" in text
    assert "No spoken overviews yet" in phone.locator(".audio-list").inner_text()
    assert row.locator(".why").is_hidden()
    assert row.bounding_box()["height"] < 120  # a title and one line of state, Try again beside them
    if SHOTS:
        phone.screenshot(path=f"{SHOTS}/unmade-closed.png")
    row.get_by_role("button", name="Why").click()
    assert "claude -p exited 1" in row.locator(".why").inner_text()
    _no_sideways_scroll(phone)
    if SHOTS:
        phone.screenshot(path=f"{SHOTS}/unmade-open.png")
    row.get_by_role("button", name="Try again").click()
    phone.wait_for_function("document.querySelector('.unmade-row').textContent.indexOf('Being made') >= 0")
    assert overview.Requests(store.target.root).get(src)["state"] == overview.QUEUED
    phone.get_by_role("button", name="Done 0").click()
    assert phone.locator(".unmade").is_hidden()  # not what a "done" filter asks about


def test_when_the_maker_is_down_the_page_says_why_and_offers_no_try_again(device, serve, tmp_path):
    """The owner pressed Try again on two days while the server's login had expired (annals#62)."""
    from annals import overview

    store = DocStore(tmp_path / "data")
    requests = overview.Requests(store.target.root)
    waits = store.publish(text="# Moths", title="Moths at night", filename="moths.md")["id"]
    failed = store.publish(text="# Owls", title="Owls", filename="owls.md")["id"]
    now = overview._now()
    requests.put(failed, {"state": overview.FAILED, "minutes": 5, "requested": now, "finished": now, "error": "the login expired"})
    overview.mark_down(requests, "the server's login expired", link="https://github.com/someone/platform/issues/563")
    overview.request(store, requests, waits, minutes=3)
    base = serve(store, overviews=True)
    phone = device()
    phone.goto(f"{base}/audio")
    note = phone.locator(".down")
    note.wait_for()
    assert "Listening is off" in note.inner_text() and "the server's login expired" in note.inner_text()
    assert note.get_by_role("link", name="platform#563").get_attribute("href").endswith("/issues/563")
    phone.locator(".unmade-row").nth(1).wait_for()
    assert "Waiting (3 min)" in phone.locator(".unmade").inner_text()
    assert phone.get_by_role("button", name="Try again").count() == 0
    _no_sideways_scroll(phone)
    if SHOTS:
        phone.screenshot(path=f"{SHOTS}/maker-down.png")
    phone.goto(f"{base}/d/{waits}")
    phone.get_by_role("button", name="Listen").click()
    panel = phone.locator(".listen-panel")
    panel.locator(".down").wait_for()
    assert "is waiting" in panel.inner_text() and panel.get_by_role("button").count() == 0


#: a transcript player in the shape of @zodal/speech's: tapping a line seeks, then plays
LINES_PLAYER = """<!doctype html><html><head><meta charset="utf-8"><title>Lines</title></head><body>
<p class="line" data-at="0">Zero.</p><p class="line" data-at="1">One.</p>
<p class="line" data-at="2">Two.</p><p class="line" data-at="3">Three.</p>
<script>
  var bytes = Uint8Array.from(atob("%s"), function (c) { return c.charCodeAt(0); });
  var player = document.createElement("audio");
  player.src = URL.createObjectURL(new Blob([bytes], {type: "audio/wav"}));
  document.body.appendChild(player);
  window.player = player;
  document.querySelectorAll(".line").forEach(function (line) {
    line.onclick = function () { player.currentTime = Number(line.dataset.at); player.play(); };
  });
</script></body></html>"""


#: resolves when the audio has ended; fails rather than hangs if it never does
_UNTIL_ENDED = """a => new Promise((ok, no) => {
  if (a.ended) return ok();
  a.addEventListener('ended', () => ok(), {once: true});
  setTimeout(() => no(new Error('the audio never ended')), 10000);
})"""


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
def test_tapping_a_line_after_the_end_plays_from_that_line(engine, request, serve, tmp_path):
    """Reported 2026-11-13 on an iPad: once the audio had finished, tapping the transcript
    played it again from the start, not from the line tapped. WebKit (every iPhone and iPad
    browser) starts an ended element from its end or from 0 when a seek is still landing as
    play() is called; the relay (annals.media) holds play() until the seek lands. The race is
    lost most of the time without the fix, so several taps make a miss near-certain."""
    browser = request.getfixturevalue(engine)
    store = DocStore(tmp_path / "data")
    over = store.publish(text=LINES_PLAYER % _silence_wav(seconds=4), title="Listen: Lines", filename="overview.html", tags=[TAG])
    page = browser.new_page()
    try:
        page.goto(f"{serve(store)}/d/{over['id']}")
        frame = page.frame_locator("iframe.frame")
        audio = frame.locator("audio")
        for attempt in range(4):
            frame.locator(".line").nth(3).click()
            audio.evaluate(_UNTIL_ENDED)
            page.wait_for_timeout(100 + 150 * attempt)
            frame.locator(".line").nth(1).click()
            page.wait_for_timeout(600)
            at, paused = audio.evaluate("a => [a.currentTime, a.paused]")
            assert not paused and 1.1 < at < 2.5, f"{engine}, tap {attempt}: at {at:.2f}s, paused={paused}; expected playing from 1s"
    finally:
        page.close()


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
def test_a_pause_while_a_play_is_held_wins(engine, request, serve, tmp_path):
    """The relay holds play() of an ended element until its seek lands; a pause() meanwhile
    (a stop button, pausing the other players) must win, and the held play() rejects with
    AbortError as a native one would (review of annals#68)."""
    browser = request.getfixturevalue(engine)
    store = DocStore(tmp_path / "data")
    over = store.publish(text=LINES_PLAYER % _silence_wav(seconds=4), title="Listen: Pause", filename="overview.html", tags=[TAG])
    page = browser.new_page()
    try:
        page.goto(f"{serve(store)}/d/{over['id']}")
        frame = page.frame_locator("iframe.frame")
        audio = frame.locator("audio")
        frame.locator(".line").nth(3).click()
        audio.evaluate(_UNTIL_ENDED)
        outcome = audio.evaluate("""a => new Promise(done => {
          a.currentTime = 1;
          const p = a.play();
          a.pause();
          let how = 'pending';
          p.then(() => { how = 'resolved'; }, e => { how = e.name; });
          setTimeout(() => done([how, a.paused, a.currentTime]), 700);
        })""")
        how, paused, at = outcome
        assert paused, f"{engine}: playing at {at:.2f}s after pause()"
        assert how == "AbortError", f"{engine}: the play() promise {how}"
    finally:
        page.close()
