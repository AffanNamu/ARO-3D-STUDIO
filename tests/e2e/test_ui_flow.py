"""Browser end-to-end test: drives the real UI against a real server (no mocks).

Skipped automatically when Playwright or a Chromium binary is not available. Needs no GPU and no AI weights:
it uses the ARO TITAN 480 procedural reference for everything after reconstruction.
"""

from __future__ import annotations

import glob
import io
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from PIL import Image

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.e2e


def _chromium() -> str | None:
    for pat in (
        os.environ.get("ARO_CHROMIUM", ""),
        "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
        str(Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux/chrome"),
    ):
        for f in glob.glob(pat) if pat else []:
            return f
    return None


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("e2e")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "ARO_DATA_DIR": str(data), "ARO_LOG_LEVEL": "WARNING"}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
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
    exe = _chromium()
    if exe is None:
        pytest.skip("no Chromium available")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(
            executable_path=exe, args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
        )
        pg = b.new_page(viewport={"width": 1600, "height": 950})
        pg.errors = []  # type: ignore[attr-defined]
        pg.on("pageerror", lambda e: pg.errors.append(f"pageerror: {e}"))  # type: ignore[attr-defined]
        pg.on("console", lambda m: pg.errors.append(f"console.error: {m.text}") if m.type == "error" else None)  # type: ignore[attr-defined]
        pg.on("requestfailed", lambda r: pg.errors.append(f"requestfailed: {r.url}"))  # type: ignore[attr-defined]
        yield pg
        b.close()


def wait_version(pg, label: str, timeout=90_000):
    pg.wait_for_function(
        "(l) => [...document.querySelectorAll('.chip.accent')].some(c => c.textContent.startsWith(l))",
        arg=label,
        timeout=timeout,
    )
    pg.wait_for_selector("#vstats", timeout=timeout)
    time.sleep(0.4)


def open_step(pg, title: str):
    if pg.locator(f".step.open .head:has-text('{title}')").count() == 0:
        pg.click(f".step .head:has-text('{title}')")
    time.sleep(0.2)


def test_complete_pipeline_through_the_ui(page, server, tmp_path):
    pg = page
    shots = Path(os.environ.get("ARO_E2E_SHOTS", tmp_path))
    shots.mkdir(parents=True, exist_ok=True)

    # every top-level view renders without console/network errors
    for view in (
        "dashboard",
        "projects",
        "library",
        "studio",
        "generation",
        "models",
        "validation",
        "exports",
        "settings",
    ):
        pg.goto(f"{server}/#/{view}")
        pg.wait_for_selector("main h1", timeout=15_000)
        assert pg.inner_text("main h1").strip(), view

    # dashboard is honest about the engine in this environment
    pg.goto(f"{server}/#/dashboard")
    pg.wait_for_selector(".notice.warn")
    assert "cannot run in this environment" in pg.inner_text(".notice.warn")
    pg.screenshot(path=str(shots / "dashboard.png"))

    # create project + asset
    pg.goto(f"{server}/#/projects")
    pg.click("button:has-text('New project')")
    pg.fill(".modal input", "ARO TITAN 480")
    pg.click(".modal button:has-text('Create project')")
    pg.wait_for_selector("h1:has-text('ARO TITAN 480')")
    pg.click("button:has-text('New asset')")
    pg.fill(".modal input >> nth=0", "ARO TITAN 480")
    pg.click(".modal button:has-text('Create asset')")
    pg.wait_for_selector(".studio")

    # reference asset (procedural, labelled as such)
    pg.click("button:has-text('Create ARO TITAN 480 reference')")
    wait_version(pg, "v0.1")
    assert "NOT an AI reconstruction" in pg.inner_text(".right")
    assert "Procedural Reference" in pg.inner_text(".right")
    # The generic one-click preparation action must be available on a raw asset.
    open_step(pg, "Source / Inspect")
    assert pg.locator("button:has-text('Prepare mesh for use')").count() == 1
    assert "Automatic mesh preparation" in pg.inner_text(".step.open .body")
    stats = pg.inner_text("#vstats")
    assert "15,736" in stats and "3.44 × 4.00 × 6.50" in stats
    pg.screenshot(path=str(shots / "studio_reference.png"))

    # viewer controls
    for label in (
        "Front",
        "Rear",
        "Left",
        "Right",
        "Top",
        "Bottom",
        "Iso",
        "Reset",
        "Clay",
        "Normals",
        "Material",
        "Wireframe",
        "Wireframe",
        "Bounds",
        "Rig",
        "Rig",
        "Bounds",
    ):
        pg.click(f".vtoolbar button:text-is('{label}')")
    assert pg.locator("canvas.viewer").count() == 1
    pg.click(".vtoolbar button:text-is('Light')")
    pg.fill("#vlight input >> nth=0", "2.5")
    pg.click(".vtoolbar button:text-is('Light')")

    # Geometry: standard cleanup -> v0.2
    open_step(pg, "Geometry")
    pg.click("button:has-text('Inspect mesh')")
    pg.wait_for_selector("text=Self-intersections")
    pg.click("button:has-text('Run geometry processing')")
    wait_version(pg, "v0.2")

    # Vehicle: prepare rig -> v0.3 ; Collision -> v0.4 ; LOD -> v0.5
    open_step(pg, "Vehicle setup")
    pg.click("button:has-text('Prepare rig & pivots')")
    wait_version(pg, "v0.3")
    open_step(pg, "Collision")
    pg.click("button:has-text('Generate collision')")
    wait_version(pg, "v0.4")
    open_step(pg, "LOD")
    pg.click("button:has-text('Generate LODs')")
    wait_version(pg, "v0.5")
    assert pg.locator("#lodbtns button").count() == 4
    pg.click("#lodbtns button:text-is('LOD3')")
    assert "LOD3" in pg.inner_text("#vstats")
    pg.click(".vtoolbar button:text-is('Collision')")
    pg.click(".vtoolbar button:text-is('Rig')")
    pg.click("#lodbtns button:text-is('LOD0')")
    pg.screenshot(path=str(shots / "studio_lod_collision_rig.png"))

    # Validate -> PRODUCTION_READY, then designate
    open_step(pg, "Validate")
    pg.click("button:has-text('Run validation on this version')")
    pg.wait_for_selector(".step.open .chip.ok:text-is('PRODUCTION READY')", timeout=90_000)
    pg.click("button:has-text('Mark as current production version')")
    pg.wait_for_selector("text=★ production")
    assert re.search(r"No geometry issues|production", pg.inner_text(".left"))

    # Export GLB + Unity package, download through the API
    open_step(pg, "Version & Export")
    pg.check("text=Unity 6 package >> input")
    pg.click(".step.open .body button.primary:has-text('Export')")
    pg.wait_for_selector(".right button:has-text('Exports (2)')", timeout=120_000)
    pg.click(".right .tabs button:has-text('Exports')")
    pg.wait_for_selector("text=integrity checks passed")
    assert pg.locator(".right .card:has-text('COMPLETED')").count() == 2
    pg.screenshot(path=str(shots / "studio_exports.png"))

    # validation + exports pages show the results
    pg.goto(f"{server}/#/validation")
    pg.wait_for_selector("td >> text=ARO TITAN 480")
    pg.click("a:has-text('Open')")
    pg.wait_for_selector(".big-status")
    assert "PRODUCTION READY" in pg.inner_text(".big-status")
    pg.screenshot(path=str(shots / "validation_report.png"))
    pg.goto(f"{server}/#/exports")
    pg.wait_for_selector("td >> text=UNITY")
    assert "Khronos" in pg.inner_text("main")
    pg.goto(f"{server}/#/library")
    pg.wait_for_selector(".asset-card")
    assert "PRODUCTION_READY" in pg.inner_text(".asset-card").replace(" ", "_")

    # models page states licence status and blocked models
    pg.goto(f"{server}/#/models")
    pg.wait_for_selector("text=Blocked models")
    body = pg.inner_text("main")
    assert "nvidia-lyra-2.0" in body and "claimed" in body

    # Batch workflow: upload multiple object images, configure each asset independently.
    # This CPU-only test intentionally confirms generation remains disabled without a runnable AI engine.
    pg.goto(f"{server}/#/generation")
    pg.wait_for_selector("h1:has-text('Generation')")
    pg.select_option("select[aria-label='Project']", label="ARO TITAN 480")
    image = Image.new("RGB", (96, 96), (190, 190, 190))
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")
    data = image_bytes.getvalue()
    pg.locator("input[aria-label='Choose multiple images']").set_input_files([
        {"name": "first-object.png", "mimeType": "image/png", "buffer": data},
        {"name": "second-building.png", "mimeType": "image/png", "buffer": data},
    ])
    pg.wait_for_selector("input[aria-label='Asset name for first-object.png']")
    pg.wait_for_selector("input[aria-label='Asset name for second-building.png']")
    pg.fill("input[aria-label='Asset name for first-object.png']", "First Prop")
    pg.select_option("select[aria-label='Category for first-object.png']", "prop")
    pg.fill("input[aria-label='Asset name for second-building.png']", "Small Building")
    pg.select_option("select[aria-label='Category for second-building.png']", "building")
    assert pg.locator("input[aria-label='Asset name for first-object.png']").input_value() == "First Prop"
    assert pg.locator("select[aria-label='Category for first-object.png']").input_value() == "prop"
    assert pg.locator("input[aria-label='Asset name for second-building.png']").input_value() == "Small Building"
    assert pg.locator("select[aria-label='Category for second-building.png']").input_value() == "building"
    assert pg.locator("button:has-text('Generate selected images')").is_disabled()
    assert "cannot run in this environment" in pg.inner_text(".notice.warn")
    pg.screenshot(path=str(shots / "generation_batch.png"))

    real = [e for e in pg.errors if "GPU stall" not in e and "GL Driver" not in e]  # type: ignore[attr-defined]
    assert not real, real
