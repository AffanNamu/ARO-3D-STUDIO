"""Load ``ARO_*`` settings from a private file, so secrets never travel through chat, shell history or the repository.

    ARO_DATABASE_URL=postgresql://...        # one KEY=VALUE per line; # starts a comment only at the beginning of a line
    export ARO_R2_BUCKET="my-bucket"         # an `export ` prefix and one pair of matching quotes are accepted

Only names that start with ``ARO_`` are read (a file cannot set PATH, proxy or loader variables). Values already in the environment win.
Nothing is expanded or executed. Keep the file OUTSIDE the repository (for example ``~/aro-secrets/aro.env``) and readable by you only.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def parse_env_text(text: str) -> tuple[dict[str, str], list[str]]:
    """Return (values, ignored names)."""
    values: dict[str, str] = {}
    ignored: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name, val = m.group(1), m.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        if not name.startswith("ARO_"):
            ignored.append(name)
            continue
        values[name] = val
    return values, ignored


def load_env_file(path: str | os.PathLike[str] | None, *, environ: dict[str, str] | None = None) -> list[str]:
    """Apply a file to the environment (existing variables win). Returns the NAMES that were set. Never prints a value."""
    if not path:
        return []
    env = os.environ if environ is None else environ
    p = Path(path).expanduser()
    if not p.is_file():
        raise SystemExit(f"The env file {p} does not exist.")
    try:
        mode = p.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO) and os.name == "posix":
            print(f"warning: {p} is readable by other users; run: chmod 600 {p}", file=sys.stderr)
    except OSError:
        pass
    values, ignored = parse_env_text(p.read_text(encoding="utf-8"))
    if ignored:
        print("note: ignored non-ARO_ names in the env file: " + ", ".join(sorted(set(ignored))), file=sys.stderr)
    set_names = []
    for k, v in values.items():
        if k not in env and v != "":
            env[k] = v
            set_names.append(k)
    return set_names
