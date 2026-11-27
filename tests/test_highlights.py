"""Highlights: the passages a reader kept, on the server (the page side is manicules).

The owner asked to select part of a document and save it, with an optional name, tags and
comment, to search those, and to keep a whole document by highlighting its title
(2026-11-27). These pin what a highlight may be, the API (per reader, behind the login,
refusing junk and cross-site writes), the agent verbs, and that the vendored widget is the
one the page loads.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from annals import highlights as H
from annals import tools
from annals.api import ROOM_ROUTES, mk_api, mk_app
from annals.auth import BasicAuth, no_auth
from annals.store import DocStore
from annals.tags import MAX_TAG_LEN, MAX_TAGS_PER_ITEM, normalize_tags

UI = Path(__file__).parent.parent / "annals" / "data" / "ui"


def target(doc="d1", exact="85 percent water", **over):
    return {
        "source": {"id": doc, "title": "Bread notes", "url": f"d/{doc}"},
        "part": "body",
        "quote": {"exact": exact, "prefix": "A rye loaf takes ", "suffix": ", and"},
        "position": {"start": 310, "end": 327},
        **over,
    }


@pytest.fixture
def store(tmp_path):
    s = DocStore(tmp_path / "data")
    (tmp_path / "notes.md").write_text("# Bread notes\n\nA rye loaf takes 85 percent water, and more.\n")
    s.doc = s.publish(tmp_path / "notes.md", title="Bread notes")["id"]
    return s


@pytest.fixture
def client(store):
    return TestClient(mk_api(store=store))


# -- the model ---------------------------------------------------------------------
def test_a_highlight_gets_the_default_name_and_keeps_only_known_fields():
    rec = H.clean({"target": target(), "junk": 1, "tags": ["b", "A", "a"]}, names=["x"])
    assert rec["name"] == "Bread notes-highlight-2"
    assert rec["tags"] == ["A", "b"] and rec["comment"] == "" and "color" not in rec
    assert "junk" not in rec and rec["target"]["position"] == {"start": 310, "end": 327}
    assert rec["id"].startswith("h") and rec["created"]


def test_the_name_counts_the_pages_highlights_and_never_repeats():
    assert H.default_name("T", ["T-highlight-2"]) == "T-highlight-3"
    assert H.default_name("T", ["T-highlight-2", "x", "T-highlight-3"]) == "T-highlight-4"


def test_a_whole_part_needs_no_quote_and_a_target_needs_one_or_the_other():
    whole = H.clean_target({"source": {"id": "d1"}, "part": "title", "whole": True})
    assert whole == {"source": {"id": "d1"}, "part": "title", "whole": True}
    with pytest.raises(ValueError, match="quote, or is the whole part"):
        H.clean_target({"source": {"id": "d1"}})


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"target": {}},
        {"target": {"source": {"id": ""}, "quote": {"exact": "x"}}},
        {"target": {"source": {"id": "d"}, "quote": {"exact": ""}}},
        {"target": {"source": {"id": "d"}, "quote": {"exact": "x" * (H.MAX_EXACT_LEN + 1)}}},
        {"target": {"source": {"id": "d"}, "quote": {"exact": "x"}, "part": "a b"}},
        {"target": {"source": {"id": "d"}, "quote": {"exact": "x"}, "position": {"start": 5, "end": 2}}},
        {"target": {"source": {"id": "d"}, "quote": {"exact": "x"}, "position": {"start": True, "end": 2}}},
        {"target": {"source": {"id": "d", "url": "javascript:alert(1)"}, "quote": {"exact": "x"}}},
        {"target": {"source": {"id": "d", "url": "java\tscript:alert(1)"}, "quote": {"exact": "x"}}},
        {"target": {"source": {"id": "d", "url": "//evil.example/x"}, "quote": {"exact": "x"}}},
        {"target": {"source": {"id": "d", "url": "https://elsewhere.example/x"}, "quote": {"exact": "x"}}},
        {"target": {"source": {"id": "d"}, "quote": {"exact": "half \ud83d of a character"}}},
        {"target": {"source": {"id": "d"}, "quote": {"exact": "x", "prefix": "\ude00 cut"}}},
        {"target": target(), "id": "settings"},
        {"target": target(), "name": "bell\x07"},
        {"target": target(), "id": "../etc"},
        {"target": target(), "color": "red; background: url(x)"},
        {"target": target(), "tags": "not-a-list"},
        {"target": target(), "name": "x" * (H.MAX_NAME_LEN + 1)},
        {"target": target(), "created": "yesterday"},
    ],
)
def test_junk_is_refused(bad):
    with pytest.raises(ValueError):
        H.clean(bad)


def test_a_passage_is_kept_as_the_document_has_it_escape_codes_included():
    rec = H.clean({"target": {"source": {"id": "log"}, "quote": {"exact": "\x1b[31mERROR\x1b[0m disk full"}}})
    assert rec["target"]["quote"]["exact"] == "\x1b[31mERROR\x1b[0m disk full"


def test_search_needs_every_word_and_answers_newest_first():
    a = H.clean({"target": target(), "name": "Water", "comment": "the table I wanted"}, now="2026-11-01T00:00:00+00:00")
    b = H.clean({"target": target("d2", "fixed at 10k"), "tags": ["money"]}, now="2026-11-02T00:00:00+00:00")
    records = {a["id"]: a, b["id"]: b}
    assert [r["id"] for r in H.search(records)] == [b["id"], a["id"]]
    assert [r["id"] for r in H.search(records, "TABLE water")] == [a["id"]]
    assert H.search(records, "table money") == []
    assert [r["id"] for r in H.search(records, source="d2")] == [b["id"]]
    assert [r["id"] for r in H.search(records, tag="MONEY")] == [b["id"]]
    assert [r["id"] for r in H.search(records, "bread")] == [b["id"], a["id"]]  # the page's title


def test_only_name_note_tags_and_colour_can_change():
    assert H.clean_patch({"comment": "", "color": None}) == {"comment": "", "color": None}
    for bad in ({"target": target()}, {"id": "x"}, {"name": ""}, {"color": "red"}, []):
        with pytest.raises(ValueError):
            H.clean_patch(bad)
    rec = H.apply_patch({"id": "h", "color": "green", "comment": "a"}, {"color": None, "comment": "b"})
    assert "color" not in rec and rec["comment"] == "b" and rec["modified"]


VENDORED = UI / "vendor" / "manicules"


def test_the_shape_and_every_limit_are_the_vendored_schemas():
    """One schema, two languages: the widget ships its JSON Schema, and this module says the same."""
    defs = json.loads((VENDORED / "highlight.schema.json").read_text())["$defs"]
    settings = defs["Settings"]["properties"]
    assert tuple(settings["color"]["enum"]) == H.PALETTE
    assert settings["color"]["default"] == H.DEFAULT_SETTINGS["color"]
    assert settings["showOthers"]["default"] is H.DEFAULT_SETTINGS["showOthers"]
    props = defs["Highlight"]["properties"]
    assert set(props) == {"id", "name", "target", "comment", "tags", "color", "created", "modified"}
    assert set(defs["HighlightPatch"]["properties"]) == set(H.PATCHABLE)
    assert props["name"]["maxLength"] == H.MAX_NAME_LEN
    assert props["comment"]["maxLength"] == H.MAX_COMMENT_LEN
    assert props["tags"]["maxItems"] == MAX_TAGS_PER_ITEM
    assert props["tags"]["items"]["maxLength"] == MAX_TAG_LEN
    target_ = props["target"]["properties"]
    assert set(target_) == {"source", "part", "quote", "position", "whole"}
    assert target_["part"]["default"] == H.DEFAULT_PART
    source = target_["source"]["properties"]
    assert (source["id"]["maxLength"], source["title"]["maxLength"], source["url"]["maxLength"]) == (
        H.MAX_SOURCE_ID_LEN, H.MAX_TITLE_LEN, H.MAX_URL_LEN)
    quote = target_["quote"]["properties"]
    assert quote["exact"]["maxLength"] == H.MAX_EXACT_LEN
    assert quote["prefix"]["maxLength"] == quote["suffix"]["maxLength"] == H.MAX_CONTEXT_LEN
    # the id and part rules are patterns in the schema: this module must agree with them case by case
    id_ok, part_ok = re.compile(props["id"]["pattern"]), re.compile(target_["part"]["pattern"])
    for candidate in ("h1", "a" * 64, "a" * 65, "", "settings", "Settings", "a b", "../x", "h_1-Z", "é"):
        def accepted(field, value):
            data = {"target": target(), "id": "ok"}
            if field == "id":
                data["id"] = value
            else:
                data["target"] = target(part=value)
            try:
                H.clean(data)
                return True
            except ValueError:
                return False
        assert accepted("id", candidate) == bool(id_ok.match(candidate)), candidate
        if candidate:  # an absent part is the default one, not a refusal
            assert accepted("part", candidate) == bool(part_ok.match(candidate)), candidate


def test_the_rules_shared_with_the_page_are_the_packages_own():
    """Default names, tags and search exist once in JavaScript (the page) and once here (the
    routes, the verbs): the package ships its answers, and this module must give the same."""
    vectors = json.loads((VENDORED / "conformance.json").read_text())
    for case in vectors["defaultName"]:
        assert H.default_name(case["title"], case["existing"]) == case["expected"], case
    for case in vectors["normalizeTags"]:
        assert normalize_tags(case["input"]) == case["expected"], case
    library = {h["id"]: h for h in vectors["search"]["library"]}
    assert len(vectors["search"]["cases"]) > 8
    for case in vectors["search"]["cases"]:
        q = case["query"]
        found = H.search(library, q.get("search", ""), source=q.get("source"), tag=q.get("tag"))
        assert [h["id"] for h in found] == case["expected"], case
    for case in vectors["safeUrl"]:
        # this host is stricter than the page (a document's address is always relative here), never looser
        try:
            kept = H._page_url(case["url"])
        except ValueError:
            kept = ""
        assert kept in ("", case["expected"]), case
        if case["expected"] and not case["expected"].startswith(("http", "/")):
            assert kept == case["expected"], case


def test_what_is_vendored_is_what_was_built():
    """SOURCE.json names the commit and the version, and a sha256 of each file beside it."""
    manifest = json.loads((VENDORED / "SOURCE.json").read_text())
    assert manifest["package"] == "manicules" and len(manifest["commit"]) == 40 and manifest["version"]
    on_disk = sorted(p.name for p in VENDORED.iterdir() if p.is_file() and p.name != "SOURCE.json")
    assert sorted(manifest["sha256"]) == on_disk
    assert {"manicules.global.js", "styles.css", "highlight.schema.json", "conformance.json", "LICENSE", "THIRD_PARTY_NOTICES.md"} <= set(on_disk)
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((VENDORED / name).read_bytes()).hexdigest() == digest, name


# -- the API -----------------------------------------------------------------------
def test_keep_list_change_and_remove(client):
    assert client.get("/highlights").json() == {"data": [], "total": 0}
    made = client.post("/highlights", json={"target": target(), "id": "hpage1"}).json()
    assert made["id"] == "hpage1" and made["name"] == "Bread notes-highlight-1"
    assert made["href"] == "d/d1?h=hpage1"
    second = client.post("/highlights", json={"target": target(exact="more"), "comment": "why"}).json()
    assert second["name"] == "Bread notes-highlight-2"
    rows = client.get("/highlights").json()
    assert rows["total"] == 2 and {r["id"] for r in rows["data"]} == {"hpage1", second["id"]}
    assert [r["id"] for r in client.get("/highlights", params={"q": "why"}).json()["data"]] == [second["id"]]
    assert client.get("/highlights", params={"source": "elsewhere"}).json()["total"] == 0
    changed = client.patch("/highlights/hpage1", json={"comment": "note", "tags": ["x"], "color": "blue"}).json()
    assert (changed["comment"], changed["tags"], changed["color"]) == ("note", ["x"], "blue")
    assert "color" not in client.patch("/highlights/hpage1", json={"color": None}).json()
    assert client.get("/highlights/hpage1").json()["comment"] == "note"
    gone = client.delete("/highlights/hpage1").json()
    assert gone["id"] == "hpage1" and client.get("/highlights/hpage1").status_code == 404
    # undo: the page posts back exactly what it was given
    assert client.post("/highlights", json=gone).json()["created"] == gone["created"]


def test_a_file_of_a_document_links_with_its_own_query(client):
    t = target()
    t["source"]["url"] = "d/d1?f=a.md"
    assert client.post("/highlights", json={"target": t, "id": "hf"}).json()["href"] == "d/d1?f=a.md&h=hf"


def test_refusals_say_why(client):
    assert client.post("/highlights", json={"target": {}}).status_code == 422
    client.post("/highlights", json={"target": target(), "id": "hx"})
    twice = client.post("/highlights", json={"target": target(), "id": "hx"})
    assert twice.status_code == 422 and "already exists" in twice.json()["detail"]
    assert client.patch("/highlights/hx", json={"target": target()}).status_code == 422
    assert client.patch("/highlights/nope", json={"comment": "x"}).status_code == 404
    assert client.delete("/highlights/nope").status_code == 404
    assert client.get("/highlights/nope").status_code == 404


def test_settings_default_then_change_then_refuse_junk(client):
    assert client.get("/highlights/settings").json() == {"color": "yellow", "showOthers": True}
    assert client.put("/highlights/settings", json={"color": "green"}).json() == {"color": "green", "showOthers": True}
    assert client.put("/highlights/settings", json={"showOthers": False}).json() == {"color": "green", "showOthers": False}
    for bad in ({"color": "red"}, {"showOthers": "no"}, {"theme": "x"}, {"color": None}):
        assert client.put("/highlights/settings", json=bad).status_code == 422
    assert client.get("/highlights/settings").json() == {"color": "green", "showOthers": False}


def test_each_reader_has_their_own_and_they_live_under_the_data_root(store):
    who = {"name": "ann@example.org"}
    c = TestClient(mk_api(store=store, reader=lambda request: who["name"]))
    c.post("/highlights", json={"target": target(), "id": "hann"})
    c.put("/highlights/settings", json={"color": "pink"})
    who["name"] = "bob@example.org"
    assert c.get("/highlights").json()["total"] == 0
    assert c.get("/highlights/hann").status_code == 404
    assert c.delete("/highlights/hann").status_code == 404
    assert c.get("/highlights/settings").json()["color"] == "yellow"
    root = Path(store.target.root)
    on_disk = json.loads((root / "highlights" / "ann@example.org.json").read_text())
    assert list(on_disk) == ["hann"]  # {id: highlight}: the layout manicules' own CLI reads
    assert not (root / "highlights" / "bob@example.org.json").exists()


def test_cross_site_writes_are_refused(client):
    evil = {"sec-fetch-site": "cross-site"}
    assert client.post("/highlights", json={"target": target()}, headers=evil).status_code == 403
    assert client.put("/highlights/settings", json={"color": "green"}, headers=evil).status_code == 403
    assert client.patch("/highlights/x", json={"comment": "x"}, headers=evil).status_code == 403
    assert client.delete("/highlights/x", headers=evil).status_code == 403


def test_highlights_are_behind_the_login(store):
    c = TestClient(mk_app(store=store, authorizer=BasicAuth("me", "pw")), follow_redirects=False)
    assert c.get("/annals/api/highlights").status_code == 401
    assert c.post("/annals/api/highlights", json={"target": target()}).status_code == 401
    assert c.get("/annals/api/highlights", auth=("me", "pw")).json()["total"] == 0


def test_the_page_is_told_whether_highlights_are_kept(store):
    assert TestClient(mk_api(store=store)).get("/sources").json()["highlights"] is True
    off = TestClient(mk_api(store=store, highlights=None))
    assert off.get("/sources").json()["highlights"] is False
    assert off.get("/highlights").status_code == 404
    assert off.post("/highlights", json={"target": target()}).status_code == 404


def test_a_room_keeps_no_highlights(store):
    room = TestClient(mk_api(store=store, room=True))
    assert room.get("/sources").json()["highlights"] is False
    assert room.get("/highlights").status_code == 404
    assert not any("highlight" in route for route in ROOM_ROUTES)
    with pytest.raises(ValueError, match="highlights"):
        mk_api(store=store, room=True, highlights=H.for_reader(store.target.root))


def test_the_routes_are_a_router_any_fastapi_host_can_include():
    """The wire is this module's, not annals' API's: a second host mounts the same seven routes."""
    from fastapi import FastAPI

    from annals.highlights_api import mk_router

    store: dict = {}

    class Mem(dict):
        def snapshot(self):
            return {k: dict(v) if isinstance(v, dict) else v for k, v in self.items()}

        def modify(self, key, change):
            new = change(self.get(key))
            if new is None:
                self.pop(key, None)
            else:
                self[key] = new
            return new

    def for_reader(who):
        return store.setdefault(who, H.ReaderHighlights(Mem(), Mem()))

    host = FastAPI()
    host.include_router(mk_router(for_reader, reader=lambda request: "me"), prefix="/api")
    c = TestClient(host)
    made = c.post("/api/highlights", json={"target": target()}).json()
    assert made["name"] == "Bread notes-highlight-1"
    assert c.get("/api/highlights").json()["total"] == 1
    assert c.put("/api/highlights/settings", json={"color": "blue"}).json()["color"] == "blue"
    assert c.delete(f"/api/highlights/{made['id']}").json()["id"] == made["id"]
    # and with no store at all, every route says so
    off = FastAPI()
    off.include_router(mk_router(None, reader=lambda request: "me"))
    assert TestClient(off).get("/highlights").status_code == 404


def test_a_reader_is_capped_in_number_and_in_room(client, monkeypatch):
    monkeypatch.setattr(H, "MAX_HIGHLIGHTS", 2)
    for i in range(2):
        assert client.post("/highlights", json={"target": target(exact=f"p{i}")}).status_code == 200
    full = client.post("/highlights", json={"target": target(exact="p3")})
    assert full.status_code == 422 and "at most 2" in full.json()["detail"]
    monkeypatch.setattr(H, "MAX_HIGHLIGHTS", 5000)
    monkeypatch.setattr(H, "MAX_STORE_BYTES", 10)
    big = client.post("/highlights", json={"target": target(exact="p4")})
    assert big.status_code == 422 and "too much room" in big.json()["detail"]


def test_half_a_character_is_refused_not_a_server_error(client):
    cut = client.post("/highlights", content=b'{"target": {"source": {"id": "d"}, "quote": {"exact": "x", "prefix": "\\ude00 cut"}}}', headers={"content-type": "application/json"})
    assert cut.status_code == 422 and "half of a character" in cut.json()["detail"]
    assert client.get("/highlights").json()["total"] == 0


# -- the page ----------------------------------------------------------------------
def test_the_highlights_page_is_served_and_the_widget_is_vendored_whole(store):
    app = TestClient(mk_app(store=store, authorizer=no_auth))
    assert app.get("/annals/highlights").status_code == 200
    for name in ("manicules.global.js", "styles.css", "highlight.schema.json"):
        assert app.get(f"/annals/api/ui/vendor/manicules/{name}").status_code == 200
    js = (UI / "app.js").read_text()
    assert 'HL_UI = "vendor/manicules/"' in js and "Manicules" in js


# -- the agent verbs ---------------------------------------------------------------
@pytest.fixture
def cli(store, monkeypatch, tmp_path):
    monkeypatch.setenv("ANNALS_CONFIG", str(tmp_path / "no-config.toml"))

    def run(verb, *args, **kwargs):
        kwargs.setdefault("target", str(store.target.root))
        return getattr(tools, verb)(*args, **kwargs)

    run.doc = store.doc
    return run


def test_an_agent_keeps_finds_changes_and_removes(cli, store):
    made = cli("highlight_add", cli.doc, "85 percent water", prefix="A rye loaf takes ", comment="the number", tags="rye, later", reader="Me@example.org")["highlight"]
    assert made["name"] == "Bread notes-highlight-1" and made["tags"] == ["later", "rye"]
    assert made["target"]["source"] == {"id": cli.doc, "title": "Bread notes", "url": f"d/{cli.doc}"}
    assert made["url"].endswith(f"/d/{cli.doc}?h={made['id']}") and made["reader"] == "me@example.org"
    found = cli("highlights", "number RYE")  # one reader has highlights: no need to name them
    assert found["total"] == 1 and found["reader"] == "me@example.org"
    assert found["highlights"][0]["id"] == made["id"] and found["highlights"][0]["reader"] == "me@example.org"
    assert cli("highlights", "absent")["total"] == 0
    assert cli("highlights", doc=cli.doc, tag="later")["total"] == 1
    assert cli("highlights", reader="someone@example.net")["total"] == 0
    edited = cli("highlight_edit", made["id"], comment="", color="green")["highlight"]
    assert edited["comment"] == "" and edited["color"] == "green"
    assert "color" not in cli("highlight_edit", made["id"], color="default")["highlight"]
    assert cli("highlight_remove", made["id"])["removed"]["id"] == made["id"]
    assert cli("highlights")["total"] == 0


def test_total_counts_matches_before_the_limit(cli):
    for words in ("one", "two", "three"):
        cli("highlight_add", cli.doc, words, reader="me@example.org")
    out = cli("highlights", limit=2)
    assert out["total"] == 3 and len(out["highlights"]) == 2


def test_an_agent_keeps_a_whole_document_by_its_title(cli):
    kept = cli("highlight_add", cli.doc, "Bread notes", whole=True, reader="me@example.org")["highlight"]
    assert kept["target"]["part"] == "title" and kept["target"]["whole"] is True


def test_an_agent_keeps_a_passage_of_one_file_of_a_document(cli, store, tmp_path):
    folder = tmp_path / "Bundle"
    folder.mkdir()
    (folder / "a.md").write_text("# A\n\nfirst file\n")
    (folder / "notes b.md").write_text("# B\n\nsecond file text\n")
    doc = store.publish(folder, title="Bundle")["id"]
    made = cli("highlight_add", doc, "second file text", file="notes b.md", reader="me@example.org")["highlight"]
    assert made["target"]["source"] == {"id": f"{doc}?f=notes b.md", "title": "notes b.md · Bundle", "url": f"d/{doc}?f=notes%20b.md"}
    assert made["url"].endswith(f"/d/{doc}?f=notes%20b.md&h={made['id']}")
    assert cli("highlights", doc=doc)["total"] == 1  # a document's highlights include its files'
    with pytest.raises(ValueError, match="has no file"):
        cli("highlight_add", doc, "x", file="missing.md", reader="me@example.org")


def test_the_page_and_the_agent_share_one_store(cli, store):
    c = TestClient(mk_api(store=store, reader=lambda request: "me@example.org"))
    c.post("/highlights", json={"target": target(store.doc), "id": "hpage"})
    assert [h["id"] for h in cli("highlights")["highlights"]] == ["hpage"]
    cli("highlight_edit", "hpage", comment="from the agent")
    assert c.get("/highlights/hpage").json()["comment"] == "from the agent"
    assert cli("highlights")["highlights"][0]["url"].endswith(c.get("/highlights/hpage").json()["href"])


def test_one_readers_notes_are_never_mixed_with_anothers_or_shown_unasked(cli, monkeypatch):
    with pytest.raises(ValueError, match="nobody has any yet"):
        cli("highlight_add", cli.doc, "x")  # whose?
    assert cli("highlights") == {"highlights": [], "total": 0, "reader": None}
    cli("highlight_add", cli.doc, "x", reader="a@example.org")
    cli("highlight_add", cli.doc, "y", reader="b@example.org")
    with pytest.raises(ValueError, match="2 readers have highlights") as refused:
        cli("highlights")
    assert "@" not in str(refused.value)  # how many, never who
    with pytest.raises(ValueError, match="2 readers have highlights"):
        cli("highlight_edit", "h1", comment="z")
    monkeypatch.setenv("ANNALS_HIGHLIGHTS_READER", "B@example.org")  # the reader an agent surface answers for
    assert cli("highlights")["reader"] == "b@example.org"
    monkeypatch.delenv("ANNALS_HIGHLIGHTS_READER")
    assert [h["target"]["quote"]["exact"] for h in cli("highlights", reader="b@example.org")["highlights"]] == ["y"]
    with pytest.raises(ValueError, match="no highlight with id nope"):
        cli("highlight_edit", "nope", comment="z", reader="a@example.org")
    with pytest.raises(ValueError, match="nothing to change"):
        cli("highlight_edit", "nope", reader="a@example.org")
    with pytest.raises(ValueError, match="not local"):
        cli("highlight_remove", "h1", reader="a@example.org", target="somehost:/srv/annals")


def test_the_verbs_are_classified_and_the_destructive_one_is_not_served_by_default():
    assert tools.EFFECTS["highlights"] == "read"
    assert tools.EFFECTS["highlight_remove"] == "destructive"
    served = {f.__name__ for f in tools.tools_with(tools.DFLT_EFFECTS)}
    assert {"highlights", "highlight_add", "highlight_edit"} <= served
    assert "highlight_remove" not in served
