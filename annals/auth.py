"""The auth seam: who may read the annals.

A annals is private by construction, so the server asks every request who is calling. The
answer comes from one of three ``Authorizer`` callables, chosen by :func:`authorizer_from_env`
(or passed to :func:`annals.api.mk_app`):

* :func:`no_auth`: everyone is the owner. Right for ``annals serve`` bound to ``127.0.0.1``,
  wrong anywhere else.
* :class:`CookieWhoami`: forward the request's cookies to an identity endpoint that answers
  ``{"email": ...}`` (enlace_auth's ``/auth/whoami``), and allow the listed emails. This is
  how a annals sits behind an existing login without owning passwords: the login page, the
  session cookie and the logout belong to the platform; the annals only checks the allowlist.
  Env: ``ANNALS_WHOAMI_URL``, ``ANNALS_ALLOWED_USERS`` (comma separated), ``ANNALS_LOGIN_URL``.
* :class:`BasicAuth`: one username and password (HTTP Basic). For a annals with no platform
  login in front of it. Env: ``ANNALS_BASIC_USER``, ``ANNALS_BASIC_PASSWORD``.

An authorizer returns the caller's identity (a string) or ``None``. The API turns ``None``
into a 303 to the login page for a browser GET, and a 401 for anything else, mirroring
what enlace_auth does so the two are indistinguishable from the phone.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import urllib.error
import urllib.request
from typing import Callable, Optional, Protocol

ENV_WHOAMI_URL = "ANNALS_WHOAMI_URL"
ENV_ALLOWED_USERS = "ANNALS_ALLOWED_USERS"
ENV_LOGIN_URL = "ANNALS_LOGIN_URL"
ENV_BASIC_USER = "ANNALS_BASIC_USER"
ENV_BASIC_PASSWORD = "ANNALS_BASIC_PASSWORD"
DFLT_LOGIN_URL = "/auth/login"
WHOAMI_TIMEOUT_S = 3.0


class RequestLike(Protocol):
    """The two things an authorizer reads from a request."""

    @property
    def headers(self): ...  # Mapping[str, str], case-insensitive


Authorizer = Callable[[RequestLike], Optional[str]]


def no_auth(request: RequestLike) -> Optional[str]:
    """Everyone is ``owner``. Only for a server that listens on localhost."""
    return "owner"


class CookieWhoami:
    """Ask an identity endpoint who holds this request's cookies; allow listed emails."""

    def __init__(
        self,
        whoami_url: str,
        allowed_users: list[str],
        *,
        login_url: str = DFLT_LOGIN_URL,
    ):
        self.whoami_url = whoami_url
        self.allowed = {u.strip().lower() for u in allowed_users if u.strip()}
        self.login_url = login_url

    def __call__(self, request: RequestLike) -> Optional[str]:
        cookie = request.headers.get("cookie")
        if not cookie:
            return None
        req = urllib.request.Request(
            self.whoami_url, headers={"Cookie": cookie, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=WHOAMI_TIMEOUT_S) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            return None
        email = (body.get("email") or "").strip().lower()
        return email if email and email in self.allowed else None


class BasicAuth:
    """HTTP Basic with one username and password, compared in constant time."""

    login_url = None  # a 401 with WWW-Authenticate is the login page

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

    def __call__(self, request: RequestLike) -> Optional[str]:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("basic "):
            return None
        try:
            user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            return None
        ok = secrets.compare_digest(user, self.username) and secrets.compare_digest(
            pw, self.password
        )
        return user if ok else None


def authorizer_from_env(env=None) -> Authorizer:
    """Pick the authorizer the environment describes; see the module docstring."""
    env = os.environ if env is None else env
    whoami, allowed = env.get(ENV_WHOAMI_URL), env.get(ENV_ALLOWED_USERS)
    if whoami and allowed:
        return CookieWhoami(
            whoami, allowed.split(","), login_url=env.get(ENV_LOGIN_URL, DFLT_LOGIN_URL)
        )
    user, pw = env.get(ENV_BASIC_USER), env.get(ENV_BASIC_PASSWORD)
    if user and pw:
        return BasicAuth(user, pw)
    return no_auth
