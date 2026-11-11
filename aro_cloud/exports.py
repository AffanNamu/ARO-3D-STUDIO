"""Other file formats of a finished model, converted on demand from the stored GLB (CPU only, a few milliseconds for a game-sized mesh).

Formats: ``obj`` (a zip: OBJ + MTL + texture), ``stl`` (geometry, Z-up as slicers expect), ``ply`` (geometry + vertex colours). Each
contains the FULL-DETAIL model only (LOD0): no lower levels of detail and no collision mesh. FBX, USDZ and .blend are not offered:
they need Blender or the USD libraries, which this service does not carry.
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
import zipfile
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import trimesh
from trimesh.exchange.obj import export_obj

from aro_cloud.db import Database
from aro_cloud.errors import InvalidRequest, NotFound, Unavailable
from aro_cloud.glb import full_detail, load_scene, parts_of
from aro_cloud.storage import ObjectStore, ObjectTooLarge, StorageError

FORMATS: dict[str, tuple[str, str, str]] = {  # format -> (file extension, content type, what it is)
    "obj": ("zip", "application/zip", "Wavefront OBJ with material and texture (zip)"),
    "stl": ("stl", "model/stl", "STL, geometry only, Z-up, metres"),
    "ply": ("ply", "application/octet-stream", "PLY with vertex colours"),
}
_Y_UP_TO_Z_UP = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=np.float64)


class ConversionError(Exception):
    pass


def convert_glb(data: bytes, fmt: str) -> bytes:
    """Pure conversion: GLB bytes in, file bytes out. Raises ConversionError when the GLB holds nothing to export."""
    if fmt not in FORMATS:
        raise ConversionError(f"unknown format '{fmt}'")
    try:
        model = [p.mesh for p in full_detail(parts_of(load_scene(data)))]
    except Exception as e:  # noqa: BLE001 - any parser failure
        raise ConversionError(f"the GLB cannot be read ({type(e).__name__})") from None
    if not model:
        raise ConversionError("the GLB contains no model geometry")
    if fmt == "obj":
        return _obj_zip(model)
    if fmt == "stl":
        merged = _merged(model, keep_colour=False)
        merged.apply_transform(_Y_UP_TO_Z_UP)
        return _as_bytes(merged.export(file_type="stl"))
    return _as_bytes(_merged(model, keep_colour=True).export(file_type="ply"))


def _as_bytes(exported: Any) -> bytes:
    if isinstance(exported, bytes):
        return exported
    if isinstance(exported, str):
        return exported.encode()
    raise ConversionError("the exporter returned no file")


def _merged(meshes: list[trimesh.Trimesh], *, keep_colour: bool) -> trimesh.Trimesh:
    out = []
    for m in meshes:
        m = m.copy()
        if keep_colour:
            try:
                visual: Any = m.visual
                if getattr(visual, "kind", None) == "texture":
                    m.visual = visual.to_color()  # texture -> per-vertex colour, the most PLY readers understand
            except Exception:  # noqa: BLE001 - a colourless mesh is still a valid export
                m.visual = trimesh.visual.ColorVisuals(mesh=m)
        else:
            m.visual = trimesh.visual.ColorVisuals(mesh=m)
        out.append(m)
    merged: trimesh.Trimesh = trimesh.util.concatenate(out) if len(out) > 1 else out[0]  # type: ignore[assignment]
    return merged


def _obj_zip(meshes: list[trimesh.Trimesh]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, mesh in enumerate(meshes):
            folder = "" if len(meshes) == 1 else f"part_{i + 1}/"
            text, extra = export_obj(mesh, include_texture=True, return_texture=True)
            _add(z, folder + "model.obj", text.encode())
            for name, blob in (extra or {}).items():
                _add(z, folder + re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)), bytes(blob))
        _add(
            z, "README.txt", b"OBJ export from ARO 3D AI Studio. Units: metres. Up axis: +Y. Full-detail model only.\n"
        )
    return buf.getvalue()


def _add(z: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(
        name, date_time=(2020, 1, 1, 0, 0, 0)
    )  # fixed timestamp: the same model gives the same bytes
    info.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(info, data)


def export_file(
    db: Database,
    store: ObjectStore,
    owner: uuid.UUID,
    asset_id: uuid.UUID,
    version_no: int,
    fmt: str,
    *,
    max_glb_bytes: int,
    ttl_s: int,
) -> dict[str, Any]:
    """A signed download link for one format of one of the caller's own models. Converted once, then served from storage."""
    if fmt not in FORMATS:
        raise InvalidRequest(
            f"Unknown format '{fmt}'.", recommended_action="Use one of: " + ", ".join(FORMATS), code="unknown_format"
        )
    ext, ctype, _ = FORMATS[fmt]
    with db.transaction() as tx:
        row = tx.one(
            """
            select f.r2_key, v.version_id, a.name
            from files f
            join asset_versions v on v.version_id = f.version_id
            join assets a on a.asset_id = v.asset_id
            where a.asset_id = CAST(:a AS uuid) and a.owner_id = CAST(:o AS uuid) and a.status = 'active'
              and v.owner_id = CAST(:o AS uuid) and v.version_no = :n and f.role = 'glb' and f.owner_id = CAST(:o AS uuid)
            """,
            a=str(asset_id),
            o=str(owner),
            n=version_no,
        )
    if not row:
        raise NotFound("That model does not exist.", code="asset_not_found")
    key = (
        f"users/{owner}/exports/{row['version_id']}/model.{fmt}.{ext}"
        if ext != fmt
        else f"users/{owner}/exports/{row['version_id']}/model.{ext}"
    )
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", row["name"]).strip("._") or "model"
    filename = f"{stem}.{ext}" if ext == fmt else f"{stem}_{fmt}.{ext}"
    try:
        if store.head(key) is None:
            source = store.get_bytes(row["r2_key"], max_glb_bytes)
            data = convert_glb(source, fmt)
            store.put_bytes(key, data, ctype)
            with db.transaction() as tx:
                tx.execute(
                    """
                    insert into files (owner_id, version_id, role, r2_key, content_type, bytes, sha256)
                    values (CAST(:o AS uuid), CAST(:v AS uuid), 'export', :k, :c, :b, :s) on conflict (r2_key) do nothing
                    """,
                    o=str(owner),
                    v=str(row["version_id"]),
                    k=key,
                    c=ctype,
                    b=len(data),
                    s=hashlib.sha256(data).hexdigest(),
                )
    except ConversionError as e:
        raise InvalidRequest(f"This model cannot be exported as {fmt.upper()}: {e}.", code="export_failed") from None
    except ObjectTooLarge:
        raise InvalidRequest("This model is too large to convert.", code="export_failed") from None
    except StorageError:
        raise Unavailable(
            "The file store is not reachable right now.",
            recommended_action="Try again in a moment.",
            code="storage_unavailable",
        ) from None
    return {
        "url": store.presign_get(key, ttl_s, filename=filename),
        "expires_at": (datetime.now().astimezone() + timedelta(seconds=ttl_s)).isoformat(),
        "content_type": ctype,
        "filename": filename,
        "format": fmt,
    }
