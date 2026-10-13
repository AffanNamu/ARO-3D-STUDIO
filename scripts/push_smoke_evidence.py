#!/usr/bin/env python
"""Push the repo-safe smoke evidence from a Colab (or any) checkout to a SEPARATE evidence branch.

    python scripts/push_smoke_evidence.py --repo /content/aro [--branch evidence/smoke-20261013-1200] [--token-env GITHUB_TOKEN]

Why: lets the session that owns the repository fetch the results with `git fetch` instead of passing zip files around.
Safety rules, all enforced here:
  * never pushes to the working/default branch: it refuses `claude/*`, `main`, `master`, or the branch currently checked out;
  * stages ONLY `docs/acceptance/evidence/ai/smoke/` (raw meshes are .gitignored; files > 8 MB are refused) - nothing else;
  * the token is read from an environment variable (in Colab: Secrets -> `GITHUB_TOKEN`, fine-grained PAT limited to this
    repository with Contents: read/write), is sent as an HTTP header, and is never printed, logged or written into the URL;
  * it refuses evidence that is not from the real engine unless --allow-double is given (test-double output is not evidence).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

EVIDENCE = "docs/acceptance/evidence/ai/smoke"
MAX_FILE = 8_000_000
PROTECTED = ("main", "master")


def git(repo: Path, *args: str, extra: list[str] | None = None, check: bool = True) -> str:
    r = subprocess.run(["git", *(extra or []), *args], cwd=repo, capture_output=True, text=True, check=False)  # noqa: S603, S607
    if check and r.returncode != 0:
        # never echo the command line (it may carry the auth header): only git's own message, with the token scrubbed
        msg = (r.stderr or r.stdout).strip()
        tok = os.environ.get("_ARO_TOKEN_SCRUB")
        raise SystemExit(f"git {args[0]} failed: {msg.replace(tok, '***') if tok else msg}")
    return r.stdout.strip()


def validate(repo: Path, branch: str, allow_double: bool) -> dict:
    ev_dir = repo / EVIDENCE
    f = ev_dir / "smoke-evidence.json"
    if not f.is_file():
        raise SystemExit(f"no {EVIDENCE}/smoke-evidence.json in {repo}: run scripts/real_inference_smoke.py first")
    ev = json.loads(f.read_text())
    if ev.get("mode") != "real_engine" and not allow_double:
        raise SystemExit("refusing: evidence is not from the real engine (a test double is not inference evidence)")
    current = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch in PROTECTED or branch.startswith("claude/") or branch == current:
        raise SystemExit(f"refusing to push to '{branch}': use a separate evidence branch (e.g. evidence/smoke-<date>)")
    big = [
        str(p.relative_to(repo))
        for p in ev_dir.rglob("*")
        if p.is_file() and "/raw/" not in p.as_posix() and p.stat().st_size > MAX_FILE
    ]
    if big:
        raise SystemExit(f"refusing: files larger than 8 MB would be committed: {big}")
    return ev


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="checkout containing docs/acceptance/evidence/ai/smoke")
    ap.add_argument("--branch", default=time.strftime("evidence/smoke-%Y%m%d-%H%M%S", time.gmtime()))
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--token-env", default="GITHUB_TOKEN")
    ap.add_argument("--allow-double", action="store_true")
    a = ap.parse_args()
    repo = Path(a.repo)
    ev = validate(repo, a.branch, a.allow_double)

    token = os.environ.get(a.token_env, "")
    extra: list[str] = []
    if token:
        os.environ["_ARO_TOKEN_SCRUB"] = token
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        extra = ["-c", f"http.extraheader=AUTHORIZATION: basic {basic}"]
    else:
        raise SystemExit(f"{a.token_env} is not set (Colab: Secrets panel -> add GITHUB_TOKEN, grant notebook access)")

    git(repo, "checkout", "-q", "-B", a.branch)
    git(repo, "add", "--", EVIDENCE, f":(exclude){EVIDENCE}/raw")  # raw meshes never travel, whatever .gitignore says
    if not git(repo, "status", "--porcelain", "--", EVIDENCE):
        raise SystemExit("nothing new to commit under " + EVIDENCE)
    staged = git(repo, "diff", "--cached", "--name-only").splitlines()
    outside = [p for p in staged if not p.startswith(EVIDENCE + "/") or p.startswith(EVIDENCE + "/raw/")]
    if outside:
        git(repo, "reset", "-q")
        raise SystemExit(f"refusing: staged files outside the evidence folder: {outside}")
    msg = f"evidence: real-inference smoke run ({ev.get('status', {}).get('real_inference')}, studio {str(ev.get('studio_commit'))[:12]})"
    git(
        repo,
        "-c",
        "user.name=ARO Colab evidence",
        "-c",
        "user.email=noreply@example.invalid",
        "commit",
        "-q",
        "-m",
        msg,
    )
    git(repo, "push", a.remote, f"HEAD:refs/heads/{a.branch}", extra=extra)
    print(
        f"pushed {len(staged)} file(s) to branch {a.branch}; tell the repository session to `git fetch origin {a.branch}`"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
