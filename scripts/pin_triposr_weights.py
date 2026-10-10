#!/usr/bin/env python
"""Pin TripoSR weights: resolve the Hub revision, download, SHA-256, update engines/locks/triposr.json.

Needs Hugging Face access (huggingface.co) and `pip install huggingface-hub`. It never loads the weights.

    python scripts/pin_triposr_weights.py --by "Your Name"                 # pin the CURRENT head of stabilityai/TripoSR
    python scripts/pin_triposr_weights.py --by "Your Name" --revision <40-hex>
    python scripts/pin_triposr_weights.py --dry-run                        # show what would change

Afterwards: `git diff aro_studio/engines/locks/triposr.json`, review (open the model card at the printed revision), commit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aro_studio.engines.pinning import RealHub, pin_lock  # noqa: E402
from aro_studio.engines.weights import ModelLock  # noqa: E402

LOCK = ROOT / "aro_studio" / "engines" / "locks" / "triposr.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--by", required=True, help="who is pinning (recorded in the lock)")
    ap.add_argument("--revision", default=None, help="40-hex commit; default: current head")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    lock = ModelLock.model_validate(json.loads(LOCK.read_text()))
    updated = pin_lock(lock, RealHub(os.environ.get("HF_TOKEN")), by=args.by, revision=args.revision)
    report = updated.pop("_pin_report")
    print(json.dumps(report, indent=2))
    check = ModelLock.model_validate(updated)
    print("lock complete:", check.complete(), "| still missing:", check.missing())
    if args.dry_run:
        return 0
    tmp = LOCK.with_suffix(".tmp")
    tmp.write_text(json.dumps(updated, indent=2) + "\n")
    tmp.replace(LOCK)
    print(f"wrote {LOCK.relative_to(ROOT)} - now review `git diff` and commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
