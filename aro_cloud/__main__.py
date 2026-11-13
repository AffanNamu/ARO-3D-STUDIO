"""``python -m aro_cloud [--env-file FILE] [--host H] [--port P]`` starts the API (uvicorn). Cloud Run sets PORT.

On your own computer, ``--env-file`` reads the ARO_* settings from your private file and the API listens on 127.0.0.1 only.
In a container (no flags), it listens on all interfaces, as a container must.
"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn

from aro_cloud.envfile import load_env_file


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="private file with ARO_* settings (see aro_cloud/envfile.py)")
    ap.add_argument("--host", default=None, help="default: 127.0.0.1 with --env-file, else 0.0.0.0 (containers)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    a = ap.parse_args(argv)
    load_env_file(a.env_file)
    host = a.host or os.environ.get("HOST") or ("127.0.0.1" if a.env_file else "0.0.0.0")  # noqa: S104  # nosec B104 - a container must listen on all interfaces
    logging.basicConfig(
        level=os.environ.get("ARO_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    uvicorn.run(
        "aro_cloud.wiring:create",
        factory=True,
        host=host,
        port=a.port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "*"),
    )


if __name__ == "__main__":
    main()
