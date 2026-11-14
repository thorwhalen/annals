"""An audio document plays in the fleet's player, with the timed text published beside it.

An audio file used to get the browser's bare player, with nothing to do but play it (the
owner, 2026-11-13: "I can't do much with that audio"). Now it gets @zodal/speech's player
(seek bar, skips, speed), and its transcript and chapters when they were published beside it
as ``<stem>.vtt`` / ``<stem>.cues.json`` and ``<stem>.chapters.vtt``. Where the reader stopped
is still picked up, since the player plays through the element the listening panel tracks.
At phone size, in Chromium and in WebKit (every browser on an iPhone or iPad).
"""

import io
import json
import os
import struct
import wave

import pytest

from annals.store import DocStore

PHONE = {"width": 390, "height": 844}
#: a folder to save screenshots in, to look at the layout by eye (unset: none are taken)
SHOTS = os.environ.get("ANNALS_TEST_SHOTS")
SECONDS = 30
VTT = """WEBVTT

00:00.000 --> 00:08.000
<v Ana>The opening line.

00:08.000 --> 00:16.000
<v Ana>The middle line.

00:16.000 --> 00:30.000
<v Ana>The closing line.
"""
CHAPTERS = """WEBVTT

00:00.000 --> 00:20.000
Opening

00:20.000 --> 00:30.000
Ending
"""


def _silence_wav(seconds=SECONDS, rate=8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * rate * seconds)
    return buf.getvalue()


@pytest.fixture(scope="module")
def site(tmp_path_factory, serve):
    tmp = tmp_path_factory.mktemp("player")
    store = DocStore(tmp / "data")
    talk = tmp / "Talk"
    talk.mkdir()
    (talk / "talk.wav").write_bytes(_silence_wav())
    (talk / "talk.vtt").write_text(VTT)
    (talk / "talk.chapters.vtt").write_text(CHAPTERS)
    with_text = store.publish(talk, title="Talk")
    bare = tmp / "bare.wav"
    bare.write_bytes(_silence_wav())
    plain = store.publish(bare, title="Bare audio")
    long = tmp / "Long"
    long.mkdir()
    (long / "long.wav").write_bytes(_silence_wav())
    cues = [{"start": i * 0.5, "end": i * 0.5 + 0.5, "text": f"Sentence number {i}, long enough to wrap once on a phone.", "segment": i // 6} for i in range(60)]
    (long / "long.cues.json").write_text(json.dumps({"cues": cues, "chapters": [{"start": 0, "title": "Start"}, {"start": 15, "title": "Half"}]}))
    lengthy = store.publish(long, title="A long transcript")
    return {"base": serve(store), "talk": with_text, "plain": plain, "long": lengthy}


@pytest.fixture(params=["chromium", "webkit"])
def phone(request):
    browser = request.getfixturevalue(request.param)
    ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=request.param == "chromium")
    yield ctx.new_page()
    ctx.close()


def _open(page, base, doc):
    page.goto(f"{base}/d/{doc['id']}")
    page.wait_for_selector(".zs-player")
    page.wait_for_function("document.querySelector('.zs-player audio').readyState >= 1")


def _time(page):
    return page.evaluate("document.querySelector('.zs-player audio').currentTime")


def test_audio_beside_its_timed_text_is_one_audio_document(site):
    assert site["talk"]["kind"] == "audio"
    assert site["talk"]["main"] == "talk.wav"


def test_the_transcript_plays_from_a_tapped_line(phone, site):
    _open(phone, site["base"], site["talk"])
    lines = phone.locator(".zs-s")
    assert lines.count() == 3
    assert phone.locator(".zs-player audio[controls]").count() == 0, "the browser's bare player is gone"
    lines.nth(1).tap()
    phone.wait_for_function("!document.querySelector('.zs-player audio').paused")
    assert 8 <= _time(phone) < 9
    assert phone.evaluate("document.documentElement.scrollWidth") <= PHONE["width"]


def test_chapters_play_from_a_tapped_chapter(phone, site):
    _open(phone, site["base"], site["talk"])
    chapters = phone.locator(".zs-ch")
    assert [" ".join(t.split()) for t in chapters.all_inner_texts()] == ["0:00 Opening", "0:20 Ending"]
    assert chapters.nth(0).bounding_box()["height"] >= 44
    chapters.nth(1).tap()
    phone.wait_for_function("!document.querySelector('.zs-player audio').paused")
    assert 20 <= _time(phone) < 21
    phone.wait_for_function("document.querySelectorAll('.zs-ch')[1].getAttribute('aria-current') === 'true'")


def test_audio_without_timed_text_gets_the_transport_alone(phone, site):
    _open(phone, site["base"], site["plain"])
    assert phone.locator(".zs-text").count() == 0
    for control in (".zs-play", ".zs-skip", ".zs-speed"):
        assert phone.locator(control).first.is_visible()
    assert phone.locator(".zs-seek").bounding_box()["height"] >= 44
    phone.locator(".zs-skip").nth(1).tap()  # ahead 10 s
    phone.wait_for_function("document.querySelector('.zs-player audio').currentTime >= 9")


def test_it_picks_up_where_the_reader_stopped(phone, site):
    """Another device stopped at 0:14 (the record its page sends on pause, seeded here so the
    test does not hang on the machine's audio clock); this one opens the audio there."""
    audio = "document.querySelector('.zs-player audio')"
    doc = site["plain"]["id"]
    saved = phone.request.post(f"{site['base']}/api/listening/{doc}", data={"spans": [[0, 14.6]], "duration": SECONDS, "position": 14.6})
    assert saved.ok, saved.text()
    _open(phone, site["base"], site["plain"])
    phone.wait_for_function(f"{audio}.currentTime >= 14")
    # the player's readout says so too, whether the seek landed before it came or after
    phone.wait_for_function("document.querySelector('.zs-now').textContent === '0:14'")
    assert phone.locator(".listening").get_by_text("Start over").count() == 1
    phone.request.delete(f"{site['base']}/api/listening/{doc}")


def test_the_transport_stays_in_sight_below_the_masthead(phone, site):
    _open(phone, site["base"], site["long"])
    assert phone.locator(".zs-text p").count() == 10, "a cues JSON keeps its paragraphs"
    assert phone.evaluate("scrollY") == 0, "opening the page never scrolls it"
    if SHOTS:
        phone.screenshot(path=os.path.join(SHOTS, "audio-player-top.png"))
    phone.mouse.wheel(0, 2000)
    phone.wait_for_timeout(300)
    head = phone.locator("header.bar").bounding_box()
    bar = phone.locator(".zs-bar").bounding_box()
    assert head["y"] + head["height"] - 1 <= bar["y"] < head["y"] + head["height"] + 4
    assert phone.evaluate("document.documentElement.scrollWidth") <= PHONE["width"]
    if SHOTS:
        phone.screenshot(path=os.path.join(SHOTS, "audio-player-scrolled.png"))
