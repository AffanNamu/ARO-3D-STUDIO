"""Shared browser launch for the e2e tests.

A missing browser is a SKIP on a developer machine but a FAILURE when ``ARO_E2E_REQUIRED=1`` (set in CI), so the browser gate
can never report green while having run nothing.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import pytest

LAUNCH_ARGS = ["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def chromium_path() -> str | None:
    for pat in (
        os.environ.get("ARO_CHROMIUM", ""),
        "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
        str(Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux*/chrome"),
    ):
        for f in glob.glob(pat) if pat else []:
            return f
    return None


def launch(p):
    """Launch Chromium: an explicitly found binary first, otherwise the browser `playwright install` provides."""
    exe = chromium_path()
    try:
        return p.chromium.launch(executable_path=exe, args=LAUNCH_ARGS) if exe else p.chromium.launch(args=LAUNCH_ARGS)
    except Exception as e:  # noqa: BLE001
        msg = f"no usable Chromium for the browser tests: {type(e).__name__}: {str(e)[:200]}"
        if os.environ.get("ARO_E2E_REQUIRED") == "1":
            pytest.fail(msg)
        pytest.skip(msg)
