#!/usr/bin/env python
"""Score a generated model against its reference image and write an inspection sheet.

    python scripts/score_model.py --model prepared.glb --reference truck.png --category heavy_truck --out out/ --label triposr-truck

Writes ``<label>-fidelity.json`` and ``<label>-sheet.png`` (reference | outline overlay | best-matching view | five standard views).
The model must be in the Studio's canonical frame (+Y up, +Z forward): use the PREPARED glb, not a raw engine mesh.
Not a pass/fail gate: it measures reference fidelity (silhouette, proportions) so engines can be compared on the same image.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--reference", required=True, type=Path)
    ap.add_argument("--category", default="other")
    ap.add_argument("--label", default="model")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    from aro_studio.quality import fidelity as fd
    from aro_studio.quality.report import load_lod0, make_sheet

    a.out.mkdir(parents=True, exist_ok=True)
    mesh = load_lod0(a.model)
    ref_img = Image.open(a.reference).convert("RGB")
    rep = fd.score_model(mesh, ref_img, a.category)
    d = rep.to_dict()
    d.update(model=a.model.name, reference=a.reference.name, label=a.label, category=a.category)
    (a.out / f"{a.label}-fidelity.json").write_text(json.dumps(d, indent=2) + "\n")
    make_sheet(mesh, ref_img, rep, a.out / f"{a.label}-sheet.png")
    p = rep.proportions
    print(
        f"{a.label}: silhouette IoU {rep.silhouette_iou:.3f} | aspect error {rep.aspect_error:.3f} | "
        f"W/L {p['ratios']['width_over_length']:.2f} H/L {p['ratios']['height_over_length']:.2f} ({p['verdict']}) | "
        f"{rep.mesh['triangles']} tris, texture/uv={rep.mesh['has_uv']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
