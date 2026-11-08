"""R2 access through the S3 API, exercised against a real S3-compatible server (moto) over HTTP, pre-signed URLs included."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from aro_cloud.storage import ObjectTooLarge, StorageError, check_key


def test_roundtrip_head_and_delete(store):
    store.put_bytes("users/u/uploads/a.png", b"hello", "image/png")
    meta = store.head("users/u/uploads/a.png")
    assert meta is not None and meta.size == 5 and meta.content_type == "image/png"
    assert store.get_bytes("users/u/uploads/a.png", 100) == b"hello"
    store.delete("users/u/uploads/a.png")
    assert store.head("users/u/uploads/a.png") is None


def test_reading_more_than_the_limit_is_refused(store):
    store.put_bytes("users/u/big.bin", b"x" * 1000, "application/octet-stream")
    with pytest.raises(ObjectTooLarge):
        store.get_bytes("users/u/big.bin", 999)


def test_a_missing_object_is_none_for_head_and_an_error_for_get(store):
    assert store.head("users/u/none.bin") is None
    with pytest.raises(StorageError):
        store.get_bytes("users/u/none.bin", 10)


@pytest.mark.parametrize("key", ["", "/abs", "../x", "a/../b", "a//b", "a b", "a\nb", "x" * 600, ".hidden"])
def test_keys_are_validated(key):
    with pytest.raises(StorageError):
        check_key(key)


def test_presigned_get_downloads_with_a_safe_filename(store):
    store.put_bytes("users/u/jobs/j/model.glb", b"glTFdata", "model/gltf-binary")
    url = store.presign_get("users/u/jobs/j/model.glb", 300, filename='my "car"\r\n.glb')
    r = httpx.get(url)
    assert r.status_code == 200 and r.content == b"glTFdata"
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment; filename=") and "\r" not in cd and "\n" not in cd and '"car"' not in cd


def test_presigned_put_lets_a_credential_free_client_write_a_bound_key(store):
    url = store.presign_put("users/u/jobs/j/model.glb", 300, "model/gltf-binary")
    r = httpx.put(url, content=b"glTF-from-worker", headers={"Content-Type": "model/gltf-binary"})
    assert r.status_code == 200
    data = store.get_bytes("users/u/jobs/j/model.glb", 100)
    assert hashlib.sha256(data).hexdigest() == hashlib.sha256(b"glTF-from-worker").hexdigest()
    # Signature enforcement (a URL authorises only its own key and content type) is done by R2/S3 itself; moto does not check SigV4, so it is
    # not asserted here. What is ours: each URL is bound to one key and one content type, and carries an expiry.
    assert "X-Amz-Expires=300" in url and "content-type" in url.lower()
    assert store.presign_put("users/u/jobs/j/other.glb", 300, "model/gltf-binary") != url
