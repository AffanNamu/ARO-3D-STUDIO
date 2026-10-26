"""``python -m aro_worker --engines trellis2,triposg --port 8000`` - start the worker. Prints the token once (or use ARO_WORKER_TOKEN)."""

from __future__ import annotations

import argparse
import logging
import os
import secrets

import uvicorn

from aro_worker.app import create_app
from aro_worker.engines.base import WorkerEngine


def build_engines(names: list[str]) -> list[WorkerEngine]:
    out: list[WorkerEngine] = []
    for n in names:
        if n == "trellis2":
            from aro_worker.engines.trellis2 import Trellis2Engine

            out.append(Trellis2Engine())
        elif n == "triposg":
            from aro_worker.engines.triposg import TripoSGEngine

            out.append(TripoSGEngine())
        elif n == "hunyuan3d":
            from aro_worker.engines.hunyuan3d import Hunyuan3DEngine

            out.append(Hunyuan3DEngine())
        elif n == "fake":
            from aro_worker.engines.fake import FakeEngine

            out.append(FakeEngine())
        else:
            raise SystemExit(f"unknown engine '{n}' (trellis2, triposg, hunyuan3d, fake)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engines", default="trellis2,triposg")
    ap.add_argument("--host", default="0.0.0.0")  # noqa: S104  # nosec B104 - a GPU worker is meant to be reached; the bearer token protects it
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    token = os.environ.get("ARO_WORKER_TOKEN") or secrets.token_urlsafe(24)
    if not os.environ.get("ARO_WORKER_TOKEN"):
        print(
            f"\nARO_WORKER_TOKEN={token}\n(generated for this run: set it in the Studio as ARO_WORKER_TOKEN)\n",
            flush=True,
        )
    app = create_app(build_engines([x.strip() for x in a.engines.split(",") if x.strip()]), token)
    uvicorn.run(app, host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
