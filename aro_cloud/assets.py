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


def list_assets(
    tx: Tx, owner: uuid.UUID, limit: int = 50, offset: int = 0, q: str | None = None
) -> list[dict[str, Any]]:
    """Newest first. ``q`` filters by name (case-insensitive substring; the wildcard characters are matched literally)."""
    pattern = None
    if q and q.strip():
        escaped = q.strip()[:100].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
    rows = tx.all(
        """
        select a.asset_id, a.name, a.category, a.status::text as status, a.created_at, a.updated_at, a.current_version_id,
               v.version_no, v.geometry_stats, v.provenance
        from assets a left join asset_versions v on v.version_id = a.current_version_id
        where a.owner_id = CAST(:o AS uuid) and a.status = 'active'
          and (CAST(:q AS text) is null or a.name ilike CAST(:q AS text) escape '\\')
        order by a.updated_at desc limit :l offset :f
        """,
        o=str(owner),
        q=pattern,
        l=limit,
        f=offset,
    )
    return [_asset(r) for r in rows]


def rename_asset(tx: Tx, owner: uuid.UUID, asset_id: uuid.UUID, name: str) -> dict[str, Any]:
    n = tx.execute(
        "update assets set name = :n, updated_at = now() where asset_id = CAST(:a AS uuid) and owner_id = CAST(:o AS uuid) and status = 'active'",
        n=name,
        a=str(asset_id),
        o=str(owner),
    )
    if n != 1:
        raise NotFound("That asset does not exist.", code="asset_not_found")
    return get_asset(tx, owner, asset_id)


def delete_asset(tx: Tx, owner: uuid.UUID, asset_id: uuid.UUID) -> None:
    """Soft delete: the model leaves the library and its files can no longer be linked to. The stored objects are purged by the retention
    policy, not here, so a mistake can still be undone by an operator."""
    n = tx.execute(
        "update assets set status = 'deleted', deleted_at = now(), updated_at = now() "
        "where asset_id = CAST(:a AS uuid) and owner_id = CAST(:o AS uuid) and status = 'active'",
        a=str(asset_id),
        o=str(owner),
    )
    if n != 1:
        raise NotFound("That asset does not exist.", code="asset_not_found")
    tx.execute(
        "insert into audit_log (actor_id, action, target, detail) values (CAST(:o AS uuid), 'delete_asset', :t, '{}'::jsonb)",
        o=str(owner),
        t=str(asset_id),
    )


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
    current = next((v for v in versions if v["version_no"] == a.get("version_no")), None)
    out["model"] = _model_summary(current) if current else None
    return out


def _model_summary(v: dict[str, Any]) -> dict[str, Any]:
    """What a person wants to know about a finished model, taken from the facts recorded when it was accepted."""
    stats = v.get("geometry_stats") or {}
    prov = v.get("provenance") or {}
    val = v.get("validation") or {}
    report = val.get("report") or {}
    studio = report.get("validation") or {}
    cats = studio.get("categories") or {}
    problems = [
        {k: c.get(k) for k in ("id", "category", "title", "severity", "status", "message")}
        for c in (studio.get("checks") or [])
        if isinstance(c, dict) and str(c.get("status", "")).lower() in ("failed", "warning")
    ]
    return {
        "version": v["version_no"],
        "triangles": stats.get("triangles"),
        "vertices": stats.get("vertices"),
        "extents_m": stats.get("extents"),
        "lods": stats.get("lods") or [],
        "collision_triangles": stats.get("collision_triangles"),
        "has_uv": stats.get("has_uv"),
        "bytes": stats.get("bytes"),
        "engine": prov.get("engine"),
        "engine_version": prov.get("engine_version"),
        "ai_inference": prov.get("ai_inference"),
        "test_double": prov.get("test_double"),
        "settings": prov.get("settings") or {},
        "files": [{"role": f["role"], "bytes": f["bytes"]} for f in v.get("files", [])],
        "checks": {
            "status": studio.get("status"),
            "overall": studio.get("overall"),
            "critical_failures": studio.get("critical_failures"),
            "major_failures": studio.get("major_failures"),
            "blocking_reasons": list(studio.get("blocking_reasons") or [])[:10],
            "categories": [
                {
                    "id": k,
                    "score": c.get("score"),
                    "failed": c.get("failed"),
                    "warnings": c.get("warnings"),
                    "applicable": c.get("applicable"),
                }
                for k, c in cats.items()
                if isinstance(c, dict)
            ],
            "problems": problems[:40],
        }
        if studio
        else None,
        "needs_human": list(report.get("needs_human") or [])[:20],
        "warnings": list(val.get("warnings") or []),
    }


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
