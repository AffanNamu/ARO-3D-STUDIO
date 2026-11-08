"""The user's library: assets, their versions and files. Every query filters by owner; a file URL is issued only after that check."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from aro_cloud.db import Tx
from aro_cloud.errors import NotFound
from aro_cloud.storage import ObjectStore

DOWNLOAD_ROLES = ("glb", "raw_mesh", "thumbnail")
_EXT = {"glb": "glb", "raw_mesh": "glb", "thumbnail": "png"}


def list_assets(tx: Tx, owner: uuid.UUID, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    rows = tx.all(
        """
        select a.asset_id, a.name, a.category, a.status::text as status, a.created_at, a.updated_at, a.current_version_id,
               v.version_no, v.geometry_stats, v.provenance
        from assets a left join asset_versions v on v.version_id = a.current_version_id
        where a.owner_id = CAST(:o AS uuid) and a.status = 'active'
        order by a.updated_at desc limit :l offset :f
        """,
        o=str(owner),
        l=limit,
        f=offset,
    )
    return [_asset(r) for r in rows]


def get_asset(tx: Tx, owner: uuid.UUID, asset_id: uuid.UUID) -> dict[str, Any]:
    a = tx.one(
        """
        select a.asset_id, a.name, a.category, a.status::text as status, a.created_at, a.updated_at, a.current_version_id, a.metadata,
               v.version_no, v.geometry_stats, v.provenance
        from assets a left join asset_versions v on v.version_id = a.current_version_id
        where a.asset_id = CAST(:a AS uuid) and a.owner_id = CAST(:o AS uuid) and a.status = 'active'
        """,
        a=str(asset_id),
        o=str(owner),
    )
    if not a:
        raise NotFound("That asset does not exist.", code="asset_not_found")
    out = _asset(a)
    out["metadata"] = a["metadata"]
    versions = tx.all(
        "select version_id, version_no, label, geometry_stats, validation, provenance, created_at from asset_versions "
        "where asset_id = CAST(:a AS uuid) and owner_id = CAST(:o AS uuid) order by version_no desc",
        a=str(asset_id),
        o=str(owner),
    )
    for v in versions:
        v["version_id"] = str(v["version_id"])
        v["created_at"] = _iso(v["created_at"])
        v["files"] = [
            {"role": f["role"], "bytes": int(f["bytes"]), "sha256": f["sha256"], "content_type": f["content_type"]}
            for f in tx.all(
                "select role, bytes, sha256, content_type from files where version_id = CAST(:v AS uuid) and owner_id = CAST(:o AS uuid) order by role",
                v=v["version_id"],
                o=str(owner),
            )
        ]
    out["versions"] = versions
    return out


def file_url(
    tx: Tx, store: ObjectStore, owner: uuid.UUID, asset_id: uuid.UUID, version_no: int, role: str, ttl_s: int
) -> dict[str, Any]:
    """A short-lived pre-signed download URL for one file of one of the caller's own asset versions."""
    if role not in DOWNLOAD_ROLES:
        raise NotFound("That file does not exist.", code="file_not_found")
    row = tx.one(
        """
        select f.r2_key, f.content_type, a.name
        from files f
        join asset_versions v on v.version_id = f.version_id
        join assets a on a.asset_id = v.asset_id
        where a.asset_id = CAST(:a AS uuid) and a.owner_id = CAST(:o AS uuid) and a.status = 'active'
          and v.owner_id = CAST(:o AS uuid) and v.version_no = :n and f.role = :r and f.owner_id = CAST(:o AS uuid)
        """,
        a=str(asset_id),
        o=str(owner),
        n=version_no,
        r=role,
    )
    if not row:
        raise NotFound("That file does not exist.", code="file_not_found")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", row["name"]).strip("._") or "model"
    name = f"{stem}.{_EXT[role]}"
    return {
        "url": store.presign_get(row["r2_key"], ttl_s, filename=name),
        "expires_at": (datetime.now().astimezone() + timedelta(seconds=ttl_s)).isoformat(),
        "content_type": row["content_type"],
        "filename": name,
    }


def _asset(r: dict[str, Any]) -> dict[str, Any]:
    stats = r.get("geometry_stats") or {}
    prov = r.get("provenance") or {}
    return {
        "asset_id": str(r["asset_id"]),
        "name": r["name"],
        "category": r["category"],
        "status": r["status"],
        "created_at": _iso(r["created_at"]),
        "updated_at": _iso(r["updated_at"]),
        "current_version": r.get("version_no"),
        "triangles": stats.get("triangles"),
        "has_uv": stats.get("has_uv"),
        "engine": prov.get("engine"),
        "ai_inference": prov.get("ai_inference"),
    }


def _iso(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)
