"""Fixtures for the platform tests.

* A REAL PostgreSQL (``ARO_TEST_DATABASE_URL`` = a superuser URL such as postgresql://postgres@127.0.0.1:5432/postgres). The migrations are
  applied once to a template database (with the minimum of Supabase's ``auth`` schema stubbed); every test gets its own copy of it.
  Without the variable these tests skip locally; CI sets ``ARO_CLOUD_TESTS_REQUIRED=1`` so a missing database is a failure there.
* A real S3 API server (moto, in-process) standing in for Cloudflare R2, reached over HTTP like R2 is, including pre-signed URLs.
* Nothing here talks to RunPod, Supabase or Cloudflare.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from urllib.parse import unquote, urlparse

import boto3
import pg8000.native
import pytest

from aro_cloud.db import Database
from aro_cloud.migrate import migrate
from aro_cloud.settings import CloudSettings
from aro_cloud.storage import R2Store

ADMIN_URL = os.environ.get("ARO_TEST_DATABASE_URL")
REQUIRED = os.environ.get("ARO_CLOUD_TESTS_REQUIRED") == "1"


def _admin() -> pg8000.native.Connection:
    assert ADMIN_URL
    u = urlparse(ADMIN_URL)
    return pg8000.native.Connection(
        user=unquote(u.username or "postgres"),
        password=unquote(u.password) if u.password else None,
        host=u.hostname or "127.0.0.1",
        port=u.port or 5432,
        database=(u.path or "/postgres").lstrip("/") or "postgres",
    )


def _url_for(dbname: str) -> str:
    assert ADMIN_URL
    u = urlparse(ADMIN_URL)
    return u._replace(path="/" + dbname).geturl()


@pytest.fixture(scope="session")
def template_db() -> Iterator[str]:
    if not ADMIN_URL:
        if REQUIRED:
            pytest.fail("ARO_CLOUD_TESTS_REQUIRED=1 but ARO_TEST_DATABASE_URL is not set")
        pytest.skip("set ARO_TEST_DATABASE_URL to run the PostgreSQL tests")
    name = "aro_tmpl_" + uuid.uuid4().hex[:10]
    admin = _admin()
    admin.run(f'create database "{name}"')
    db = Database(_url_for(name), ssl_mode="disable")
    try:
        migrate(db, stub_auth=True)
    finally:
        db.close()
    yield name
    admin.run(f'drop database if exists "{name}" with (force)')
    admin.close()


@pytest.fixture
def pg(template_db: str) -> Iterator[Database]:
    name = "aro_t_" + uuid.uuid4().hex[:10]
    admin = _admin()
    admin.run(f'create database "{name}" template "{template_db}"')
    db = Database(_url_for(name), ssl_mode="disable")
    yield db
    db.close()
    admin.run(f'drop database if exists "{name}" with (force)')
    admin.close()


@pytest.fixture(scope="session")
def s3_server() -> Iterator[str]:
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def store(s3_server: str) -> R2Store:
    bucket = "aro-test-" + uuid.uuid4().hex[:10]
    client = boto3.client(
        "s3",
        endpoint_url=s3_server,
        aws_access_key_id="test-key",
        aws_secret_access_key="test-secret",  # noqa: S106 - moto accepts anything
        region_name="us-east-1",  # moto refuses CreateBucket with R2's pseudo-region "auto"; the service under test uses "auto" like R2
    )
    client.create_bucket(Bucket=bucket)
    return R2Store(
        bucket=bucket, endpoint_url=s3_server, access_key_id="test-key", secret_access_key="test-secret", region="auto"
    )


@pytest.fixture
def settings() -> CloudSettings:
    return CloudSettings(
        env="test",
        enabled_engines="triposg",
        price_image_to_3d=10,
        allow_test_double=False,
        requests_per_minute=6000,
        allowed_origins="http://localhost:3000",
        internal_token="t" * 32,
        max_attempts=2,
        retry_backoff_s=1,
        dispatch_grace_s=30,
        ingest_stale_s=30,
        gpu_usd_per_second=0.0005,
    )
