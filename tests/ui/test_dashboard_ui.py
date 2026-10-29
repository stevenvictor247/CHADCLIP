"""Opens the real dashboard in a real browser (Playwright) and checks what you'd see: tabs, icons, the chart, the ambient layer.

Skipped when Playwright isn't installed (the normal test job); the "ui" job in .github/workflows/tests.yml runs it.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def hq_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "HQ_DATA_DIR": tempfile.mkdtemp(prefix="hq-ui-"), "HQ_PASSWORD": "", "SCOUT_WEB_SEARCH": "0",
           "ANTHROPIC_API_KEY": "", "HQ_PAUSED": "true"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "hq.api:app", "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("HQ didn't start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        exe = os.environ.get("HQ_UI_CHROMIUM") or None   # point at an already-installed Chromium instead of Playwright's own
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        yield b
        b.close()


@pytest.fixture
def page(browser, hq_url):
    pg = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(hq_url + "/")
    pg.wait_for_selector("#hq-tabs")
    pg.errors = errors
    yield pg
    pg.close()


def test_tabs_use_lucide_icons_and_switch(page):
    assert page.locator("#hq-tabs svg.lucide").count() >= 11
    page.click('#hq-tabs [data-go="boss"]')
    assert page.evaluate("document.body.dataset.tab") == "boss"
    page.click('#hq-tabs [data-go="home"]')
    assert page.evaluate("document.body.dataset.tab") == "home"
    assert not page.errors


def test_money_chart_opens(page):
    page.click('#hq-money [data-panel="chart"]')
    page.wait_for_selector("#m-chart .uplot canvas", timeout=10000)
    assert page.locator("#m-chart .u-legend").count() == 1
    page.click('#hq-money [data-panel="chart"]')   # toggles shut
    assert page.locator("#hq-money-panel.open").count() == 0
    assert not page.errors


def test_money_numbers_still_read_right(page):
    assert page.inner_text("#m-spent").startswith("$")
    assert page.inner_text("#m-net").lstrip("−").startswith("$")


def test_ambient_layer_draws_over_the_villages(page):
    page.wait_for_selector("#hq-fx canvas", timeout=10000)   # PixiJS fireflies; WebGL works in headless Chromium via SwiftShader
    assert page.locator("#worldcanvas").count() == 1          # the villages themselves are untouched
    assert not page.errors
