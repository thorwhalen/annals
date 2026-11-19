"""Fixtures shared by the browser tests: a live annals server, a Chromium and a WebKit.

The browser tests skip where Playwright or its Chromium is missing; ``ANNALS_TEST_BROWSER``
names a browser executable Playwright did not download. On CI (``CI`` set, as GitHub Actions
does) a missing browser is installed once instead, so these tests run there rather than
skipping: the wads workflow does not run ``[tool.wads.ci.commands] pre_test``. Chromium must
install. WebKit (with its system libraries) sometimes cannot within
:data:`OPTIONAL_INSTALL_TIMEOUT_S` on a hosted runner; its tests then skip with the
install's own output as the reason, rather than turn every run of main red.
"""

import os
import socket
import subprocess
import sys
import threading
import time

import pytest

from annals.api import mk_app
from annals.auth import no_auth


FAKE_PDF = b"%PDF-1.4 fake\n%%EOF\n"


@pytest.fixture(autouse=True)
def _fake_pdf_printer(monkeypatch):
    """Html pages are "printed" to a stub PDF in tests: no Chromium launch per publish.

    ``tests/test_pagepdf.py`` prints for real where Chromium is installed."""
    import annals.pagepdf

    monkeypatch.setattr(annals.pagepdf, "DFLT_PDF_RENDERER", lambda path: FAKE_PDF)


@pytest.fixture
def fake_pdf():
    """What the stub printer above prints."""
    return FAKE_PDF


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def serve():
    """``serve(store, **app_options)`` runs the whole app over ``store`` (``mk_app`` options,
    such as ``overviews=True``) and returns its page's base url."""
    uvicorn = pytest.importorskip("uvicorn")
    servers = []

    def _serve(store, **app_options):
        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(
                mk_app(store=store, authorizer=no_auth, **app_options),
                port=port,
                log_level="error",
            )
        )
        threading.Thread(target=server.run, daemon=True).start()
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        servers.append(server)
        return f"http://127.0.0.1:{port}/annals"

    yield _serve
    for server in servers:
        server.should_exit = True


@pytest.fixture(scope="session")
def _playwright():
    """The one Playwright of the run: two cannot run at once, so every browser comes from it."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        yield p


#: the browsers CI must have; any other engine is tried, and skipped when it cannot install
REQUIRED_ON_CI = frozenset({"chromium"})
INSTALL_TIMEOUT_S = 600
OPTIONAL_INSTALL_TIMEOUT_S = 240
_install_failed: dict[str, str] = {}  # engine -> why, so a failed install is tried once


def _install(engine: str) -> str | None:
    """Install ``engine`` with its system libraries; ``None`` when done, else why not."""
    if engine in _install_failed:
        return _install_failed[engine]
    required = engine in REQUIRED_ON_CI
    cmd = [sys.executable, "-m", "playwright", "install", "--with-deps", engine]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT_S if required else OPTIONAL_INSTALL_TIMEOUT_S,
        )
        why = None if r.returncode == 0 else f"exit {r.returncode}: {(r.stdout + r.stderr)[-1500:]}"
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"") + (e.stderr or b"")
        out = out.decode(errors="replace") if isinstance(out, bytes) else out
        why = f"timed out after {e.timeout:g}s: {out[-1500:]}"
    if why and required:
        raise RuntimeError(f"could not install {engine} on CI: {why}")
    if why:
        _install_failed[engine] = why
    return why


def _browser(p, engine, *, executable_path=None):
    """A launched Playwright browser of ``engine`` (chromium, webkit, firefox), for a fixture to
    yield. Skips where it is missing; on CI it is installed once instead (see the module doc)."""
    from playwright.sync_api import Error

    def launch():
        return getattr(p, engine).launch(executable_path=executable_path)

    try:
        b = launch()
    except Error as e:
        if not os.environ.get("CI"):
            pytest.skip(f"no {engine} to run: {e}")
        why = _install(engine)
        if why:
            pytest.skip(f"{engine} could not be installed on this runner ({why})")
        b = launch()
    yield b
    b.close()


@pytest.fixture(scope="module")
def chromium(_playwright):
    yield from _browser(_playwright, "chromium", executable_path=os.environ.get("ANNALS_TEST_BROWSER"))


@pytest.fixture(scope="module")
def webkit(_playwright):
    """Safari's engine: what every browser on an iPhone or iPad runs, where media timing differs."""
    yield from _browser(_playwright, "webkit")
