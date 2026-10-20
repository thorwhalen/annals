"""The HTTP surface: page routes, JSON API, raw files, the bin, and the auth gate."""

import pytest
from fastapi.testclient import TestClient

from annals.api import mk_api, mk_app, page_html
from annals.auth import BasicAuth, CookieWhoami, no_auth
from annals.store import DocStore


@pytest.fixture
def store(tmp_path):
    s = DocStore(tmp_path / "data")
    s.publish(text="# Hello\n\nworld", title="Hello")
    return s


@pytest.fixture
def client(store):
    return TestClient(mk_app(store=store, authorizer=no_auth), follow_redirects=False)


def test_page_routes_and_assets(client):
    for path in ["/annals/", "/annals/d/x", "/annals/g/y", "/annals/trash"]:
        r = client.get(path)
        assert r.status_code == 200 and "<div id=\"app\"" in r.text
    assert client.get("/").status_code == 307 and client.get("/annals").status_code == 307
    assert client.get("/annals/api/ui/app.js").status_code == 200
    assert client.get("/annals/api/ui/marked.min.js").headers["cache-control"] == "no-cache"
    shell = client.get("/annals/").text
    assert 'api: "/annals/api"' in shell and "/annals/api/ui/app.js" in shell


def test_list_get_raw_and_bin(client, store):
    doc = client.get("/annals/api/docs").json()["docs"][0]
    assert doc["title"] == "Hello"
    full = client.get(f"/annals/api/docs/{doc['id']}").json()
    assert full["text"].startswith("# Hello") and full["in_trash"] is False
    raw = client.get(f"/annals/api/raw/{doc['id']}/{doc['main']}")
    assert raw.status_code == 200 and raw.text.startswith("# Hello")
    assert client.get(f"/annals/api/raw/{doc['id']}/nope.txt").status_code == 404
    assert client.get("/annals/api/docs?q=world").json()["docs"][0]["id"] == doc["id"]
    assert client.get("/annals/api/docs?q=zzz").json()["docs"] == []

    assert client.delete(f"/annals/api/docs/{doc['id']}").status_code == 409  # not in bin yet
    assert client.post(f"/annals/api/docs/{doc['id']}/trash").json()["in_trash"] is True
    assert client.get("/annals/api/docs").json()["docs"] == []
    assert client.get("/annals/api/docs?trash=1").json()["docs"][0]["id"] == doc["id"]
    assert client.post(f"/annals/api/docs/{doc['id']}/restore").json()["in_trash"] is False
    client.post(f"/annals/api/docs/{doc['id']}/trash")
    assert client.delete(f"/annals/api/docs/{doc['id']}").json()["ok"] is True
    assert client.get(f"/annals/api/docs/{doc['id']}").status_code == 404
    assert client.get("/annals/api/docs/../../etc").status_code in (404, 400)


def test_groups_endpoint(client, store):
    a = store.publish(text="a", title="A")
    g = store.make_group("Pair", [a["id"], "20200101-000000-gone-0000"])
    got = client.get(f"/annals/api/groups/{g['id']}").json()
    assert got["title"] == "Pair" and [m["id"] for m in got["items"]] == [a["id"]]
    assert client.get("/annals/api/groups").json()["groups"][0]["id"] == g["id"]
    assert client.get("/annals/api/groups/20200101-000000-nope-0000").status_code == 404


def test_html_doc_gets_sandbox_csp(client, store, tmp_path):
    d = tmp_path / "art"
    d.mkdir()
    (d / "index.html").write_text("<title>Art</title><script>1</script>")
    m = store.publish(d)
    r = client.get(f"/annals/api/raw/{m['id']}/index.html")
    assert r.headers["content-security-policy"].startswith("sandbox")
    assert "text" not in client.get(f"/annals/api/docs/{m['id']}").json()


def test_basic_auth_gate(store):
    c = TestClient(mk_app(store=store, authorizer=BasicAuth("me", "pw")), follow_redirects=False)
    r = c.get("/annals/api/docs")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert c.get("/annals/api/docs", auth=("me", "pw")).status_code == 200
    assert c.get("/annals/api/docs", auth=("me", "nope")).status_code == 401


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
    r = c.get("/annals/d/abc?x=1", headers={"accept": "text/html"})
    assert r.status_code == 303 and r.headers["location"].startswith("/auth/login?login_required=1&next=%2Fannals%2Fd%2Fabc")
    assert c.get("/annals/api/docs").status_code == 401
    assert c.get("/annals/api/docs", headers={"cookie": "enlace_session=bad"}).status_code == 401
    assert c.get("/annals/api/docs", headers={"cookie": "enlace_session=good"}).status_code == 200


PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000") + b"\0" * 64


def test_media_kinds_folder_and_ranges(client, store, tmp_path):
    d = tmp_path / "renders"
    (d / "sub").mkdir(parents=True)
    (d / "a.png").write_bytes(PNG)
    (d / "sub" / "b.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>")
    (d / "clip.mp4").write_bytes(bytes(range(256)) * 400)  # 102400 bytes
    (d / "notes.md").write_text("# n")
    (d / "more.md").write_text("# m")  # two pages and no index.html: a folder
    m = store.publish(d)
    assert m["kind"] == "folder" and m["title"] == "renders"
    assert m["sizes"]["clip.mp4"] == 102400 and "image" in m["excerpt"]
    full = client.get(f"/annals/api/docs/{m['id']}").json()
    assert full["file_kinds"]["clip.mp4"] == "video" and full["file_kinds"]["sub/b.svg"] == "image"
    listed = client.get("/annals/api/docs").json()["docs"]
    assert next(x for x in listed if x["id"] == m["id"])["thumb"] == "a.png"

    # a realistic 64KB range, the size a real player asks for, comes back partial and raw
    r = client.get(f"/annals/api/raw/{m['id']}/clip.mp4", headers={"range": "bytes=0-65535", "accept-encoding": "gzip"})
    assert r.status_code == 206 and r.headers["content-range"] == "bytes 0-65535/102400"
    assert len(r.content) == 65536 and "content-encoding" not in r.headers
    assert r.headers["content-type"] == "video/mp4"
    img = client.get(f"/annals/api/raw/{m['id']}/a.png")
    assert img.headers["content-type"] == "image/png" and img.headers["content-security-policy"].startswith("sandbox")
    svg = client.get(f"/annals/api/raw/{m['id']}/sub/b.svg")
    assert svg.headers["content-security-policy"].startswith("sandbox")
    assert client.get(f"/annals/api/raw/{m['id']}/notes.md").headers["content-type"].startswith("text/markdown")


def test_single_media_and_page_with_assets(store, tmp_path):
    (tmp_path / "shot.png").write_bytes(PNG)
    m = store.publish(tmp_path / "shot.png")
    assert m["kind"] == "image" and m["title"] == "shot"
    d = tmp_path / "report"
    d.mkdir()
    (d / "report.md").write_text("# Findings\n\n![a](fig.png)")
    (d / "fig.png").write_bytes(PNG)
    m2 = store.publish(d)
    assert m2["kind"] == "md" and m2["main"] == "report.md" and m2["title"] == "Findings"


def test_mk_api_mounts_at_root_with_no_gate(store):
    c = TestClient(mk_api(store=store))
    doc = c.get("/docs").json()["docs"][0]
    assert c.get(f"/raw/{doc['id']}/{doc['main']}").status_code == 200
    assert c.get("/ui/app.js").status_code == 200
    shell = page_html(base="/annals", api="/api/annals")
    assert 'base: "/annals", api: "/api/annals"' in shell and 'href="/api/annals/ui/style.css"' in shell


def test_thumbnails_are_small_cached_webp(store, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    d = tmp_path / "pics"
    d.mkdir()
    Image.new("RGB", (1200, 800), "teal").save(d / "big.png")
    (d / "v.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    m = store.publish(d)
    c = TestClient(mk_api(store=store))
    r = c.get(f"/thumb/{m['id']}/big.png?w=300")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    from io import BytesIO
    assert Image.open(BytesIO(r.content)).size[0] == 320  # snapped up to a cached width
    assert len(list((store.target.root / "cache" / "thumbs" / m["id"]).glob("*.w320.webp"))) == 1
    assert c.get(f"/thumb/{m['id']}/v.svg").headers["content-type"].startswith("image/svg")
    no_pillow = TestClient(mk_api(store=store, thumbnailer=None))
    assert no_pillow.get(f"/thumb/{m['id']}/big.png").headers["content-type"] == "image/png"
    store.trash(m["id"])
    c.delete(f"/docs/{m['id']}")
    assert not (store.target.root / "cache" / "thumbs" / m["id"]).exists()


def test_every_raw_type_but_pdf_is_sandboxed(store, tmp_path):
    d = tmp_path / "feeds"
    d.mkdir()
    for name in ("feed.rss", "a.atom", "x.xhtml", "noext", "doc.pdf"):
        (d / name).write_text("<x/>")
    m = store.publish(d)
    c = TestClient(mk_api(store=store))
    for name in ("feed.rss", "a.atom", "x.xhtml", "noext"):
        assert c.get(f"/raw/{m['id']}/{name}").headers["content-security-policy"].startswith("sandbox"), name
    assert "content-security-policy" not in c.get(f"/raw/{m['id']}/doc.pdf").headers


def test_crafted_meta_cannot_escape_the_document(store, tmp_path):
    import json

    (tmp_path / "data" / "secret.txt").write_text("root only")
    m = store.publish(text="# x", title="x")
    meta_path = store.target.root / "docs" / m["id"] / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["files"] += ["../../secret.txt", "../other/meta.json"]
    meta_path.write_text(json.dumps(meta))
    (store.target.root / "docs" / m["id"] / "link.png").symlink_to(tmp_path / "data" / "secret.txt")
    (tmp_path / "outside.txt").write_text("root only")
    (store.target.root / "docs" / m["id"] / "far.png").symlink_to(tmp_path / "outside.txt")
    meta["files"] += ["link.png", "far.png"]
    meta_path.write_text(json.dumps(meta))
    c = TestClient(mk_api(store=store))
    for rel in ("../../secret.txt", "..%2F..%2Fsecret.txt", "link.png", "far.png"):
        r = c.get(f"/raw/{m['id']}/{rel}")
        assert r.status_code == 404 and "root only" not in r.text, rel
        assert c.get(f"/thumb/{m['id']}/{rel}").status_code == 404, rel


def test_documents_from_before_media_kinds_show_inline(store, tmp_path):
    import json

    (tmp_path / "old.png").write_bytes(PNG)
    m = store.publish(tmp_path / "old.png")
    meta_path = store.target.root / "docs" / m["id"] / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["kind"] = "file"  # what the pre-media store wrote for an image
    meta.pop("sizes")
    meta_path.write_text(json.dumps(meta))
    c = TestClient(mk_api(store=store))
    assert c.get(f"/docs/{m['id']}").json()["kind"] == "image"
    assert next(d for d in c.get("/docs").json()["docs"] if d["id"] == m["id"])["kind"] == "image"


def test_refused_thumbnail_sends_a_placeholder_not_a_huge_original(store, tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    import annals.api as api_mod

    d = tmp_path / "huge"
    d.mkdir()
    Image.new("RGB", (400, 300), "navy").save(d / "photo.png")
    m = store.publish(d)
    monkeypatch.setattr(api_mod, "THUMB_MAX_PIXELS", 1000)  # "too many pixels to decode"
    c = TestClient(mk_api(store=store))
    monkeypatch.setattr(api_mod, "THUMB_FALLBACK_MAX_BYTES", 10**9)
    assert c.get(f"/thumb/{m['id']}/photo.png").headers["content-type"] == "image/png"  # small: the original
    monkeypatch.setattr(api_mod, "THUMB_FALLBACK_MAX_BYTES", 10)
    r = c.get(f"/thumb/{m['id']}/photo.png")
    assert r.headers["content-type"] == "image/svg+xml" and b"large image" in r.content


def test_symlinks_out_of_the_data_root_are_not_followed(tmp_path, store, client):
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cret-word")
    doc = client.get("/annals/api/docs").json()["docs"][0]
    main = tmp_path / "data" / "docs" / doc["id"] / doc["main"]
    main.unlink()
    main.symlink_to(secret)
    r = client.get(f"/annals/api/docs/{doc['id']}")
    assert r.status_code == 404 and "s3cret" not in r.text
    assert client.get(f"/annals/api/raw/{doc['id']}/{doc['main']}").status_code == 404
    # a symlinked meta.json drops the document from listings instead of showing it
    meta = tmp_path / "data" / "docs" / doc["id"] / "meta.json"
    meta.unlink()
    meta.symlink_to(secret)
    assert client.get("/annals/api/docs").json()["docs"] == []
    # a symlinked group file must not break the group list
    groups = tmp_path / "data" / "groups"
    groups.mkdir(exist_ok=True)
    (groups / "x.json").symlink_to(secret)
    assert client.get("/annals/api/groups").status_code == 200


def test_cookie_whoami_caches_answers_but_not_outages(monkeypatch):
    import urllib.request
    from types import SimpleNamespace

    calls, now = [], [0.0]
    mode = {"fail": True}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"email": "owner@example.com"}'

    def fake_urlopen(req, timeout):
        calls.append(1)
        if mode["fail"]:
            raise OSError("down")
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    auth = CookieWhoami("http://identity/whoami", ["owner@example.com"], cache_ttl_s=10, clock=lambda: now[0])
    req = SimpleNamespace(headers={"cookie": "s=1"})
    assert auth(req) is None and auth(req) is None and len(calls) == 2  # outage: not cached
    mode["fail"] = False
    assert auth(req) == "owner@example.com" and auth(req) == "owner@example.com" and len(calls) == 3
    now[0] = 11.0
    assert auth(req) == "owner@example.com" and len(calls) == 4  # expired


def test_cookie_whoami_cache_eviction_is_thread_safe(monkeypatch):
    import threading
    import urllib.request
    from types import SimpleNamespace

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"email": "owner@example.com"}'

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: Resp())
    auth = CookieWhoami("http://identity/whoami", ["owner@example.com"], cache_max=4)
    errors = []

    def hammer(n):
        try:
            for i in range(3000):
                auth(SimpleNamespace(headers={"cookie": f"s={n}-{i}"}))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert len(auth._cache) <= 4


def test_state_changes_refuse_cross_site_browsers(client, store):
    doc_id = store.list()[0]["id"]
    url = f"/annals/api/docs/{doc_id}/trash"
    bad = [{"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
           {"Origin": "https://evil.example"}, {"Origin": "null"}]
    for headers in bad:
        assert client.post(url, headers=headers).status_code == 403
    assert not store.meta(doc_id).get("trashed")
    ok = client.post(url, headers={"Sec-Fetch-Site": "same-origin"})
    assert ok.status_code == 200
    r = client.post(f"/annals/api/docs/{doc_id}/restore", headers={"Origin": "http://testserver"})
    assert r.status_code == 200
    assert client.post(url).status_code == 200  # non-browser client: no headers


def test_origin_matching_rules(client, store):
    doc_id = store.list()[0]["id"]
    url = f"/annals/api/docs/{doc_id}/trash"
    ok = [{"Origin": "HTTP://TestServer"},
          {"Origin": "https://a.com", "X-Forwarded-Host": "a.com, b.com"}]
    for h in ok:
        assert client.post(url, headers=h).status_code == 200
    bad = [{"Origin": "http://testserver:8080"},
           {"Origin": "http://testserver", "Sec-Fetch-Site": "cross-site"},
           {"Origin": "https://evil.com", "X-Forwarded-Host": "a.com"}]
    for h in bad:
        assert client.post(url, headers=h).status_code == 403
    evil = {"Sec-Fetch-Site": "cross-site"}
    assert client.post(f"/annals/api/docs/{doc_id}/restore", headers=evil).status_code == 403
    assert client.delete(f"/annals/api/docs/{doc_id}", headers=evil).status_code == 403
    assert client.patch(f"/annals/api/items/x", json={}, headers=evil).status_code == 403
