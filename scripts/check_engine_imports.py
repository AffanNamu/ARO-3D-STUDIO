"""Will an engine's source import cleanly in the environment we are about to run it in? Answered WITHOUT running the engine's code.

The engine files are only PARSED (``ast``); then every third-party ``from X import Y`` they contain is resolved by importing X from the
environment this script runs in (which executes only installed, pinned packages) and looking for Y. A name that does not resolve is
reported before anyone spends GPU time on it. Names of the engine's own package and the standard library are skipped.

    <env-python> -I scripts/check_engine_imports.py <checkout-root> triposg/pipelines/pipeline_triposg.py triposg/inference_utils.py ...

Used to validate the pinned environment of ``scripts/lab_bootstrap.py`` (see docs/verification/lab-environment-rehearsal.md).
A missing ``diso`` is expected for TripoSG: aro_worker/shims/diso_shim.py replaces it.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
files = [root / f for f in sys.argv[2:]]
local_tops = {"triposg", "scripts", "image_process", "briarmbg", "hy3dgen"}  # the engines' own packages
stdlib = set(sys.stdlib_module_names)
need: dict[tuple[str, str | None], list[str]] = {}
for f in files:
    tree = ast.parse(f.read_text(), filename=str(f))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top = node.module.split(".")[0]
            if top in local_tops or top in stdlib or top == "__future__":
                continue
            for a in node.names:
                need.setdefault((node.module, a.name), []).append(f.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                if top in local_tops or top in stdlib:
                    continue
                need.setdefault((a.name, None), []).append(f.name)

bad = 0
for (mod, name), where in sorted(need.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
    try:
        m = importlib.import_module(mod)
        if name and name != "*" and not hasattr(m, name):
            try:
                importlib.import_module(f"{mod}.{name}")
            except Exception:  # noqa: BLE001
                raise AttributeError(f"{mod} has no attribute {name}") from None
        status = "ok"
    except Exception as e:  # noqa: BLE001
        status = f"MISSING: {type(e).__name__}: {str(e)[:110]}"
        bad += 1
    print(f"{status:12s} from {mod} import {name or ''}   <- {', '.join(sorted(set(where)))}")
print("unresolved:", bad)
