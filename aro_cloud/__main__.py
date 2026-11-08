"""``python -m aro_cloud`` starts the API (uvicorn). Cloud Run sets PORT."""

from __future__ import annotations

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("ARO_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    uvicorn.run(
        "aro_cloud.wiring:create",
        factory=True,
        host=os.environ.get("HOST", "0.0.0.0"),  # noqa: S104  # nosec B104 - a container must listen on all interfaces
        port=int(os.environ.get("PORT", "8080")),
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "*"),
    )


if __name__ == "__main__":
    main()
