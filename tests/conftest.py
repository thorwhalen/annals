"""Fixtures shared by the browser tests: a live annals server, a Chromium and a WebKit.

The browser tests skip where Playwright or its Chromium is missing; ``ANNALS_TEST_BROWSER``
names a browser executable Playwright did not download. On CI (``CI`` set, as GitHub Actions
does) a missing Chromium is installed once instead, so these tests run there rather than
skipping: the wads workflow does not run ``[tool.wads.ci.commands] pre_test``.
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


def _browser(p, engine, *, executable_path=None):
    """A launched Playwright browser of ``engine`` (chromium, webkit, firefox), for a fixture to
    yield. Skips where it is missing; on CI it is installed once instead."""
    from playwright.sync_api import Error

    def launch():
        return getattr(p, engine).launch(executable_path=executable_path)

    try:
        b = launch()
    except Error as e:
        if not os.environ.get("CI"):
            pytest.skip(f"no {engine} to run: {e}")
        cmd = [sys.executable, "-m", "playwright", "install", "--with-deps", engine]
        subprocess.run(cmd, check=True, timeout=600)
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
