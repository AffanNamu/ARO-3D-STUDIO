"""Input images. Validated by content (the Studio's existing image validator), then stored privately; clients never write to storage."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from aro_cloud import keys
from aro_cloud.db import Database
from aro_cloud.errors import InvalidRequest, NotFound
from aro_cloud.settings import CloudSettings
from aro_cloud.storage import ObjectStore, StorageError
from aro_studio.core.errors import InvalidInputError
from aro_studio.imaging.validate import load_image
from aro_studio.security.uploads import sniff

EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def create_upload(
    db: Database, store: ObjectStore, settings: CloudSettings, owner: uuid.UUID, data: bytes
) -> dict[str, Any]:
    """Validate and store one image. The same bytes uploaded twice by one user return the first upload."""
    try:
        image, report = load_image(
            data,
            max_bytes=settings.max_upload_mb * 1_000_000,
            max_pixels=settings.max_image_pixels,
            min_side=settings.min_image_side,
        )
    except InvalidInputError as e:
        raise InvalidRequest(
            str(e), recommended_action=getattr(e, "recommended_action", None), code="invalid_image"
        ) from None
    image.close()
    content_type = sniff(data).mime
    sha = hashlib.sha256(data).hexdigest()
    with db.transaction() as tx:
        prior = tx.one(
            "select upload_id, content_type, bytes, sha256, width, height, has_alpha, created_at from uploads "
            "where owner_id = CAST(:o AS uuid) and sha256 = :s order by created_at limit 1",
            o=str(owner),
            s=sha,
        )
    if prior:
        return _view(prior, report.warnings)
    upload_id = uuid.uuid4()
    key = keys.upload_key(owner, upload_id, EXT[content_type])
    try:
        store.put_bytes(key, data, content_type)
    except StorageError:
        raise InvalidRequest(
            "The image could not be stored. Try again in a moment.", code="storage_unavailable"
        ) from None
    with db.transaction() as tx:
        row = tx.one(
            """
            insert into uploads (upload_id, owner_id, r2_key, content_type, bytes, sha256, width, height, has_alpha)
            values (CAST(:u AS uuid), CAST(:o AS uuid), :k, :c, :b, :s, :w, :h, :a)
            returning upload_id, content_type, bytes, sha256, width, height, has_alpha, created_at
            """,
            u=str(upload_id),
            o=str(owner),
            k=key,
            c=content_type,
            b=len(data),
            s=sha,
            w=report.width,
            h=report.height,
            a=bool(report.has_alpha),
        )
    assert row is not None
    return _view(row, report.warnings)


def _view(row: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    return {
        "upload_id": str(row["upload_id"]),
        "content_type": row["content_type"],
        "bytes": row["bytes"],
        "width": row["width"],
        "height": row["height"],
        "has_alpha": row["has_alpha"],
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else str(row["created_at"]),
        "warnings": warnings,
    }


def upload_url(db: Database, store: ObjectStore, owner: uuid.UUID, upload_id: uuid.UUID, ttl_s: int) -> dict[str, Any]:
    """A short-lived link to one of the caller's own uploaded images (the reference a model was made from)."""
    with db.transaction() as tx:
        row = tx.one(
            "select r2_key, content_type, width, height from uploads where upload_id = CAST(:u AS uuid) and owner_id = CAST(:o AS uuid)",
            u=str(upload_id),
            o=str(owner),
        )
    if not row:
        raise NotFound("That upload does not exist.", code="upload_not_found")
    return {
        "url": store.presign_get(row["r2_key"], ttl_s),
        "content_type": row["content_type"],
        "width": row["width"],
        "height": row["height"],
    }
