"""Share links: scope isolation, expiry, the password gate, revocation, filtered references."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from annals.api import mk_app
from annals.auth import BasicAuth
from annals.share import (
    REMOVED_ID,
    ScryptHasher,
    Shares,
    filter_refs,
    is_expired,
    parse_expires,
    references,
)
from annals.share_api import SlidingWindowLimiter, mk_share_api
from annals.store import DocStore

T0 = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


@pytest.fixture
def report(store, tmp_path):
    """A report with two images, a private note beside them, and links out."""
    src = tmp_path / "report"
    (src / "img").mkdir(parents=True)
    (src / "img" / "a.png").write_bytes(b"\x89PNG a")
    (src / "img" / "b.png").write_bytes(b"\x89PNG b")
    (src / "private.txt").write_text("secret notes")
    other = store.publish(text="# Other\n\nprivate page", title="Other")
    (src / "report.md").write_text(
        "# Report\n\n![a](img/a.png)\n\n![b](img/b.png)\n\n"
        "[notes](private.txt) and [web](https://example.org)\n\n"
        f"see [other](/annals/d/{other['id']}) or {other['id']}\n"
    )
    meta = store.publish(src, title="Report")
    return meta, other


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def shares(store, clock):
    # a cheap scrypt keeps the suite fast; the format and the checks are the same
    return Shares(store, hasher=ScryptHasher(n=2**4), clock=clock)


@pytest.fixture
def client(shares):
    app = mk_share_api(shares=shares, thumbnailer=None)
    return TestClient(app, follow_redirects=False)


def _link(rec):
    return f"/{rec['token']}"


# -- the core -------------------------------------------------------------------------


def test_parse_expires_and_is_expired():
    assert parse_expires(None) is None and parse_expires("") is None
    assert parse_expires("7d", now=T0) == (T0 + timedelta(days=7)).isoformat()
    assert parse_expires("2026-10-30", now=T0) == "2026-10-30T23:59:59+00:00"
    assert parse_expires("2026-10-23T10:00:00Z", now=T0) == "2026-10-23T10:00:00+00:00"
    with pytest.raises(ValueError):
        parse_expires("2020-01-01", now=T0)
    with pytest.raises(ValueError):
        parse_expires("next tuesday", now=T0)
    assert is_expired({"expires": "garbage"})  # fail closed
    assert not is_expired({"expires": None})


def test_hasher_roundtrip_and_never_stores_plaintext(shares, report):
    meta, _ = report
    rec = shares.create(meta["id"], password="hunter22")
    stored = shares.record(rec["token"])
    assert stored["password"].startswith("scrypt$") and "hunter22" not in str(stored)
    assert "password" not in rec and rec["protected"] is True
    assert shares.check_password(stored, "hunter22")
    assert not shares.check_password(stored, "hunter23")
    assert len(rec["token"]) >= 22


def test_a_record_written_before_caplinks_still_opens(shares, store, report):
    """Records on disk predate the move to caplinks; they need no migration."""
    meta, _ = report
    token = "Legacy0Record0Token0aa"
    legacy = {
        "token": token,
        "title": "Report",
        "created": T0.isoformat(),
        "root": {"kind": "doc", "id": meta["id"]},
        "docs": {meta["id"]: meta["files"]},
        "expires": (T0 + timedelta(days=7)).isoformat(),
        "password": ScryptHasher(n=2**4).hash("hunter22"),
        "revoked": None,
    }
    store.target.write_text(f"shares/{token}.json", json.dumps(legacy, indent=1))
    state, rec = shares.status(token)
    assert state == "ok" and rec["docs"] == legacy["docs"]
    assert shares.check_password(rec, "hunter22")
    assert [r["token"] for r in shares.list()] == [token]
    store.target.write_text(f"shares/{token}.json", json.dumps({**legacy, "docs": []}))
    assert shares.status(token) == ("missing", None)  # no scope: grants nothing


def test_scope_defaults_and_include(shares, report):
    meta, other = report
    everything = shares.create(meta["id"])
    assert set(everything["docs"][meta["id"]]) == set(meta["files"])
    some = shares.create(meta["id"], include=["img/a.png"])
    assert some["docs"] == {meta["id"]: ["img/a.png", "report.md"]}
    linked = shares.create(meta["id"], include=["img/a.png", other["id"]])
    assert set(linked["docs"]) == {meta["id"], other["id"]}
    with pytest.raises(ValueError):
        shares.create(meta["id"], include=["../../etc/passwd"])
    with pytest.raises(ValueError):
        shares.create(meta["id"], exclude=["report.md"])  # the page itself


def test_resources_lists_files_and_linked_pages(shares, report):
    meta, other = report
    res = shares.resources(meta["id"])
    by = {f["rel"]: f for f in res["files"]}
    assert by["img/a.png"]["referenced"] and by["private.txt"]["referenced"]
    assert by["report.md"]["main"]
    assert [p["id"] for p in res["pages"]] == [other["id"]]


def test_filter_refs_removes_what_is_not_shared():
    shared = {"20261001-000000-ok-aaaa": "/t/d/20261001-000000-ok-aaaa"}.get
    text = (
        "![in](img/a.png) ![out](img/b.png) [kept words](private.txt) "
        "[web](https://example.org) <img src=\"img/b.png\"> "
        "[ok](https://h/annals/d/20261001-000000-ok-aaaa) "
        "[no](/annals/d/20261002-000000-no-bbbb) 20261002-000000-no-bbbb "
        "https://h/annals/g/20261003-000000-grp-cccc"
    )
    out = filter_refs(text, "md", files={"img/a.png"}, shared=shared)
    assert "![in](img/a.png)" in out and "img/b.png" not in out
    assert "private.txt" not in out and "kept words" in out
    assert "https://example.org" in out
    assert "/t/d/20261001-000000-ok-aaaa" in out
    assert "bbbb" not in out and "cccc" not in out and REMOVED_ID in out


def test_references_finds_html_attrs():
    refs = references('<img src="a.png"><a href="../x">', "html", from_dir="sub/")
    assert refs["files"] == ["sub/a.png", "x"]


# -- the public server ----------------------------------------------------------------


def test_page_and_scope_isolation(client, shares, report, store):
    meta, other = report
    rec = shares.create(meta["id"], include=["img/a.png"])
    link = _link(rec)
    assert client.get(link).status_code == 307
    page = client.get(link + "/")
    assert page.status_code == 200 and "window.ANNALS" in page.text
    assert page.headers["x-robots-tag"].startswith("noindex")
    assert page.headers["referrer-policy"] == "no-referrer"
    assert "script-src 'self' 'nonce-" in page.headers["content-security-policy"]

    doc = client.get(f"{link}/docs/{meta['id']}").json()
    assert doc["files"] == ["img/a.png", "report.md"]
    assert "source" not in doc and "tags" not in doc  # no host, cwd, or owner's tags
    assert "img/b.png" not in doc["text"] and "private.txt" not in doc["text"]
    assert other["id"] not in doc["text"]

    assert client.get(f"{link}/raw/{meta['id']}/img/a.png").status_code == 200
    # an unchosen file of the same document, another document, a traversal: all 404
    assert client.get(f"{link}/raw/{meta['id']}/img/b.png").status_code == 404
    assert client.get(f"{link}/raw/{meta['id']}/private.txt").status_code == 404
    assert client.get(f"{link}/docs/{other['id']}").status_code == 404
    assert client.get(f"{link}/raw/{other['id']}/document.md").status_code == 404
    assert client.get(f"{link}/raw/{meta['id']}/../{other['id']}/document.md").status_code == 404
    raw_md = client.get(f"{link}/raw/{meta['id']}/report.md").text
    assert "img/b.png" not in raw_md and "private.txt" not in raw_md
    info = client.get(f"{link}/share").json()
    assert [d["id"] for d in info["docs"]] == [meta["id"]]
    # a guessed token, and a malformed one
    assert client.get("/" + "A" * 22 + "/share").status_code == 404
    assert client.get("/..%2F/share").status_code == 404


def test_ui_assets_are_an_allowlist(client):
    assert client.get("/ui/app.js").status_code == 200
    assert client.get("/ui/style.css").status_code == 200
    assert client.get("/ui/index.html").status_code == 404
    assert client.get("/ui/vendor/zodal-store-http.min.js").status_code == 404


def test_expiry_is_enforced_per_request(client, shares, report, clock):
    meta, _ = report
    rec = shares.create(meta["id"], expires="1h")
    link = _link(rec)
    assert client.get(f"{link}/share").status_code == 200
    clock.t = T0 + timedelta(hours=2)
    assert client.get(f"{link}/share").status_code == 410
    assert client.get(f"{link}/raw/{meta['id']}/report.md").status_code == 410
    assert client.get(f"{link}/").status_code == 410
    assert rec["token"] not in [r["token"] for r in shares.list()]
    assert rec["token"] in [r["token"] for r in shares.list(all=True)]


def test_password_gate(client, shares, report):
    meta, _ = report
    rec = shares.create(meta["id"], password="open sesame")
    link = _link(rec)
    form = client.get(f"{link}/")
    assert form.status_code == 401 and 'name="password"' in form.text
    assert client.get(f"{link}/share").status_code == 401
    assert client.get(f"{link}/raw/{meta['id']}/report.md").status_code == 401
    # missing, then wrong
    assert client.post(f"{link}/unlock", content=b"").status_code == 401
    wrong = client.post(
        f"{link}/unlock",
        content=b"password=nope",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert wrong.status_code == 401 and "not right" in wrong.text
    ok = client.post(
        f"{link}/unlock",
        content=b"password=open+sesame&next=/elsewhere",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert ok.status_code == 303 and ok.headers["location"] == f"{link}/"
    cookie = ok.headers["set-cookie"]
    assert "HttpOnly" in cookie and f"Path={link}" in cookie
    assert client.get(f"{link}/share").status_code == 200
    assert client.get(f"{link}/raw/{meta['id']}/img/a.png").status_code == 200
    # a cookie made for one link does not open another
    other = shares.create(meta["id"], password="open sesame")
    stranger = TestClient(client.app)
    stranger.cookies.set("annals_share", client.cookies.get("annals_share"))
    assert stranger.get(f"/{other['token']}/share").status_code == 401
    assert stranger.get(f"{link}/share").status_code == 200  # the cookie is real


def test_password_attempts_are_limited(shares, report):
    meta, _ = report
    app = mk_share_api(
        shares=shares,
        thumbnailer=None,
        rate_limiter=SlidingWindowLimiter(max_per_window=3),
    )
    client = TestClient(app, follow_redirects=False)
    rec = shares.create(meta["id"], password="right-one")
    hdr = {"content-type": "application/x-www-form-urlencoded"}
    codes = [
        client.post(f"/{rec['token']}/unlock", content=b"password=x", headers=hdr).status_code
        for _ in range(4)
    ]
    assert codes == [401, 401, 401, 429]


def test_revoked_link_is_gone(client, shares, report):
    meta, _ = report
    rec = shares.create(meta["id"])
    link = _link(rec)
    assert client.get(f"{link}/share").status_code == 200
    shares.revoke(rec["token"])
    assert client.get(f"{link}/share").status_code == 404
    assert client.get(f"{link}/raw/{meta['id']}/report.md").status_code == 404
    assert client.get(f"{link}/").status_code == 404


def test_trashed_document_is_not_served(client, shares, report, store):
    meta, _ = report
    rec = shares.create(meta["id"])
    store.trash(meta["id"])
    assert client.get(f"{_link(rec)}/docs/{meta['id']}").status_code == 404


def test_group_share(client, shares, store):
    a = store.publish(text="# A", title="A")
    b = store.publish(text="# B", title="B")
    g = store.make_group("Pair", [a["id"], b["id"]])
    rec = shares.create(g["id"], include=[a["id"]])
    assert rec["root"] == {"kind": "group", "id": g["id"]} and list(rec["docs"]) == [a["id"]]
    info = client.get(f"{_link(rec)}/share").json()
    assert [d["id"] for d in info["docs"]] == [a["id"]]
    assert client.get(f"{_link(rec)}/docs/{b['id']}").status_code == 404


# -- the owner's side, through the standalone app -------------------------------------


def test_owner_api_and_gate(store, report):
    meta, _ = report
    app = mk_app(store=store, authorizer=BasicAuth("me", "pw"))
    anon = TestClient(app, follow_redirects=False)
    owner = TestClient(
        app, follow_redirects=False, headers={"Authorization": "Basic bWU6cHc="}
    )
    assert anon.post("/annals/api/shares", json={"ref": meta["id"]}).status_code == 401
    res = owner.get(f"/annals/api/docs/{meta['id']}/shareable").json()
    assert {f["rel"] for f in res["files"]} == set(meta["files"])
    made = owner.post(
        "/annals/api/shares",
        json={"ref": meta["id"], "include": ["img/a.png"], "expires": "7d", "password": "pw-for-x"},
    )
    assert made.status_code == 200
    rec = made.json()
    assert rec["url"] == f"/annals/shared/{rec['token']}/" and "password" not in rec
    # the recipient needs no login, only the link (and here its password)
    assert anon.get(rec["url"]).status_code == 401
    assert anon.get(rec["url"] + "share").status_code == 401
    unlocked = anon.post(
        rec["url"] + "unlock",
        content=b"password=pw-for-x",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert unlocked.status_code == 303
    assert anon.get(rec["url"] + f"raw/{meta['id']}/img/a.png").status_code == 200
    assert anon.get(rec["url"] + f"raw/{meta['id']}/img/b.png").status_code == 404
    # nothing else of the annals opens with that cookie
    assert anon.get("/annals/api/docs").status_code == 401
    assert anon.get("/annals/shared/../api/docs").status_code in (401, 404)
    listed = owner.get("/annals/api/shares").json()["shares"]
    assert [s["token"] for s in listed] == [rec["token"]]
    assert owner.delete(f"/annals/api/shares/{rec['token']}").json()["revoked"]
    assert anon.get(rec["url"] + "share").status_code == 404
    assert owner.post("/annals/api/shares", json={"ref": meta["id"], "expires": "1999-01-01"}).status_code == 422
    assert owner.post("/annals/api/shares", json={"ref": "nope"}).status_code == 404


# -- what the adversarial review found ------------------------------------------------


def test_defaults_expire_and_passwords_have_a_floor(shares, report):
    meta, _ = report
    rec = shares.create(meta["id"])
    assert rec["expires"] == (T0 + timedelta(days=7)).isoformat()
    assert shares.create(meta["id"], expires="never")["expires"] is None
    with pytest.raises(ValueError):
        shares.create(meta["id"], password="short")


def test_plain_text_and_svg_are_filtered_too(client, shares, store, tmp_path):
    private = store.publish(text="# P", title="Private thing")
    src = tmp_path / "t"
    src.mkdir()
    (src / "notes.txt").write_text(f"see https://h/annals/d/{private['id']} and secret.png")
    (src / "pic.svg").write_text(f'<svg><image href="/annals/raw/{private["id"]}/x.png"/></svg>')
    meta = store.publish(src, title="Notes")
    rec = shares.create(meta["id"])
    link = _link(rec)
    for rel in ("notes.txt", "pic.svg"):
        body = client.get(f"{link}/raw/{meta['id']}/{rel}").text
        assert private["id"] not in body and "private-thing" not in body


def test_owner_host_links_are_removed(client, shares, store):
    meta = store.publish(
        text="[ledger](http://testserver/annals/s/ledgers/taxes.md) [web](https://example.org)",
        title="Links",
    )
    rec = shares.create(meta["id"])
    text = client.get(f"{_link(rec)}/docs/{meta['id']}").json()["text"]
    assert "taxes" not in text and "https://example.org" in text


def test_a_big_page_is_refused_not_sent_unfiltered(client, shares, report, monkeypatch):
    import annals.share_api as sa

    meta, other = report
    rec = shares.create(meta["id"])
    monkeypatch.setattr(sa, "MAX_SHARED_PAGE_BYTES", 10)
    r = client.get(f"{_link(rec)}/raw/{meta['id']}/report.md")
    assert r.status_code == 413 and other["id"] not in r.text


def test_a_linked_page_brings_only_what_it_shows(shares, store, tmp_path):
    src = tmp_path / "linked"
    src.mkdir()
    (src / "page.md").write_text("# L\n\n![](shown.png)")
    (src / "shown.png").write_bytes(b"s")
    (src / "unshown.png").write_bytes(b"u")
    linked = store.publish(src, title="Linked")
    root = store.publish(text=f"[l](/annals/d/{linked['id']})", title="Root")
    rec = shares.create(root["id"], include=[linked["id"]])
    assert sorted(rec["docs"][linked["id"]]) == ["page.md", "shown.png"]


def test_one_guesser_does_not_lock_out_the_recipient(shares, report):
    meta, _ = report
    app = mk_share_api(
        shares=shares,
        thumbnailer=None,
        rate_limiter=SlidingWindowLimiter(max_per_window=3),
        trusted_proxies=("testclient",),  # the test client plays the reverse proxy
    )
    rec = shares.create(meta["id"], password="right-one")
    client = TestClient(app, follow_redirects=False)

    def attempt(pw, ip):
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "x-forwarded-for": ip,
        }
        body = f"password={pw}".encode()
        return client.post(f"/{rec['token']}/unlock", content=body, headers=headers)

    assert [attempt("x", "6.6.6.6").status_code for _ in range(4)] == [401, 401, 401, 429]
    assert attempt("right-one", "1.2.3.4").status_code == 303


def test_wrong_passwords_from_everywhere_lock_the_link_for_a_while(shares, report):
    meta, _ = report
    app = mk_share_api(
        shares=shares,
        thumbnailer=None,
        link_failure_limiter=SlidingWindowLimiter(max_per_window=2),
        trusted_proxies=("testclient",),
    )
    rec = shares.create(meta["id"], password="right-one")
    hdr = {"content-type": "application/x-www-form-urlencoded"}
    c = TestClient(app, follow_redirects=False)
    for i in range(3):
        c.post(f"/{rec['token']}/unlock", content=b"password=x", headers={**hdr, "x-forwarded-for": f"9.9.9.{i}"})
    r = c.post(f"/{rec['token']}/unlock", content=b"password=right-one", headers={**hdr, "x-forwarded-for": "1.1.1.1"})
    assert r.status_code == 429


def test_a_share_record_without_its_scope_is_a_missing_link(shares, report):
    meta, _ = report
    token = shares.create(meta["id"])["token"]
    assert shares.links.status(token)[0] == "ok"
    texts = shares.links.store.texts
    texts[f"{token}.json"] = json.dumps({"token": token, "created": "2026-01-01"})
    assert shares.links.status(token)[0] == "missing"
