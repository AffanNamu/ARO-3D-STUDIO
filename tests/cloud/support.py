"""Helpers for the platform tests: users, models, a scripted GPU provider and a simulated worker.

Everything labelled TEST DOUBLE here stands in for a paid external service. A test-double engine's output is never counted as AI
inference: the output gate refuses it unless a test explicitly allows it.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import trimesh
from PIL import Image

from aro_cloud import keys
from aro_cloud.db import Database
from aro_cloud.providers.base import ProviderAmbiguous, ProviderRejected, ProviderStatus, ProviderUnavailable
from aro_cloud.schemas import CreateGeneration
from aro_cloud.storage import ObjectStore


def make_user(db: Database, credits: int = 100) -> uuid.UUID:
    uid = uuid.uuid4()
    with db.transaction() as tx:
        tx.execute(
            "insert into auth.users (id, email) values (CAST(:u AS uuid), :e)",
            u=str(uid),
            e=f"{uid.hex[:8]}@example.test",
        )
        tx.execute("select ensure_user(CAST(:u AS uuid))", u=str(uid))
        if credits:
            tx.execute("select grant_credits(CAST(:u AS uuid), :n, 'test grant')", u=str(uid), n=credits)
    return uid


def enable_model(db: Database, model: str = "triposg") -> None:
    """What a person does with `python -m aro_cloud.admin verify-model ... enable-model ...` after reading the licence."""
    with db.transaction() as tx:
        tx.execute(
            "update model_registry set licence_status = 'verified', verified_by = 'test fixture', verified_at = now(), enabled = true where model_id = :m",
            m=model,
        )


def png_bytes(w: int = 512, h: int = 512) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 120, 60)).save(buf, "PNG")
    return buf.getvalue()


def make_glb(subdivisions: int = 3) -> bytes:
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions, radius=1.0)
    return bytes(trimesh.Scene(mesh).export(file_type="glb"))


def png_thumb() -> bytes:
    return png_bytes(64, 64)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_for(upload_id: uuid.UUID, **over: Any) -> CreateGeneration:
    body: dict[str, Any] = {"kind": "image_to_3d", "upload_id": str(upload_id), "name": "Test car", "engine": "triposg"}
    body.update(over)
    return CreateGeneration.model_validate(body)


def add_upload(db: Database, store: ObjectStore, owner: uuid.UUID) -> uuid.UUID:
    data = png_bytes()
    upload_id = uuid.uuid4()
    key = keys.upload_key(owner, upload_id, "png")
    store.put_bytes(key, data, "image/png")
    with db.transaction() as tx:
        tx.execute(
            "insert into uploads (upload_id, owner_id, r2_key, content_type, bytes, sha256, width, height, has_alpha) "
            "values (CAST(:u AS uuid), CAST(:o AS uuid), :k, 'image/png', :b, :s, 512, 512, false)",
            u=str(upload_id),
            o=str(owner),
            k=key,
            b=len(data),
            s=sha(data),
        )
    return upload_id


@dataclass
class Run:
    payload: dict[str, Any]
    state: str = "queued"
    output: dict[str, Any] | None = None
    error: str | None = None
    execution_ms: int | None = None


@dataclass
class ScriptedProvider:
    """TEST DOUBLE for RunPod: records what it is asked and answers from a script. It runs no model."""

    name: str = "test-double"
    runs: dict[str, Run] = field(default_factory=dict)
    submits: int = 0
    cancels: list[str] = field(default_factory=list)
    submit_errors: list[Exception] = field(default_factory=list)  # consumed one per submit call
    status_error: Exception | None = None
    cancel_error: Exception | None = None

    def submit(self, payload: dict[str, Any], *, execution_timeout_s: int, ttl_s: int) -> str:
        self.submits += 1
        if self.submit_errors:
            raise self.submit_errors.pop(0)
        rid = f"run-{self.submits}"
        self.runs[rid] = Run(payload)
        return rid

    def status(self, run_id: str) -> ProviderStatus:
        if self.status_error:
            raise self.status_error
        run = self.runs.get(run_id)
        if run is None:
            return ProviderStatus("unknown", raw_status="404")
        return ProviderStatus(run.state, output=run.output, error=run.error, execution_ms=run.execution_ms)

    def cancel(self, run_id: str) -> None:
        if self.cancel_error:
            raise self.cancel_error
        self.cancels.append(run_id)
        run = self.runs.get(run_id)
        if run and run.state in ("queued", "running"):
            run.state = "cancelled"

    @property
    def last(self) -> str:
        return f"run-{self.submits}"


def upload_as_worker(
    payload: dict[str, Any],
    *,
    glb: bytes | None = None,
    engine: str = "triposg",
    test_double: bool = False,
    corrupt_sha: bool = False,
    write_marker: bool = True,
    skip_roles: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Do what the real worker does with the URLs it was given: PUT each output, write result.json last, return the result dict."""
    glb = glb if glb is not None else make_glb()
    blobs = {
        "raw_mesh": glb,
        "glb": glb,
        "thumbnail": png_thumb(),
        "report": json.dumps({"status": "ok", "stage_times_s": {"generate": 12.5}}).encode(),
    }
    files = []
    for role, data in blobs.items():
        if role in skip_roles:
            continue
        spec = payload["outputs"][role]
        r = httpx.put(spec["put_url"], content=data, headers={"Content-Type": spec["content_type"]}, timeout=30)
        r.raise_for_status()
        files.append(
            {"role": role, "bytes": len(data), "sha256": ("0" * 64) if corrupt_sha and role == "glb" else sha(data)}
        )
    result = {
        "schema_version": 1,
        "ok": True,
        "engine": {"id": engine, "version": "test", "test_double": test_double},
        "files": files,
        "stats": {"total_s": 20.0},
        "validation": {},
    }
    if write_marker:
        spec = payload["outputs"]["result"]
        httpx.put(
            spec["put_url"],
            content=json.dumps(result).encode(),
            headers={"Content-Type": spec["content_type"]},
            timeout=30,
        ).raise_for_status()
    return result


def finish_run(provider: ScriptedProvider, run_id: str, **kw: Any) -> None:
    run = provider.runs[run_id]
    run.output = upload_as_worker(run.payload, **kw)
    run.state = "succeeded"
    run.execution_ms = 20_000


__all__ = [
    "ProviderAmbiguous",
    "ProviderRejected",
    "ProviderUnavailable",
    "ScriptedProvider",
    "add_upload",
    "enable_model",
    "finish_run",
    "make_glb",
    "make_user",
    "png_bytes",
    "request_for",
    "sha",
    "upload_as_worker",
]


def make_game_glb() -> bytes:
    """A GLB shaped like the pipeline's output: textured LOD0..LOD2 plus a collision hull, all overlapping."""
    import numpy as np

    scene = trimesh.Scene()
    for level, sub in ((0, 3), (1, 2), (2, 1)):
        m = trimesh.creation.icosphere(subdivisions=sub, radius=1.0)
        uv = np.column_stack([(m.vertices[:, 0] + 1) / 2, (m.vertices[:, 1] + 1) / 2])
        tex = Image.new("RGB", (16, 16), (200, 60, 50))
        m.visual = trimesh.visual.TextureVisuals(uv=uv, image=tex)
        scene.add_geometry(m, node_name=f"Car_LOD{level}", geom_name=f"Car_LOD{level}")
    hull = trimesh.creation.box((2, 2, 2))
    scene.add_geometry(hull, node_name="COL_Hull", geom_name="COL_Hull")
    return bytes(scene.export(file_type="glb"))
