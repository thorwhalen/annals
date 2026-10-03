"""The HTTP surface: page routes, JSON API, raw files, the bin, and the auth gate."""

import pytest
from fastapi.testclient import TestClient

from tray.api import mk_app
from tray.auth import BasicAuth, CookieWhoami, no_auth
from tray.store import DocStore


@pytest.fixture
def store(tmp_path):
    s = DocStore(tmp_path / "data")
    s.publish(text="# Hello\n\nworld", title="Hello")
    return s


@pytest.fixture
def client(store):
    return TestClient(mk_app(store=store, authorizer=no_auth), follow_redirects=False)


def test_page_routes_and_assets(client):
    for path in ["/tray/", "/tray/d/x", "/tray/g/y", "/tray/trash"]:
        r = client.get(path)
        assert r.status_code == 200 and "<div id=\"app\"" in r.text
    assert client.get("/").status_code == 307 and client.get("/tray").status_code == 307
    assert client.get("/tray/ui/app.js").status_code == 200
    assert client.get("/tray/ui/marked.min.js").status_code == 200


def test_list_get_raw_and_bin(client, store):
    doc = client.get("/tray/api/docs").json()["docs"][0]
    assert doc["title"] == "Hello"
    full = client.get(f"/tray/api/docs/{doc['id']}").json()
    assert full["text"].startswith("# Hello") and full["in_trash"] is False
    raw = client.get(f"/tray/api/raw/{doc['id']}/{doc['main']}")
    assert raw.status_code == 200 and raw.text.startswith("# Hello")
    assert client.get(f"/tray/api/raw/{doc['id']}/nope.txt").status_code == 404
    assert client.get("/tray/api/docs?q=world").json()["docs"][0]["id"] == doc["id"]
    assert client.get("/tray/api/docs?q=zzz").json()["docs"] == []

    assert client.delete(f"/tray/api/docs/{doc['id']}").status_code == 409  # not in bin yet
    assert client.post(f"/tray/api/docs/{doc['id']}/trash").json()["in_trash"] is True
    assert client.get("/tray/api/docs").json()["docs"] == []
    assert client.get("/tray/api/docs?trash=1").json()["docs"][0]["id"] == doc["id"]
    assert client.post(f"/tray/api/docs/{doc['id']}/restore").json()["in_trash"] is False
    client.post(f"/tray/api/docs/{doc['id']}/trash")
    assert client.delete(f"/tray/api/docs/{doc['id']}").json()["ok"] is True
    assert client.get(f"/tray/api/docs/{doc['id']}").status_code == 404
    assert client.get("/tray/api/docs/../../etc").status_code in (404, 400)


def test_groups_endpoint(client, store):
    a = store.publish(text="a", title="A")
    g = store.make_group("Pair", [a["id"], "20200101-000000-gone-0000"])
    got = client.get(f"/tray/api/groups/{g['id']}").json()
    assert got["title"] == "Pair" and [m["id"] for m in got["items"]] == [a["id"]]
    assert client.get("/tray/api/groups").json()["groups"][0]["id"] == g["id"]
    assert client.get("/tray/api/groups/20200101-000000-nope-0000").status_code == 404


def test_html_doc_gets_sandbox_csp(client, store, tmp_path):
    d = tmp_path / "art"
    d.mkdir()
    (d / "index.html").write_text("<title>Art</title><script>1</script>")
    m = store.publish(d)
    r = client.get(f"/tray/api/raw/{m['id']}/index.html")
    assert r.headers["content-security-policy"].startswith("sandbox")
    assert "text" not in client.get(f"/tray/api/docs/{m['id']}").json()


def test_basic_auth_gate(store):
    c = TestClient(mk_app(store=store, authorizer=BasicAuth("me", "pw")), follow_redirects=False)
    r = c.get("/tray/api/docs")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert c.get("/tray/api/docs", auth=("me", "pw")).status_code == 200
    assert c.get("/tray/api/docs", auth=("me", "nope")).status_code == 401


def test_cookie_whoami_gate(store, monkeypatch):
    auth = CookieWhoami("http://identity/whoami", ["Owner@Example.com"], login_url="/auth/login")
    answers = {"good": {"email": "owner@example.com"}, "bad": {"email": "someone@else.com"}}

    def fake_call(self, request):
        cookie = request.headers.get("cookie", "")
        body = answers.get(cookie.split("=")[-1]) if cookie else None
        email = (body or {}).get("email", "").lower()
        return email if email in self.allowed else None

    monkeypatch.setattr(CookieWhoami, "__call__", fake_call)
    c = TestClient(mk_app(store=store, authorizer=auth), follow_redirects=False)
    r = c.get("/tray/d/abc?x=1", headers={"accept": "text/html"})
    assert r.status_code == 303 and r.headers["location"].startswith("/auth/login?login_required=1&next=%2Ftray%2Fd%2Fabc")
    assert c.get("/tray/api/docs").status_code == 401
    assert c.get("/tray/api/docs", headers={"cookie": "enlace_session=bad"}).status_code == 401
    assert c.get("/tray/api/docs", headers={"cookie": "enlace_session=good"}).status_code == 200
