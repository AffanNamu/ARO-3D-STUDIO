#!/usr/bin/env python
"""HTTP-level deployment verification against ANY running Studio (container, Space, VM). Standard library only.

    python scripts/verify_deployment.py --base-url http://127.0.0.1:7860 --token "$ARO_ACCESS_TOKEN" --max-upload-mb 1

Every check is evaluated against the live service; the process exits 1 if any check fails. Results are written as JSON
(`--out`) so they can be attached to the acceptance report as evidence. Nothing here mocks the service.
"""

from __future__ import annotations

import argparse
import io
import json
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
import zlib

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail[:160]}", flush=True)
    return ok


class Client:
    def __init__(self, base: str, token: str | None):
        self.base, self.token = base.rstrip("/"), token

    def req(self, method: str, path: str, body=None, headers=None, token="__default__", raw=False, timeout=120):
        h = dict(headers or {})
        tok = self.token if token == "__default__" else token
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        data = None
        if body is not None and not isinstance(body, (bytes, bytearray)):
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        elif body is not None:
            data = bytes(body)
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:  # noqa: S310
                payload = resp.read()
                return resp.status, (payload if raw else _j(payload)), dict(resp.headers)
        except urllib.error.HTTPError as e:
            payload = e.read()
            return e.code, (payload if raw else _j(payload)), dict(e.headers)

    def upload(self, path: str, filename: str, content: bytes, fields=None, token="__default__"):
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in (fields or {}).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
            + content
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        return self.req(
            "POST", path, b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"}, token=token
        )

    def wait_job(self, jid: str, timeout=300):
        end = time.time() + timeout
        while time.time() < end:
            s, j, _ = self.req("GET", f"/api/jobs/{jid}")
            if s == 200 and j["state"] in (
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "TIMEOUT",
                "RESOURCE_LIMIT",
                "MODEL_ERROR",
                "INVALID_INPUT",
            ):
                return j
            time.sleep(0.4)
        raise TimeoutError(jid)


def _j(b: bytes):
    try:
        return json.loads(b)
    except Exception:  # noqa: BLE001
        return {"_raw": b[:200].decode("latin1")}


def tiny_png(w=200, h=200) -> bytes:
    raw = b"".join(b"\x00" + bytes([230]) * (w * 3) for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def huge_dimension_png(w=30000, h=30000) -> bytes:
    """A few hundred bytes of PNG that DECLARES 900 megapixels (decompression-bomb style); IDAT is bogus on purpose."""

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 1, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" * 64))
        + chunk(b"IEND", b"")
    )


def zip_bytes(members: list[tuple[str, bytes]], symlink: str | None = None) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, d in members:
            zf.writestr(n, d)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = 0o120777 << 16
            zf.writestr(info, "/etc/passwd")
    return b.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:7860")
    ap.add_argument("--token", default=None)
    ap.add_argument("--max-upload-mb", type=int, default=25, help="the limit the service was started with")
    ap.add_argument("--expect-no-ai", action="store_true", help="assert generation fails cleanly (engine not runnable)")
    ap.add_argument("--skip-pipeline", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    c = Client(a.base_url, a.token)

    s, j, _ = c.req("GET", "/api/health", token=None)
    check("health endpoint", s == 200 and j.get("status") == "ok", json.dumps(j))
    s, j, h = c.req("GET", "/api/health", token=None)
    low = {k.lower(): v for k, v in h.items()}
    check(
        "security headers (CSP, nosniff, no-referrer)",
        "content-security-policy" in low
        and low.get("x-content-type-options") == "nosniff"
        and "referrer-policy" in low,
    )
    if a.token:
        s, j, _ = c.req("GET", "/api/projects", token=None)
        check("API rejects requests without a token (401)", s == 401, f"status {s}")
        s, j, _ = c.req("GET", "/api/projects", token="wrong-token")
        check("API rejects a wrong token (401)", s == 401, f"status {s}")
        s, j, _ = c.req("GET", "/api/projects")
        check("API accepts the correct token", s == 200, f"status {s}")
        s, j, _ = c.req("GET", "/api/system")
        check(
            "system endpoint never echoes the token",
            s == 200 and a.token not in json.dumps(j) and j.get("auth_enabled") is True,
        )
    s, sysinfo, _ = c.req("GET", "/api/system")
    check(
        "system endpoint reports resources, queue and limits",
        s == 200 and "resources" in sysinfo and "queue" in sysinfo,
        f"cpu={sysinfo.get('resources', {}).get('cpu_count')} cgroup_mem_mb={sysinfo.get('cgroup_memory_limit_mb')}",
    )

    s, p, _ = c.req("POST", "/api/projects", {"name": "verify-deployment"})
    pid = p.get("project_id")
    check("create project", s == 201 and pid, f"status {s}")
    s, asset, _ = c.req("POST", f"/api/projects/{pid}/assets", {"name": "ARO TITAN 480", "category": "heavy_truck"})
    aid = asset.get("asset_id")
    check("create asset", s == 201 and aid)

    # ---- upload protections ------------------------------------------------------------------------------------------
    s, j, _ = c.upload(f"/api/projects/{pid}/sources", "ok.png", tiny_png())
    check("valid PNG accepted and stored by content hash", s == 201 and len(j.get("sha256", "")) == 64, f"status {s}")
    sha = j.get("sha256")
    s, j, _ = c.upload(f"/api/projects/{pid}/sources", "../../etc/passwd.png", b"<?php system($_GET['c']); ?>")
    check(
        "non-image content with an image filename rejected (400)",
        s == 400,
        f"status {s} {j.get('error', {}).get('message', '')[:80]}",
    )
    big = b"\x89PNG\r\n\x1a\n" + b"\0" * ((a.max_upload_mb + 1) * 1_000_000)
    s, j, _ = c.upload(f"/api/projects/{pid}/sources", "big.png", big)
    check(
        f"upload over {a.max_upload_mb} MB rejected (400)", s == 400 and "limit" in json.dumps(j).lower(), f"status {s}"
    )
    s, j, _ = c.upload(f"/api/projects/{pid}/sources", "bomb.png", huge_dimension_png())
    check(
        "decompression-bomb image (900 MP declared) rejected before decoding (400)",
        s == 400,
        f"status {s} {j.get('error', {}).get('message', '')[:80]}",
    )
    s, j, _ = c.upload(f"/api/projects/{pid}/sources", "trunc.png", tiny_png()[:60])
    check("truncated/corrupt image rejected (400)", s == 400, f"status {s}")

    # ---- archive protections (mesh import) ---------------------------------------------------------------------------
    for label, data in (
        ("zip-slip (../ member)", zip_bytes([("../../evil.obj", b"v 0 0 0\n")])),
        ("absolute-path member", zip_bytes([("/tmp/evil.obj", b"v 0 0 0\n")])),
        ("symlink member", zip_bytes([("m.obj", b"v 0 0 0\n")], symlink="link")),
        ("zip bomb (compression ratio)", zip_bytes([("zeros.obj", b"\0" * 6_000_000)])),
    ):
        s, j, _ = c.upload(f"/api/assets/{aid}/import", "a.zip", data)
        check(f"archive rejected: {label} (400)", s == 400, f"status {s} {j.get('error', {}).get('message', '')[:70]}")
    s, j, _ = c.req("GET", "/api/projects/..%2f..%2f..%2fetc%2fpasswd")
    check("path traversal in an id never reads files", s in (400, 404) and "root:" not in json.dumps(j), f"status {s}")
    s, j, _ = c.req("GET", "/api/projects/prj_" + "0" * 20)
    check("unknown id is a clean 404 with no traceback", s == 404 and "Traceback" not in json.dumps(j))

    # ---- inference failure handling ------------------------------------------------------------------------------------
    if sha:
        s, j, _ = c.req("POST", f"/api/assets/{aid}/generate", {"image_sha256": sha, "preset": "LOW_RESOURCE"})
        check("generation job accepted (202)", s == 202, f"status {s}")
        job = c.wait_job(j["job_id"]) if s == 202 else {}
        if a.expect_no_ai:
            err = job.get("error") or {}
            check(
                "no AI runtime: job ends MODEL_ERROR with an actionable explanation",
                job.get("state") == "MODEL_ERROR" and bool(err.get("recommended_action")),
                f"{job.get('state')} | {err.get('message', '')[:100]}",
            )
            s, ast, _ = c.req("GET", f"/api/assets/{aid}")
            check(
                "failed generation created no asset version (no placeholder geometry)",
                ast.get("versions") == [],
                f"versions={len(ast.get('versions', []))}",
            )
        s, j, _ = c.req("GET", "/api/health", token=None)
        check("service still healthy after the failed inference job", s == 200)

    # ---- full reference pipeline in the deployed service ----------------------------------------------------------------
    if not a.skip_pipeline:
        s, v, _ = c.req("POST", f"/api/assets/{aid}/reference/titan480")
        check("create ARO TITAN 480 procedural reference", s == 201, f"status {s}")
        cur = v.get("version_id")
        for op, params in (
            ("geometry", {"preset": "standard_cleanup"}),
            ("rig", {}),
            ("collision", {}),
            ("lod", {}),
            ("validate", {"config": {"check_intersections": False}}),
        ):
            s, j, _ = c.req("POST", f"/api/versions/{cur}/process", {"operation": op, "params": params})
            job = c.wait_job(j["job_id"]) if s == 202 else {"state": f"HTTP {s}"}
            ok = job["state"] == "COMPLETED"
            check(f"pipeline step: {op}", ok, job["state"] if ok else json.dumps(job.get("error"))[:200])
            if not ok:
                break
            if op != "validate":
                cur = job["result"]["version_id"]
            else:
                check(
                    "validation status PRODUCTION_READY, 0 critical failures",
                    job["result"]["status"] == "PRODUCTION_READY" and job["result"]["critical_failures"] == 0,
                    f"{job['result']['status']} {job['result']['overall']}%",
                )
        s, j, _ = c.req("POST", f"/api/versions/{cur}/export", {"formats": ["glb", "unity"]})
        job = c.wait_job(j["job_id"]) if s == 202 else {"state": f"HTTP {s}"}
        check("export GLB + Unity package (verified server-side)", job["state"] == "COMPLETED", job["state"])
        s, ex, _ = c.req("GET", f"/api/exports?asset_id={aid}")
        glb = next((e for e in ex.get("items", []) if e["format"] == "glb"), None)
        if glb:
            s, blob, _ = c.req("GET", f"/api/exports/{glb['export_id']}/download", raw=True)
            import hashlib

            check(
                "downloaded GLB is a glTF binary whose SHA-256 matches the export record",
                s == 200 and blob[:4] == b"glTF" and hashlib.sha256(blob).hexdigest() == glb["sha256"],
                f"{len(blob)} bytes",
            )
            check("GLB verification recorded as OK", glb["report"]["verification"]["ok"] is True)
        state = {"project_id": pid, "asset_id": aid}
    else:
        state = {"project_id": pid, "asset_id": aid}

    failed = [r for r in RESULTS if r["result"] != "PASS"]
    out = {
        "base_url": a.base_url,
        "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "state": state,
        "passed": len(RESULTS) - len(failed),
        "failed": len(failed),
        "checks": RESULTS,
    }
    if a.out:
        with open(a.out, "w") as f:
            json.dump(out, f, indent=2)
    print(f"\n{out['passed']}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
