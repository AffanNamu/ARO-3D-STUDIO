"""Object storage (Cloudflare R2 through the S3 API).

* Keys are built by the server from validated ids only (``keys.py``); a client-supplied string never becomes a key.
* Reads for browsers are short-lived pre-signed GET URLs issued after an ownership check. The GPU worker gets pre-signed PUT URLs for
  exactly the keys it may write and holds NO storage credentials. R2 pre-signed PUTs cannot bound the size, so the server re-checks
  size and SHA-256 after the worker reports completion.
* R2 charges no egress; the bucket stays private (no public access, no custom domain).
"""

from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,510}$")


class StorageError(RuntimeError):
    pass


class ObjectTooLarge(StorageError):
    pass


@dataclass(frozen=True)
class ObjectMeta:
    size: int
    etag: str | None
    content_type: str | None


def check_key(key: str) -> str:
    if not _KEY.match(key) or ".." in key.split("/") or "//" in key:
        raise StorageError("invalid object key")
    return key


class ObjectStore(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str) -> None: ...
    def get_bytes(self, key: str, max_bytes: int) -> bytes: ...
    def head(self, key: str) -> ObjectMeta | None: ...
    def delete(self, key: str) -> None: ...
    def presign_get(self, key: str, ttl_s: int, filename: str | None = None) -> str: ...
    def presign_put(self, key: str, ttl_s: int, content_type: str) -> str: ...


def _safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "download"
    return stem[:100]


class R2Store:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        client: Any = None,
    ) -> None:
        self.bucket = bucket
        self._c = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            ),
        )

    # -- writes ----------------------------------------------------------------------------------------------------------------
    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._c.put_object(Bucket=self.bucket, Key=check_key(key), Body=io.BytesIO(data), ContentType=content_type)
        except (ClientError, BotoCoreError) as e:
            raise StorageError(f"could not store the object ({type(e).__name__})") from None

    def delete(self, key: str) -> None:
        try:
            self._c.delete_object(Bucket=self.bucket, Key=check_key(key))
        except (ClientError, BotoCoreError) as e:
            raise StorageError(f"could not delete the object ({type(e).__name__})") from None

    # -- reads -----------------------------------------------------------------------------------------------------------------
    def head(self, key: str) -> ObjectMeta | None:
        try:
            r = self._c.head_object(Bucket=self.bucket, Key=check_key(key))
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise StorageError(f"could not read object metadata ({e.response.get('Error', {}).get('Code')})") from None
        except BotoCoreError as e:
            raise StorageError(f"could not read object metadata ({type(e).__name__})") from None
        return ObjectMeta(int(r["ContentLength"]), r.get("ETag"), r.get("ContentType"))

    def get_bytes(self, key: str, max_bytes: int) -> bytes:
        meta = self.head(key)
        if meta is None:
            raise StorageError("object not found")
        if meta.size > max_bytes:
            raise ObjectTooLarge(f"object is {meta.size} bytes, above the {max_bytes} byte limit")
        try:
            r = self._c.get_object(Bucket=self.bucket, Key=check_key(key))
            data: bytes = r["Body"].read(max_bytes + 1)
        except (ClientError, BotoCoreError) as e:
            raise StorageError(f"could not read the object ({type(e).__name__})") from None
        if len(data) > max_bytes:
            raise ObjectTooLarge("object grew beyond the limit while being read")
        return data

    # -- signed URLs (computed locally; no network) -----------------------------------------------------------------------------
    def presign_get(self, key: str, ttl_s: int, filename: str | None = None) -> str:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": check_key(key)}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{_safe_filename(filename)}"'
        return str(self._c.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl_s, HttpMethod="GET"))

    def presign_put(self, key: str, ttl_s: int, content_type: str) -> str:
        params = {"Bucket": self.bucket, "Key": check_key(key), "ContentType": content_type}
        return str(self._c.generate_presigned_url("put_object", Params=params, ExpiresIn=ttl_s, HttpMethod="PUT"))


def expires_at(ttl_s: int) -> float:
    return time.time() + ttl_s
