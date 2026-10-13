"""BasicAuth: constant-time comparison must not crash on any credentials a client can send."""

import base64
from types import SimpleNamespace

from annals.auth import BasicAuth


def _req(user_pw: bytes):
    token = base64.b64encode(user_pw).decode()
    return SimpleNamespace(headers={"authorization": f"Basic {token}"})


def test_basic_auth_accepts_and_rejects():
    auth = BasicAuth("me", "pw")
    assert auth(_req(b"me:pw")) == "me"
    assert auth(_req(b"me:nope")) is None
    assert auth(SimpleNamespace(headers={})) is None
    assert auth(SimpleNamespace(headers={"authorization": "Bearer x"})) is None


def test_basic_auth_non_ascii_credentials_are_rejected_not_a_crash():
    auth = BasicAuth("me", "pw")
    assert auth(_req("é:x".encode())) is None
    assert auth(_req("me:pé".encode())) is None


def test_basic_auth_non_ascii_secret_still_matches():
    assert BasicAuth("josé", "päss")(_req("josé:päss".encode())) == "josé"


def test_basic_auth_garbage_header_is_rejected():
    assert BasicAuth("me", "pw")(SimpleNamespace(headers={"authorization": "Basic !!!"})) is None


def test_basic_auth_unencodable_config_fails_at_startup():
    import pytest

    with pytest.raises(UnicodeEncodeError):
        BasicAuth("me", "bad\udcff")
