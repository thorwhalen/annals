"""Spoken overviews offered to some readers only (``mk_api(overviews=<readers>)``).

The reader offered them sees the Listen button and the documents overviews made; every
other reader is served the same API over the documents minus those, with overviews off.
Readers are named by a gateway's header here (:class:`annals.auth.TrustedHeader`), the way
a forward-auth proxy names them.
"""

import stat
import sys

import pytest
from fastapi.testclient import TestClient

from annals import overview
from annals.api import mk_api, mk_app, serve
from annals.auth import TrustedHeader, authorizer_from_env
from annals.overview import Requests
from annals.store import DocStore, HidingStore

OWNER, OTHER = "owner@example.test", "someone@example.test"
HEADER = "X-Test-User"


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


@pytest.fixture
def docs(store, tmp_path):
    """A plain document, the overview made of it, and a group holding both."""
    plain = store.publish(text="# Hello\n\nThe parser landed.", title="Hello")["id"]
    requests = Requests(store.target.root)
    overview.request(store, requests, plain, minutes=3)
    script = tmp_path / "maker.py"
    script.write_text(
        "import sys\nsource, minutes, out = sys.argv[1:4]\n"
        "open(out, 'w').write('<!doctype html><title>P</title>' + open(source).read())\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    command = [sys.executable, str(script), "{source}", "{minutes}", "{out}"]
    assert overview.work(store, requests, command=command)[0]["state"] == "done"
    made = requests.get(plain)["overview"]
    group = store.make_group("Both", [plain, made])["id"]
    return {"plain": plain, "made": made, "group": group}


def _client(store, who, overviews=frozenset({OWNER})):
    app = mk_app(store=store, authorizer=TrustedHeader(HEADER), overviews=overviews)
    headers = {HEADER: who} if who else {}
    return TestClient(app, headers=headers)


def _ids(rows):
    return {r["id"] for r in rows}


def test_the_reader_offered_overviews_sees_them(store, docs):
    c = _client(store, OWNER.upper())  # names compare without case
    assert {docs["plain"], docs["made"]} <= _ids(c.get("/annals/api/docs").json()["docs"])
    page = c.get(f"/annals/api/docs/{docs['plain']}").json()
    assert page["listen"]["state"] == "done" and page["listen"]["overview"] == docs["made"]
    assert c.get(f"/annals/api/docs/{docs['made']}").status_code == 200
    assert docs["made"] in _ids(c.get("/annals/api/audio").json()["docs"])
    r = c.post(f"/annals/api/docs/{docs['plain']}/overview", json={"minutes": 5, "force": True})
    assert r.status_code == 200 and r.json()["state"] == "queued"


def test_another_reader_has_no_listen_and_cannot_ask(store, docs):
    c = _client(store, OTHER)
    page = c.get(f"/annals/api/docs/{docs['plain']}").json()
    assert "listen" not in page
    assert c.get(f"/annals/api/docs/{docs['plain']}/overview").status_code == 404
    r = c.post(f"/annals/api/docs/{docs['plain']}/overview", json={"minutes": 5})
    assert r.status_code == 404
    r = c.post("/annals/api/overviews", json={"docs": [docs["plain"]]})
    assert r.status_code == 404
    assert "listen" not in c.get(f"/annals/api/groups/{docs['group']}").json()
    assert Requests(store.target.root).get(docs["plain"])["minutes"] == 3  # nothing queued


def test_another_reader_never_sees_what_overviews_made(store, docs):
    c = _client(store, OTHER)
    api, made = "/annals/api", docs["made"]
    assert _ids(c.get(f"{api}/docs").json()["docs"]) == {docs["plain"]}
    assert _ids(c.get(f"{api}/docs", params={"q": "Listen"}).json()["docs"]) == set()
    assert made not in _ids(c.get(f"{api}/audio").json()["docs"])
    assert all(made not in r["key"] for r in c.get(f"{api}/items").json()["data"])
    assert c.get(f"{api}/items/published:{made}").status_code == 404
    group = c.get(f"{api}/groups/{docs['group']}").json()
    assert _ids(group["items"]) == {docs["plain"]} and made not in group["docs"]
    listed = {g["id"]: g for g in c.get(f"{api}/groups").json()["groups"]}
    assert listed[docs["group"]]["docs"] == [docs["plain"]]
    page = c.get(f"{api}/docs/{docs['plain']}").json()
    assert page["groups"][0]["n"] == 1
    meta = store.meta(made)
    for path in (
        f"/docs/{made}",
        f"/raw/{made}/{meta['main']}",
        f"/export/{made}",
        f"/listening/{made}",
        f"/docs/{made}/shareable",
    ):
        assert c.get(api + path).status_code == 404, path
    assert c.get(f"{api}/aggregate", params={"doc": made}).status_code == 404
    r = c.post(f"{api}/shares", json={"ref": made})
    assert r.status_code == 404
    r = c.post(f"{api}/shares", json={"ref": docs["group"]})  # the group, without it
    assert r.status_code == 200 and list(r.json()["docs"]) == [docs["plain"]]
    assert c.post(f"{api}/docs/{made}/trash").status_code == 404
    assert not store.meta(made)["in_trash"]


def test_offered_to_everyone_is_unchanged(store, docs):
    c = _client(store, OTHER, overviews=True)
    assert c.get(f"/annals/api/docs/{docs['plain']}").json()["listen"]["state"] == "done"
    assert docs["made"] in _ids(c.get("/annals/api/docs").json()["docs"])


def test_off_hides_nothing_and_offers_nothing(store, docs):
    c = _client(store, OTHER, overviews=False)
    assert "listen" not in c.get(f"/annals/api/docs/{docs['plain']}").json()
    assert docs["made"] in _ids(c.get("/annals/api/docs").json()["docs"])


def test_the_readers_come_from_the_environment(store, docs, monkeypatch):
    monkeypatch.setenv(overview.ENV_OVERVIEWS, f"{OWNER}, boss@example.test")
    app = mk_app(store=store, authorizer=TrustedHeader(HEADER))
    owner = TestClient(app, headers={HEADER: OWNER})
    other = TestClient(app, headers={HEADER: OTHER})
    assert "listen" in owner.get(f"/annals/api/docs/{docs['plain']}").json()
    assert "listen" not in other.get(f"/annals/api/docs/{docs['plain']}").json()
    monkeypatch.delenv(overview.ENV_OVERVIEWS)
    app = mk_app(store=store, authorizer=TrustedHeader(HEADER))
    owner = TestClient(app, headers={HEADER: OWNER})
    assert "listen" not in owner.get(f"/annals/api/docs/{docs['plain']}").json()


def test_a_predicate_names_the_readers(store, docs):
    api = mk_api(store=store, overviews=lambda who: who.endswith("@example.test"),
                 reader=lambda request: request.headers.get(HEADER, "owner"))  # fmt: skip
    yes = TestClient(api, headers={HEADER: OTHER})
    no = TestClient(api, headers={HEADER: "x@elsewhere.test"})
    assert "listen" in yes.get(f"/docs/{docs['plain']}").json()
    assert "listen" not in no.get(f"/docs/{docs['plain']}").json()


def test_a_request_without_the_header_is_refused_without_a_password_prompt(store, docs):
    r = _client(store, None).get("/annals/api/docs")
    assert r.status_code == 401 and "www-authenticate" not in r.headers


@pytest.mark.parametrize("bad", [42, object()])
def test_overviews_refuses_what_it_cannot_read(store, bad):
    with pytest.raises(TypeError):
        mk_api(store=store, overviews=bad)


# -- the header authorizer ----------------------------------------------------------


class _Req:
    def __init__(self, **headers):
        self.headers = {k.lower(): v for k, v in headers.items()}


def test_trusted_header_names_the_reader():
    auth = TrustedHeader("X-Iq-User")
    assert auth(_Req(**{"x-iq-user": " Thor@Example.test "})) == "thor@example.test"
    assert auth(_Req()) is None and auth(_Req(**{"x-iq-user": "  "})) is None


def test_trusted_header_can_narrow_who_reads():
    auth = TrustedHeader("X-Iq-User", allowed_users=["a@x.test"])
    assert auth(_Req(**{"x-iq-user": "a@x.test"})) == "a@x.test"
    assert auth(_Req(**{"x-iq-user": "b@x.test"})) is None


def test_the_environment_picks_the_header_authorizer():
    auth = authorizer_from_env({"ANNALS_USER_HEADER": "X-Iq-User"})
    assert isinstance(auth, TrustedHeader) and auth.allowed is None
    auth = authorizer_from_env(
        {"ANNALS_USER_HEADER": "X-Iq-User", "ANNALS_ALLOWED_USERS": "a@x.test"}
    )
    assert auth.allowed == {"a@x.test"}


def test_serve_refuses_a_header_anyone_could_send(monkeypatch):
    monkeypatch.setenv("ANNALS_USER_HEADER", "X-Iq-User")
    with pytest.raises(ValueError, match="header"):
        serve(host="0.0.0.0")


# -- the store view -----------------------------------------------------------------


def test_hiding_never_deletes_from_a_group(store, docs):
    view = HidingStore(store, hide=overview.made_here)
    extra = store.publish(text="# More", title="More")["id"]
    assert view.add_to_group(docs["group"], [extra])["docs"] == [docs["plain"], extra]
    assert store.group(docs["group"])["docs"] == [docs["plain"], docs["made"], extra]
    with pytest.raises(KeyError):
        view.meta(docs["made"])
    with pytest.raises(KeyError):
        view.read_text(docs["made"])


def test_the_text_combined_for_an_overview_is_made_here_too():
    combined = {"tags": [overview.COMBINED_TAG], "source": {"session": overview.COMBINED_SESSION}}
    assert overview.made_here(combined)
    assert not overview.made_here({"tags": [overview.COMBINED_TAG], "source": {"session": "x"}})
    assert not overview.made_here({"tags": ["report"]})


# -- found by review: shares, pending replacements, failing predicates ---------------


def test_another_reader_never_sees_or_revokes_a_share_reaching_what_overviews_made(store, docs):
    owner, other = _client(store, OWNER), _client(store, OTHER)
    api = "/annals/api"
    of_made = owner.post(f"{api}/shares", json={"ref": docs["made"]}).json()["token"]
    of_group = owner.post(f"{api}/shares", json={"ref": docs["group"]}).json()["token"]
    of_plain = owner.post(f"{api}/shares", json={"ref": docs["plain"]}).json()["token"]
    seen = {r["token"] for r in other.get(f"{api}/shares", params={"all": 1}).json()["shares"]}
    assert seen == {of_plain}
    for token in (of_made, of_group):
        assert other.get(f"{api}/shares/{token}/sources").status_code == 404
        assert other.delete(f"{api}/shares/{token}").status_code == 404
    assert {r["token"] for r in owner.get(f"{api}/shares").json()["shares"]} == {
        of_made, of_group, of_plain
    }  # still live: the owner's to revoke


def test_a_pending_replacement_of_a_hidden_document_is_hidden_too(tmp_path):
    store = DocStore(tmp_path / "data", settle=False)  # keep the replacement pending
    made = store.publish(text="# Listen", title="Listen: x", tags=[overview.TAG])["id"]
    pending = store.publish(text="# Listen again", title="Listen: x", replace=made)["id"]
    view = HidingStore(store, hide=overview.made_here)
    assert view.hides(made) and view.hides(pending)
    assert view.list() == []
    with pytest.raises(KeyError):
        view.meta(pending)


def test_a_failing_predicate_serves_the_reader_as_not_offered(store, docs):
    def broken(who):
        raise RuntimeError("no directory today")

    c = TestClient(mk_app(store=store, authorizer=TrustedHeader(HEADER), overviews=broken),
                   headers={HEADER: OWNER})  # fmt: skip
    r = c.get(f"/annals/api/docs/{docs['plain']}")
    assert r.status_code == 200 and "listen" not in r.json()


@pytest.mark.parametrize("value, offered", [("true", True), ("1", True), ("no", False)])
def test_an_on_off_word_is_never_a_reader_name(store, docs, monkeypatch, value, offered):
    monkeypatch.setenv(overview.ENV_OVERVIEWS, value)
    c = TestClient(mk_app(store=store, authorizer=TrustedHeader(HEADER)), headers={HEADER: OTHER})
    assert ("listen" in c.get(f"/annals/api/docs/{docs['plain']}").json()) is offered
