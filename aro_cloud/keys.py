"""Object keys, built from server-validated UUIDs and fixed names only."""

from __future__ import annotations

import uuid

# role -> (file name, content type). The GPU worker may write exactly these names under its job prefix, nothing else.
JOB_FILES: dict[str, tuple[str, str]] = {
    "raw_mesh": ("raw.glb", "model/gltf-binary"),
    "glb": ("model.glb", "model/gltf-binary"),
    "thumbnail": ("thumbnail.png", "image/png"),
    "report": ("report.json", "application/json"),
    "result": (
        "result.json",
        "application/json",
    ),  # completion marker, written LAST: lets the API recover a finished job if RunPod's record expired
}
REQUIRED_ROLES = ("glb", "result")


def upload_key(owner: uuid.UUID, upload_id: uuid.UUID, ext: str) -> str:
    return f"users/{owner}/uploads/{upload_id}.{ext}"


def job_prefix(owner: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"users/{owner}/jobs/{job_id}"


def job_key(owner: uuid.UUID, job_id: uuid.UUID, role: str) -> str:
    return f"{job_prefix(owner, job_id)}/{JOB_FILES[role][0]}"
