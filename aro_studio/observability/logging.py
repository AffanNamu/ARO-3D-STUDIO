"""Structured logging with secret redaction (spec §36, §52)."""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys
import time
from pathlib import Path

_REDACT = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._\-~+/=]+"),
    re.compile(r"(?i)\b(hf_[A-Za-z0-9]{20,})\b"),
    re.compile(r"(?i)((?:token|secret|password|api[_-]?key)\s*[:=]\s*)['\"]?[^\s'\",]+"),
]


def redact(text: str) -> str:
    out = text
    out = _REDACT[0].sub(r"\1***", out)
    out = _REDACT[1].sub("hf_***", out)
    out = _REDACT[2].sub(r"\1***", out)
    return out


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for k in ("job_id", "project_id", "asset_id", "generation_id", "stage"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=True)


_configured = False


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    global _configured
    root = logging.getLogger("aro_studio")
    root.setLevel(level.upper())
    if _configured:
        return
    fmt = RedactingJsonFormatter()
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        for name, lvl in (("app.log", logging.INFO), ("error.log", logging.ERROR)):
            fh = logging.handlers.RotatingFileHandler(
                log_dir / name, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
            )
            fh.setLevel(lvl)
            fh.setFormatter(fmt)
            root.addHandler(fh)
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"aro_studio.{name}")
