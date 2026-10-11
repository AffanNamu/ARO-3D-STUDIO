"""Browser test of the batch image-to-3D screen against the real Studio with a test-double engine."""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from PIL import Image

pw = pytest.importorskip("playwright.sync_api")
from tests.e2e.browser import launch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.e2e


def _png(w=160, h=120, color=(180, 90, 40)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def _gif() -> bytes:
    b = io.BytesIO()
    Image.new("P", (160, 120)).save(b, "GIF")
    return b.getvalue()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("e2e_batch")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "ARO_DATA_DIR": str(data), "ARO_LOG_LEVEL": "WARNING", "PYTHONPATH": str(ROOT)}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.e2e.double_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("server did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def page(server):
    with pw.sync_playwright() as p:
        b = launch(p)
        pg = b.new_page(viewport={"width": 1400, "height": 1000})
        pg.errors = []  # type: ignore[attr-defined]
        pg.on("pageerror", lambda e: pg.errors.append(f"pageerror: {e}"))  # type: ignore[attr-defined]
        pg.on("console", lambda m: pg.errors.append(f"console.error: {m.text}") if m.type == "error" else None)  # type: ignore[attr-defined]
        yield pg
        b.close()


def test_batch_screen_preview_edit_partial_failure_and_open_asset(server, page):
    pg = page
    shots = Path(os.environ.get("ARO_E2E_SHOTS", "")) if os.environ.get("ARO_E2E_SHOTS") else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        server + "/api/projects",
        data=json.dumps({"name": "Batch UI"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req)  # noqa: S310

    pg.goto(f"{server}/#/generation")
    pg.wait_for_selector("h1:has-text('Generation')")
    pg.select_option("select[aria-label='Project']", label="Batch UI")
    assert "Batch is not multi-view" in pg.inner_text("#batch-panel")
    assert pg.locator("button:has-text('Generate selected images')").is_disabled()
    assert "Add at least one image" in pg.inner_text(".batch-reason")

    pg.locator("input[aria-label='Choose multiple images']").set_input_files(
        [
            {"name": "kettle.png", "mimeType": "image/png", "buffer": _png()},
            {
                "name": "bad-content.png",
                "mimeType": "image/png",
                "buffer": _gif(),
            },  # decodes in a browser, rejected by the server
            {"name": "chair.png", "mimeType": "image/png", "buffer": _png(color=(40, 90, 180))},
            {"name": "tiny.png", "mimeType": "image/png", "buffer": _png(16, 16)},  # rejected before upload
            {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hello"},  # rejected before upload
        ]
    )
    pg.wait_for_selector("input[aria-label='Asset name for chair.png']")
    pg.wait_for_function(
        "() => document.querySelectorAll('.batch-item').length === 5 && !document.body.innerText.includes('Checking…')"
    )
    # preview thumbnails for every readable image; per-image validation messages for the unusable ones
    assert pg.locator(".batch-thumb img").count() == 4
    tiny = pg.locator(".batch-item", has_text="tiny.png")
    assert "Cannot use" in tiny.inner_text() and "shorter side must be at least" in tiny.inner_text()
    assert "not a PNG, JPG or WebP" in pg.locator(".batch-item", has_text="notes.txt").inner_text()
    assert pg.locator("input[aria-label='Asset name for tiny.png']").is_disabled()

    # independent names and categories, removal before submission
    pg.fill("input[aria-label='Asset name for kettle.png']", "Steel Kettle")
    pg.select_option("select[aria-label='Category for kettle.png']", "household_object")
    pg.fill("input[aria-label='Asset name for chair.png']", "Wooden Chair")
    pg.select_option("select[aria-label='Category for chair.png']", "furniture")
    pg.click("button[aria-label='Remove notes.txt']")
    assert pg.locator(".batch-item").count() == 4
    assert pg.locator("button:has-text('Generate selected images (3)')").is_enabled()
    if shots:
        pg.screenshot(path=str(shots / "batch_ready.png"), full_page=True)

    pg.click("button:has-text('Generate selected images')")
    # valid siblings finish even though one item fails at the server; each item shows its own outcome
    pg.wait_for_function(
        "() => [...document.querySelectorAll('.batch-item')].filter(c => c.dataset.status === 'COMPLETED').length === 2",
        timeout=60_000,
    )
    bad = pg.locator(".batch-item", has_text="bad-content.png")
    bad.locator("[role=alert]").wait_for()
    assert "Failed" in bad.inner_text() and "not a PNG, JPEG or WebP" in bad.inner_text()
    assert "Edit and retry" in bad.inner_text()
    done = pg.locator(".batch-item", has_text="kettle.png")
    assert "Done" in done.inner_text() and done.locator("a:has-text('Open asset')").count() == 1
    assert "Steel Kettle" in urllib.request.urlopen(server + "/api/assets").read().decode()  # noqa: S310
    if shots:
        pg.screenshot(path=str(shots / "batch_done.png"), full_page=True)

    # the finished asset opens in the Studio
    done.locator("a:has-text('Open asset')").click()
    pg.wait_for_selector(".big-status, #vstats, h1", timeout=30_000)
    assert "/studio/" in pg.url

    real = [e for e in pg.errors if "GPU stall" not in e and "GL Driver" not in e]  # type: ignore[attr-defined]
    assert not real, real
