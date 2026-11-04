"""Fixtures shared by the browser tests: a live annals server and a Chromium.

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
    """``serve(store)`` runs the whole app over ``store`` and returns its page's base url."""
    uvicorn = pytest.importorskip("uvicorn")
    servers = []

    def _serve(store):
        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(
                mk_app(store=store, authorizer=no_auth), port=port, log_level="error"
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


@pytest.fixture(scope="module")
def chromium():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:

        def launch():
            return p.chromium.launch(
                executable_path=os.environ.get("ANNALS_TEST_BROWSER")
            )

        try:
            b = launch()
        except sync_api.Error as e:
            if not os.environ.get("CI"):
                pytest.skip(f"no browser to run: {e}")
            cmd = [
                sys.executable,
                "-m",
                "playwright",
                "install",
                "--with-deps",
                "chromium",
            ]
            subprocess.run(cmd, check=True, timeout=600)
            b = launch()
        yield b
        b.close()
