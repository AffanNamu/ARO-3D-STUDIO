#!/usr/bin/env python
"""Verify local TripoSR files against engines/locks/triposr.json WITHOUT loading them.

    python scripts/verify_triposr_weights.py [--dir /path/with/config.yaml+model.ckpt]
Exit 0 only if the lock is complete and every file matches.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aro_studio.core.errors import ModelError  # noqa: E402
from aro_studio.engines.weights import load_lock, resolve_weights  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None, help="local directory; default: download the pinned revision from the Hub")
    a = ap.parse_args()
    lock = load_lock("triposr")
    try:
        r = resolve_weights(lock, a.dir or lock.weights.repo_id)
    except ModelError as e:
        print("FAIL:", e.message, "\n  →", e.recommended_action)
        return 1
    print(
        "OK: all files match the lock:",
        r.source,
        "\n ",
        r.config,
        "\n ",
        r.checkpoint,
        *[f"\n  aux {k}: {v}" for k, v in r.aux.items()],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
