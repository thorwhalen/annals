"""Each document links to the session(s) that made it, on the owner's page only.

The link is recorded at publish (``CLAUDE_CODE_BRIDGE_SESSION_ID``, or ``--session-url``),
a new version adds its session, the API checks the links again, and nothing that leaves the
owner (a share's meta, page, files and exports; a room) carries them.
"""

import io
import json

import pytest
from fastapi.testclient import TestClient

from annals.__main__ import run
from annals.api import mk_app
from annals.auth import no_auth
from annals.sessions import sessions_of
from annals.share import ScryptHasher, Shares
from annals.share_api import mk_share_api
from annals.store import DocStore, RoomStore, without_provenance

A_URL = "https://claude.ai/code/session_01AAAA"
B_URL = "https://claude.ai/code/session_01BBBB"


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """``cli(*args, bridge=...)`` runs ``annals`` as a session whose bridge id is ``bridge``."""
    data = tmp_path / "data"
    monkeypatch.setenv("ANNALS_TARGET", str(data))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://example.test/annals")
    monkeypatch.delenv("ANNALS_OUTBOX", raising=False)
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    def _run(*args, bridge=None):
        if bridge:
            monkeypatch.setenv("CLAUDE_CODE_BRIDGE_SESSION_ID", bridge)
        else:
            monkeypatch.delenv("CLAUDE_CODE_BRIDGE_SESSION_ID", raising=False)
        out, err = io.StringIO(), io.StringIO()
        rc = run(list(args), out=out, err=err)
        assert rc == 0, err.getvalue()
        return out.getvalue().strip().rsplit("/", 1)[-1]

    _run.store = DocStore(data)
    return _run


@pytest.fixture
def doc(cli, tmp_path):
    src = tmp_path / "r.md"
    src.write_text("# Report\n\nThe body of the report.\n", encoding="utf-8")
    return cli("publish", str(src), "--session", "alpha", bridge="session_01AAAA")


def test_publish_records_the_session_link_from_claude_code(cli, doc):
    meta = cli.store.meta(doc)
    assert meta["sessions"] == [{"name": "alpha", "url": A_URL}]
    assert meta["source"]["session_url"] == A_URL


def test_a_new_version_adds_its_session_after_the_first(cli, doc, tmp_path):
    src = tmp_path / "r2.md"
    src.write_text("# Report\n\nversion two\n", encoding="utf-8")
    cli("publish", str(src), "--replace", doc, "--session", "beta", bridge="session_01BBBB")
    cli("publish", str(src), "--replace", doc, "--session", "alpha", bridge="session_01AAAA")
    assert cli.store.meta(doc)["sessions"] == [
        {"name": "alpha", "url": A_URL},
        {"name": "beta", "url": B_URL},
    ]


def test_session_url_flag_overrides_and_none_leaves_it_out(cli, tmp_path):
    src = tmp_path / "x.md"
    src.write_text("# X\n", encoding="utf-8")
    given = cli("publish", str(src), "--session-url", B_URL, bridge="session_01AAAA")
    assert sessions_of(cli.store.meta(given)) == [{"name": "", "url": B_URL}]
    none = cli("publish", str(src), "--session", "s", "--session-url", "none", bridge="session_01AAAA")
    assert cli.store.meta(none)["sessions"] == [{"name": "s", "url": ""}]
    err = io.StringIO()
    assert run(["publish", str(src), "--session-url", "https://evil.example/x"], out=io.StringIO(), err=err) == 1


def test_ls_finds_a_document_by_any_session_that_made_it(cli, doc, tmp_path):
    src = tmp_path / "r2.md"
    src.write_text("# Report\n\nversion two\n", encoding="utf-8")
    cli("publish", str(src), "--replace", doc, "--session", "beta", bridge="session_01BBBB")
    from annals.tools import ls

    for name in ("alpha", "beta"):
        assert [d["id"] for d in ls(session=name)["docs"]] == [doc], name
    assert ls(session="gamma")["docs"] == []


def test_a_living_page_keeps_its_first_session_and_the_latest(cli, doc, tmp_path):
    from annals.sessions import MAX_SESSIONS

    src = tmp_path / "r2.md"
    for i in range(MAX_SESSIONS + 5):
        src.write_text(f"# Report\n\nversion {i}\n", encoding="utf-8")
        cli("publish", str(src), "--replace", doc, "--session", f"s{i}", bridge=f"session_01S{i}")
    names = [s["name"] for s in cli.store.meta(doc)["sessions"]]
    assert len(names) == MAX_SESSIONS
    assert names[0] == "alpha" and names[-1] == f"s{MAX_SESSIONS + 4}"


def test_a_document_from_before_names_its_session_from_source():
    assert sessions_of({"source": {"session": "old", "host": "h"}}) == [{"name": "old", "url": ""}]
    assert sessions_of({"source": {}}) == []


def test_the_api_shows_the_links_and_drops_one_it_would_not_accept(cli, doc):
    client = TestClient(mk_app(store=cli.store, authorizer=no_auth))
    assert client.get(f"/annals/api/docs/{doc}").json()["sessions"] == [{"name": "alpha", "url": A_URL}]
    path = cli.store.target.root / "docs" / doc / "meta.json"
    meta = json.loads(path.read_text())
    meta["sessions"] = [{"name": "alpha", "url": "javascript:alert(1)"}]
    path.write_text(json.dumps(meta))
    assert client.get(f"/annals/api/docs/{doc}").json()["sessions"] == [{"name": "alpha", "url": ""}]


def test_a_group_lists_its_documents_sessions(cli, doc, tmp_path):
    src = tmp_path / "o.md"
    src.write_text("# Other\n", encoding="utf-8")
    other = cli("publish", str(src), "--session", "beta", bridge="session_01BBBB")
    g = cli.store.make_group("Pair", [doc, other])
    client = TestClient(mk_app(store=cli.store, authorizer=no_auth))
    got = client.get(f"/annals/api/groups/{g['id']}").json()
    assert [i["sessions"] for i in got["items"]] == [[{"name": "alpha", "url": A_URL}], [{"name": "beta", "url": B_URL}]]
    assert got["sessions"] == [{"name": "alpha", "url": A_URL}, {"name": "beta", "url": B_URL}]


def test_a_share_carries_no_session_link(cli, doc):
    shares = Shares(cli.store, hasher=ScryptHasher(n=2**4))
    rec = shares.create(doc)
    client = TestClient(mk_share_api(shares=shares, thumbnailer=None), follow_redirects=False)
    link = f"/{rec['token']}"
    main = cli.store.meta(doc)["main"]
    routes = ("/", "/?viewer", "/share", f"/docs/{doc}", "/share.md", f"/d/{doc}", f"/d/{doc}.md",
              "/sources", f"/raw/{doc}/{main}", f"/source/{doc}/{main}", "/aggregate",
              f"/export/{doc}?format=md", f"/export/{doc}?format=html", "/combine/formats")
    for path in routes:
        r = client.get(link + path)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
        assert "claude.ai/code" not in r.text and "session_01" not in r.text, path
        assert "alpha" not in r.text, path


def test_a_room_and_a_copy_carry_no_session_link(cli, doc):
    assert "sessions" not in RoomStore(cli.store).meta(doc)
    assert "sessions" not in without_provenance(cli.store.meta(doc))


# -- the page: one row under the title, on documents and groups -------------------------


@pytest.fixture
def phone(chromium):
    ctx = chromium.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    yield ctx.new_page()
    ctx.close()


def test_the_page_links_each_session_under_the_title(cli, doc, tmp_path, serve, phone):
    src = tmp_path / "o.md"
    src.write_text("# Other\n", encoding="utf-8")
    other = cli("publish", str(src), "--session", "beta", bridge="session_01BBBB")
    g = cli.store.make_group("Pair", [doc, other])
    base = serve(cli.store)
    phone.goto(f"{base}/d/{doc}")
    row = phone.locator(".doc-head .made-by")
    row.wait_for()
    assert row.locator("a").evaluate_all("as => as.map(a => [a.textContent, a.href, a.target])") == [
        ["alpha ↗", A_URL, "_blank"]
    ]
    assert "@ " in row.inner_text()  # the host the session ran on
    # it sits right under the title, above the document, in sight on a phone
    assert row.bounding_box()["y"] < phone.locator(".doc-body").bounding_box()["y"]
    phone.goto(f"{base}/g/{g['id']}")
    links = phone.locator(".doc-head .made-by a")
    links.first.wait_for()
    assert links.evaluate_all("as => as.map(a => a.href)") == [A_URL, B_URL]


def test_many_sessions_show_the_first_and_the_latest_then_all_on_a_tap(cli, doc, tmp_path, serve, phone):
    src = tmp_path / "r2.md"
    for i in range(4):
        src.write_text(f"# Report\n\nversion {i}\n", encoding="utf-8")
        cli("publish", str(src), "--replace", doc, "--session", f"s{i}", bridge=f"session_01S{i}")
    phone.goto(f"{serve(cli.store)}/d/{doc}")
    row = phone.locator(".doc-head .made-by")
    row.wait_for()
    chips = lambda: row.locator(".session-chip").evaluate_all("cs => cs.map(c => c.textContent)")
    assert chips() == ["alpha ↗", "+2 more", "s2 ↗", "s3 ↗"]
    assert "@ " not in row.inner_text()  # the host is the latest publisher's: not said for several
    row.get_by_text("+2 more").click()
    assert chips() == ["alpha ↗", "s0 ↗", "s1 ↗", "s2 ↗", "s3 ↗"]
