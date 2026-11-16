"""Links in a framed html document reach their site: a new tab, never the sandboxed frame."""

import re
from importlib.resources import files

from fastapi.testclient import TestClient

from annals.api import RAW_SANDBOX_FLAGS, links_open_apart, mk_app
from annals.auth import no_auth
from annals.store import DocStore


def test_links_to_other_sites_open_apart():
    page = (
        '<a href="https://claude.ai/code?prompt=x">go</a>\n'
        '<A HREF="//example.org/a" class=x>proto-relative</A>'
        '<a href="https://k.org" target="_self">kept</a>'
        '<a href="page2.html">sibling</a> <a href="#top">anchor</a>'
        '<area href="http://map.org" alt=m>'
        "<script>var s = '<a href=\"https://not.a.tag\">';</script>"
    ).encode()
    out = links_open_apart(page).decode()
    assert '<a target="_blank" href="https://claude.ai/code?prompt=x">' in out
    assert '<A target="_blank" HREF="//example.org/a"' in out
    assert '<area target="_blank" href="http://map.org"' in out
    assert 'target="_self">kept' in out and out.count('target="_blank"') == 3
    assert '<a href="page2.html">' in out and '<a href="#top">' in out
    assert "<script>var s = '<a href=\"https://not.a.tag\">';</script>" in out  # not a tag


def test_link_rewrite_leaves_alone_what_it_should():
    based = b'<base target="_top"><a href="https://x.org">x</a>'
    assert links_open_apart(based) == based
    latin = 'caf\xe9 <a href="https://x.org">x</a>'.encode("latin-1")
    out = links_open_apart(latin)
    assert out.startswith(b"caf\xe9 ") and b'target="_blank"' in out
    assert links_open_apart(latin, max_bytes=10) == latin


def test_framed_document_serves_escaping_sandbox_and_rewritten_links(tmp_path):
    store = DocStore(tmp_path / "data")
    page = tmp_path / "links.html"
    page.write_text('<title>L</title><a href="https://claude.ai/code?prompt=x">go</a>')
    m = store.publish(page)
    c = TestClient(mk_app(store=store, authorizer=no_auth))
    r = c.get(f"/annals/api/raw/{m['id']}/links.html")
    csp = r.headers["content-security-policy"]
    assert "allow-popups-to-escape-sandbox" in csp and "allow-same-origin" not in csp
    assert 'target="_blank" href="https://claude.ai' in r.text
    # what a browser already holds is not revalidated to the old body and headers
    assert r.headers["etag"].endswith('-2"')
    # the same document shared: same policy, same links
    made = c.post("/annals/api/shares", json={"ref": m["id"]}).json()
    shared = TestClient(c.app).get(f"{made['url']}raw/{m['id']}/links.html")
    assert "allow-popups-to-escape-sandbox" in shared.headers["content-security-policy"]
    assert 'target="_blank" href="https://claude.ai' in shared.text


def test_page_frame_uses_the_server_sandbox_flags():
    js = (files("annals") / "data" / "ui" / "app.js").read_text()
    flags = re.search(r'var FRAME_SANDBOX = "([^"]+)"', js).group(1).split()
    assert flags == list(RAW_SANDBOX_FLAGS)
    assert 'sandbox: "allow' not in js  # every frame takes the one list
