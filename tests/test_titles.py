"""No generic titles, and the owner can rename: a document or a group, from the page or the CLI.

Seven audio overviews were all titled "overview": two makers write ``<folder>/overview.mp3``
and annals titled a file by its name. A name that says nothing now takes its title from
beside the file (a manifest's ``title``, else the folder). And any title can be changed.
"""

import io
import json

import pytest
from fastapi.testclient import TestClient

from annals.__main__ import run
from annals.api import mk_api, mk_app
from annals.auth import no_auth
from annals.store import DocStore

MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00fake audio"


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


def _overview(folder, manifest=None, name="overview.mp3"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(MP3)
    if manifest is not None:
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder / name


def test_a_generic_file_takes_its_makers_title(store, tmp_path):
    f = _overview(tmp_path / "20261119-223540-theremin-7d32", {"title": "The Theremin: Invention, Spies and Halloween"})
    assert store.publish(f)["title"] == "The Theremin: Invention, Spies and Halloween"


def test_a_generic_file_with_no_manifest_takes_its_folders_name(store, tmp_path):
    f = _overview(tmp_path / "20261119-224931-jazz-chords-harmony-for-beginners-46e3")
    assert store.publish(f)["title"] == "jazz chords harmony for beginners"


def test_hailings_meta_json_names_it_too(store, tmp_path):
    folder = tmp_path / "20261112-124253-arioso-app-mac-38e4"
    f = _overview(folder)
    (folder / "meta.json").write_text(json.dumps({"title": "Arioso Studio: what shipped, what waits"}))
    (folder / "overview.vtt").write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nHi\n")
    meta = store.publish(f, folder / "overview.vtt")  # the audio with its timed text
    assert meta["title"] == "Arioso Studio: what shipped, what waits"


def test_a_name_that_says_something_is_kept_and_a_given_title_wins(store, tmp_path):
    folder = tmp_path / "20261119-223540-theremin-7d32"
    _overview(folder, {"title": "From the manifest"})
    assert store.publish(_overview(folder, name="theremin-history.mp3"))["title"] == "theremin-history"
    assert store.publish(folder / "overview.mp3", title="Given")["title"] == "Given"


def test_when_nothing_beside_it_says_more_the_name_stays(store, tmp_path):
    assert store.publish(_overview(tmp_path / "tmp"))["title"] == "overview"


def test_a_page_called_index_with_a_heading_keeps_its_heading(store, tmp_path):
    folder = tmp_path / "20261101-site-ab12"
    folder.mkdir()
    (folder / "index.md").write_text("# Real heading\n\nbody")
    assert store.publish(folder / "index.md")["title"] == "Real heading"


# -- rename -----------------------------------------------------------------------------


def test_rename_sticks_through_a_new_version(store, tmp_path):
    f = tmp_path / "r.md"
    f.write_text("# First\n\nv1")
    doc = store.publish(f)["id"]
    assert store.rename(doc, "  My   name ")["title"] == "My name"
    f.write_text("# Publisher's new heading\n\nv2")
    after = store.publish(f, replace=doc)
    assert after["title"] == "My name" and after["version"] == 2
    with pytest.raises(ValueError):
        store.rename(doc, "   ")


def test_rename_in_the_bin(store, tmp_path):
    doc = store.publish(text="# A", title="A")["id"]
    store.trash(doc)
    assert store.rename(doc, "B")["title"] == "B"
    assert store.meta(doc)["in_trash"] and store.restore(doc)["title"] == "B"


def test_the_api_renames_documents_and_groups_and_refuses_odd_bodies(store):
    doc = store.publish(text="# A", title="A")["id"]
    g = store.make_group("G", [doc])
    client = TestClient(mk_app(store=store, authorizer=no_auth))
    r = client.patch(f"/annals/api/docs/{doc}", json={"title": "New A"})
    assert r.status_code == 200 and r.json()["title"] == "New A"
    assert client.get(f"/annals/api/docs/{doc}").json()["title"] == "New A"
    assert client.patch(f"/annals/api/docs/{doc}", json={"title": ""}).status_code == 422
    assert client.patch(f"/annals/api/docs/{doc}", json={"title": "x", "tags": []}).status_code == 422
    assert client.patch("/annals/api/docs/20260101-000000-nope-ab12", json={"title": "x"}).status_code == 404
    assert client.patch(f"/annals/api/groups/{g['id']}", json={"title": "New G"}).json()["title"] == "New G"
    assert store.group(g["id"])["docs"] == [doc]


def test_a_room_cannot_rename(store):
    doc = store.publish(text="# A", title="A")["id"]
    room = TestClient(mk_api(store=store, room=True))
    assert room.patch(f"/docs/{doc}", json={"title": "x"}).status_code in (403, 405)
    assert store.meta(doc)["title"] == "A"


def test_the_cli_renames(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("ANNALS_TARGET", str(data))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://example.test/annals")
    monkeypatch.delenv("ANNALS_OUTBOX", raising=False)
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    store = DocStore(data)
    doc = store.publish(text="# A", title="A")["id"]
    g = store.make_group("G", [doc])
    for ref, title in ((f"https://example.test/annals/d/{doc}", "Doc B"), (f"https://example.test/annals/g/{g['id']}", "Group B")):
        out, err = io.StringIO(), io.StringIO()
        assert run(["rename", ref, title], out=out, err=err) == 0, err.getvalue()
    assert store.meta(doc)["title"] == "Doc B" and store.group(g["id"])["title"] == "Group B"


# -- the page ---------------------------------------------------------------------------


@pytest.fixture
def phone(chromium):
    ctx = chromium.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    yield ctx.new_page()
    ctx.close()


def test_the_pencil_beside_the_title_renames_in_place(store, serve, phone):
    doc = store.publish(text="# overview\n\nbody", title="overview")["id"]
    phone.goto(f"{serve(store)}/d/{doc}")
    pencil = phone.locator(".doc-head .rename-btn")
    pencil.wait_for()
    box = pencil.bounding_box()
    assert box["width"] >= 44 and box["height"] >= 44  # a thumb's size on a phone
    pencil.click()
    field = phone.locator(".doc-head .title-input")
    assert field.input_value() == "overview"
    field.press("Escape")  # Escape puts the old title back, nothing saved
    assert phone.locator(".doc-head h2").text_content() == "overview"
    pencil.click()
    field.fill("Jazz chords from the ground up")
    field.press("Enter")
    phone.locator(".doc-head h2", has_text="Jazz chords").wait_for()
    assert store.meta(doc)["title"] == "Jazz chords from the ground up"
