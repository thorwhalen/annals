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


def _run_install(args: list[str], timeout: float) -> str | None:
    """Run ``playwright <args>``; ``None`` when it worked, else why not (its output's tail)."""
    cmd = [sys.executable, "-m", "playwright", *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"") + (e.stderr or b"")
        out = out.decode(errors="replace") if isinstance(out, bytes) else out
        return f"{' '.join(args)} timed out after {e.timeout:g}s: {out[-1500:]}"
    if r.returncode:
        return f"{' '.join(args)} exit {r.returncode}: {(r.stdout + r.stderr)[-1500:]}"
    return None


def _launch_installed(p, engine: str, launch):
    """Install ``engine`` on CI and launch it; skip (an optional engine) or fail (a required one).

    The browser comes from Playwright's own download, which is reliable; its system libraries
    come from apt, whose mirrors a hosted runner sometimes cannot reach, and which the runner
    image mostly has already. So the browser alone first, and apt only when it will not start.
    """
    from playwright.sync_api import Error

    required = engine in REQUIRED_ON_CI
    timeout = INSTALL_TIMEOUT_S if required else OPTIONAL_INSTALL_TIMEOUT_S
    why = _install_failed.get(engine)
    if why is None:
        why = _run_install(["install", engine], timeout)
    if why is None:
        try:
            return launch()
        except Error:
            why = _run_install(["install-deps", engine], timeout)
    if why is None:
        try:
            return launch()
        except Error as e:
            why = f"installed, but it will not start: {e}"
    _install_failed[engine] = why
    if required:
        raise RuntimeError(f"could not install {engine} on CI: {why}")
    pytest.skip(f"{engine} could not be installed on this runner ({why})")


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
        b = _launch_installed(p, engine, launch)
    yield b
    b.close()


@pytest.fixture(scope="module")
def chromium(_playwright):
    yield from _browser(_playwright, "chromium", executable_path=os.environ.get("ANNALS_TEST_BROWSER"))


@pytest.fixture(scope="module")
def webkit(_playwright):
    """Safari's engine: what every browser on an iPhone or iPad runs, where media timing differs."""
    yield from _browser(_playwright, "webkit")
