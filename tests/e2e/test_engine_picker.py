"""Browser test of the engine picker on the Generation page (real Studio, labelled test-double engines)."""

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


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (160, 120), (180, 90, 40)).save(b, "PNG")
    return b.getvalue()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("e2e_picker")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "ARO_DATA_DIR": str(data), "ARO_LOG_LEVEL": "WARNING", "PYTHONPATH": str(ROOT)}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.e2e.two_engine_app:app",
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


def test_engine_picker_lists_engines_blocks_an_unavailable_one_and_sends_the_choice(server, page):
    pg = page
    pg.goto(f"{server}/#/generation")
    pg.wait_for_selector("h1:has-text('Generation')")
    picker = pg.locator("select[aria-label='Engine']")
    labels = [o.strip() for o in picker.locator("option").all_inner_texts()]
    assert labels == [
        "Plumbing test double (NOT AI)",
        "Second test double (NOT AI)",
        "Third test double (NOT AI) — not available",
    ]
    assert picker.input_value() == "plumbing_test_double"  # the first runnable engine is the default

    # an engine that cannot run says so and disables conversion
    picker.select_option("third_test_double")
    pg.wait_for_selector("text=cannot run in this environment")
    pg.locator("input[aria-label='Choose an image to convert']").set_input_files(
        {"name": "a.png", "mimeType": "image/png", "buffer": _png()}
    )
    pg.wait_for_selector("button:has-text('Convert to 3D')")
    assert pg.locator("button:has-text('Convert to 3D')").is_disabled()

    # a runnable one is sent with the conversion request
    picker.select_option("second_test_double")
    pg.wait_for_function("() => !document.body.innerText.includes('cannot run in this environment')")
    pg.locator("input[aria-label='Choose an image to convert']").set_input_files(
        {"name": "b.png", "mimeType": "image/png", "buffer": _png()}
    )
    pg.wait_for_function(
        "() => { const b=[...document.querySelectorAll('button')].find(x=>x.innerText.includes('Convert to 3D')); return b && !b.disabled; }"
    )
    with pg.expect_response(lambda r: r.url.endswith("/api/convert") and r.request.method == "POST") as info:
        pg.click("button:has-text('Convert to 3D')")
    assert info.value.status == 202, info.value.text()
    jobs = json.load(urllib.request.urlopen(f"{server}/api/jobs?limit=5"))["items"]  # noqa: S310
    assert any(j["params"].get("engine_id") == "second_test_double" for j in jobs), (
        jobs
    )  # the picker's choice reached the server
    assert not pg.errors, pg.errors
