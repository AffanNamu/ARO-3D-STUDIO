"""Read-only checks that say, in plain words, whether a part of the setup is correct. Nothing printed here is a secret.

    python -m aro_cloud.doctor --env-file ~/aro-secrets/aro.env supabase
    python -m aro_cloud.doctor --env-file ~/aro-secrets/aro.env r2 --origin http://localhost:3000
    python -m aro_cloud.doctor --env-file ~/aro-secrets/aro.env runpod
    python -m aro_cloud.doctor --env-file ~/aro-secrets/aro.env all

What each area touches: ``supabase`` only READS (one connection, catalogue queries, the public key endpoint). ``r2`` writes, reads and deletes a few
tiny objects under ``doctor/`` in your bucket. ``runpod`` calls the endpoint's free /health route: it submits no job and starts no GPU.
Statuses: PASS, FAIL, PARTIAL (works but needs attention), BLOCKED (not checked because an earlier check failed).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from aro_cloud.db import Database, DatabaseError
from aro_cloud.envfile import load_env_file
from aro_cloud.migrate import MIGRATIONS
from aro_cloud.settings import CloudSettings
from aro_cloud.storage import ObjectStore, R2Store, StorageError

CREDIT_FUNCTIONS = (
    "ensure_user(uuid)",
    "grant_credits(uuid,integer,text)",
    "reserve_credits(uuid,uuid,integer)",
    "capture_credits(uuid,uuid)",
    "release_credits(uuid,uuid)",
)


@dataclass
class Check:
    area: str
    name: str
    status: str  # PASS | FAIL | PARTIAL | BLOCKED
    detail: str
    hint: str | None = None


def _missing(s: CloudSettings, area: str, names: dict[str, bool]) -> Check | None:
    absent = [n for n, ok in names.items() if not ok]
    if absent:
        return Check(
            area,
            "configuration",
            "FAIL",
            "not set: " + ", ".join(absent),
            "Add them to your private env file (see docs/platform/owner-setup.md).",
        )
    return None


def project_ref(s: CloudSettings) -> str | None:
    host = urlparse(s.supabase_url or "").hostname or ""
    return host.split(".")[0] if host.endswith(".supabase.co") else None


# ====================================================================================================================== Supabase
def check_supabase(s: CloudSettings, *, db: Database | None = None, http: httpx.Client | None = None) -> list[Check]:
    out: list[Check] = []
    miss = _missing(s, "supabase", {"ARO_DATABASE_URL": bool(s.database_url), "ARO_SUPABASE_URL": bool(s.supabase_url)})
    if miss:
        return [miss]
    out.append(Check("supabase", "configuration", "PASS", "ARO_DATABASE_URL and ARO_SUPABASE_URL are set"))
    ref = project_ref(s)
    if not ref:
        out.append(
            Check(
                "supabase",
                "project URL",
                "FAIL",
                "ARO_SUPABASE_URL should look like https://<project-ref>.supabase.co",
                "Copy the Project URL from Project Settings -> API.",
            )
        )
    assert s.database_url is not None
    u = urlparse(s.database_url.get_secret_value())
    user = u.username or ""
    host = u.hostname or ""
    db_ref = (
        user.split(".", 1)[1]
        if "." in user
        else (host.split(".")[1] if host.startswith("db.") and host.count(".") >= 3 else None)
    )
    if ref and db_ref and ref != db_ref:
        out.append(
            Check(
                "supabase",
                "same project",
                "FAIL",
                f"the database connection points at project '{db_ref}' but ARO_SUPABASE_URL is project '{ref}'",
                "Both must come from the SAME Supabase project.",
            )
        )
    elif ref and db_ref:
        out.append(Check("supabase", "same project", "PASS", f"database and URL are both project '{ref}'"))
    else:
        out.append(
            Check(
                "supabase",
                "same project",
                "PARTIAL",
                "could not compare the project of the database string with the URL",
            )
        )
    if host.startswith("db.") and host.endswith(".supabase.co"):
        out.append(
            Check(
                "supabase",
                "connection type",
                "PARTIAL",
                "direct connection (db.<ref>.supabase.co)",
                "Direct connections are IPv6-only on many networks and hosts. If the next check fails, use the pooler string instead.",
            )
        )

    own_db = db is None
    try:
        db = db or Database(s.database_url.get_secret_value(), ssl_mode=s.database_ssl, ca_file=s.database_ca_file)
        with db.transaction() as tx:
            info = tx.one("select version() as v, current_database() as d")
            assert info is not None
            out.append(
                Check(
                    "supabase",
                    "database connection",
                    "PASS",
                    f"connected to database '{info['d']}' ({str(info['v']).split(',')[0][:40]}), TLS mode {s.database_ssl}",
                )
            )
            has_auth = tx.one("select to_regclass('auth.users') as t")
            if not (has_auth and has_auth["t"]):
                out.append(
                    Check(
                        "supabase",
                        "Supabase auth schema",
                        "FAIL",
                        "auth.users does not exist: this does not look like a Supabase database",
                        "Use the connection string of your Supabase project.",
                    )
                )
                return out
            out.append(Check("supabase", "Supabase auth schema", "PASS", "auth.users exists"))
            out += _supabase_schema_checks(tx)
    except DatabaseError as e:
        out.append(
            Check(
                "supabase",
                "database connection",
                "FAIL",
                str(e),
                "Fix ARO_DATABASE_URL / ARO_DATABASE_SSL, then run this check again.",
            )
        )
        out.append(Check("supabase", "schema checks", "BLOCKED", "need a database connection"))
    finally:
        if own_db and db is not None:
            db.close()
    out += _jwks_check(s, http)
    return out


def _supabase_schema_checks(tx) -> list[Check]:
    out: list[Check] = []
    applied = (
        {r["name"]: r["sha256"] for r in tx.all("select name, sha256 from public.aro_migrations")}
        if tx.one("select to_regclass('public.aro_migrations') as t")["t"]
        else {}
    )
    files = sorted(MIGRATIONS.glob("*.sql"))
    missing = [f.name for f in files if f.name not in applied]
    changed = [
        f.name for f in files if f.name in applied and applied[f.name] != hashlib.sha256(f.read_bytes()).hexdigest()
    ]
    if missing:
        out.append(
            Check(
                "supabase",
                "migrations",
                "FAIL",
                "not applied: " + ", ".join(missing),
                "Run: python -m aro_cloud.migrate --env-file <your env file>",
            )
        )
        return out
    if changed:
        out.append(
            Check(
                "supabase",
                "migrations",
                "FAIL",
                "applied but different from the repository: " + ", ".join(changed),
                "Never edit an applied migration; add a new one.",
            )
        )
    else:
        out.append(Check("supabase", "migrations", "PASS", f"{len(files)} applied, checksums match the repository"))
    bare = [
        r["relname"]
        for r in tx.all(
            "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relrowsecurity order by 1"
        )
    ]
    out.append(
        Check(
            "supabase",
            "row level security",
            "PASS" if not bare else "FAIL",
            "enabled on every table in schema public" if not bare else "NOT enabled on: " + ", ".join(bare),
            None
            if not bare
            else "Supabase exposes public tables through its API: enable RLS on them (alter table <name> enable row level security).",
        )
    )
    try:
        leaks = []
        for fn in CREDIT_FUNCTIONS:
            for role in ("anon", "authenticated"):
                r = tx.one("select has_function_privilege(:r, :f, 'execute') as ok", r=role, f=fn)
                if r and r["ok"]:
                    leaks.append(f"{role} can run {fn.split('(')[0]}")
        out.append(
            Check(
                "supabase",
                "credit functions closed to browsers",
                "PASS" if not leaks else "FAIL",
                "anon and authenticated cannot run any credit function" if not leaks else "; ".join(leaks),
                None if not leaks else "The migration revokes these; re-apply it or run the revoke statements by hand.",
            )
        )
    except DatabaseError:
        out.append(
            Check(
                "supabase",
                "credit functions closed to browsers",
                "PARTIAL",
                "could not test (roles anon/authenticated missing?)",
            )
        )
    reg = tx.all("select model_id, licence_status::text as st, enabled from model_registry order by model_id")
    out.append(
        Check(
            "supabase",
            "model registry",
            "PASS",
            "; ".join(f"{r['model_id']}: {r['st']}, {'enabled' if r['enabled'] else 'disabled'}" for r in reg)
            + " (a model stays disabled until YOU verify its licence)",
        )
    )
    n = tx.one("select count(*) as n from auth.users")
    out.append(
        Check(
            "supabase",
            "sign-ups",
            "PASS",
            f"{n['n'] if n else 0} user(s) in auth.users"
            + ("" if n and n["n"] else " (create your account in the web app, then run /v1/me once)"),
        )
    )
    return out


def _jwks_check(s: CloudSettings, http: httpx.Client | None) -> list[Check]:
    url = s.jwks_url
    if not url:
        return [Check("supabase", "token signing keys", "BLOCKED", "no ARO_SUPABASE_URL")]
    try:
        r = (http or httpx.Client(timeout=8)).get(url)
    except httpx.HTTPError as e:
        return [
            Check(
                "supabase",
                "token signing keys",
                "FAIL",
                f"could not reach the key endpoint ({type(e).__name__})",
                "Check ARO_SUPABASE_URL and your internet connection.",
            )
        ]
    keys = []
    if r.status_code == 200:
        try:
            keys = r.json().get("keys", [])
        except ValueError:
            keys = []
    if keys:
        algs = sorted({str(k.get("alg", "?")) for k in keys})
        return [
            Check(
                "supabase",
                "token signing keys",
                "PASS",
                f"{len(keys)} public key(s) published, algorithms {', '.join(algs)}: no shared secret needed",
            )
        ]
    if s.supabase_jwt_secret:
        return [
            Check(
                "supabase",
                "token signing keys",
                "PASS",
                "no public keys published; ARO_SUPABASE_JWT_SECRET is set (legacy shared-secret project)",
            )
        ]
    return [
        Check(
            "supabase",
            "token signing keys",
            "FAIL",
            f"no public keys at the key endpoint (HTTP {r.status_code}) and ARO_SUPABASE_JWT_SECRET is not set",
            "This looks like a legacy project: add its JWT secret (Project Settings -> API -> JWT Settings) as ARO_SUPABASE_JWT_SECRET.",
        )
    ]


# ============================================================================================================================ R2
def check_r2(
    s: CloudSettings, *, store: ObjectStore | None = None, http: httpx.Client | None = None, origin: str | None = None
) -> list[Check]:
    miss = _missing(
        s,
        "r2",
        {
            "ARO_R2_ACCOUNT_ID (or ARO_R2_ENDPOINT_URL)": bool(s.r2_endpoint),
            "ARO_R2_BUCKET": bool(s.r2_bucket),
            "ARO_R2_ACCESS_KEY_ID": bool(s.r2_access_key_id),
            "ARO_R2_SECRET_ACCESS_KEY": bool(s.r2_secret_access_key),
        },
    )
    if miss:
        return [miss]
    out = [Check("r2", "configuration", "PASS", "account, bucket and access key are set")]
    if store is None:
        assert s.r2_endpoint and s.r2_bucket and s.r2_access_key_id and s.r2_secret_access_key
        store = R2Store(
            bucket=s.r2_bucket,
            endpoint_url=s.r2_endpoint,
            access_key_id=s.r2_access_key_id.get_secret_value(),
            secret_access_key=s.r2_secret_access_key.get_secret_value(),
            region=s.r2_region,
        )
    client = http or httpx.Client(timeout=15)
    key = f"doctor/{uuid.uuid4()}.txt"
    body = b"aro doctor " + uuid.uuid4().hex.encode()
    created = [key]
    try:
        try:
            store.put_bytes(key, body, "text/plain")
            meta = store.head(key)
            got = store.get_bytes(key, 1000)
            ok = meta is not None and got == body
            out.append(
                Check(
                    "r2",
                    "write, read, head",
                    "PASS" if ok else "FAIL",
                    "a test object was written and read back" if ok else "the object read back differently",
                )
            )
        except StorageError as e:
            out.append(
                Check(
                    "r2",
                    "write, read, head",
                    "FAIL",
                    str(e),
                    "Check the account id, bucket name and that the token has Object Read & Write on THIS bucket.",
                )
            )
            out.append(Check("r2", "signed URLs, privacy, CORS", "BLOCKED", "need working storage access"))
            return out
        url = store.presign_get(key, 120)
        try:
            r = client.get(url)
            out.append(
                Check(
                    "r2",
                    "signed download link",
                    "PASS" if r.status_code == 200 and r.content == body else "FAIL",
                    "a pre-signed GET link downloads the object"
                    if r.status_code == 200
                    else f"the link answered HTTP {r.status_code}",
                )
            )
        except httpx.HTTPError as e:
            out.append(Check("r2", "signed download link", "FAIL", f"could not use the link ({type(e).__name__})"))
        key2 = f"doctor/{uuid.uuid4()}.put.txt"
        created.append(key2)
        try:
            r = client.put(
                store.presign_put(key2, 120, "text/plain"), content=b"x", headers={"Content-Type": "text/plain"}
            )
            out.append(
                Check(
                    "r2",
                    "signed upload link",
                    "PASS" if r.status_code in (200, 201) and store.head(key2) else "FAIL",
                    "a pre-signed PUT link (what the GPU worker uses) writes the object"
                    if r.status_code in (200, 201)
                    else f"the link answered HTTP {r.status_code}",
                )
            )
        except (httpx.HTTPError, StorageError) as e:
            out.append(Check("r2", "signed upload link", "FAIL", f"could not use the link ({type(e).__name__})"))
        bare = url.split("?", 1)[0]
        try:
            r = client.get(bare)
            out.append(
                Check(
                    "r2",
                    "bucket is private",
                    "PASS" if r.status_code in (401, 403, 404) else "FAIL",
                    "the object cannot be fetched without a signature"
                    if r.status_code in (401, 403, 404)
                    else f"an unsigned request got HTTP {r.status_code}: the bucket is readable without a signature",
                    None
                    if r.status_code in (401, 403, 404)
                    else "Turn off public access / the r2.dev subdomain / any custom domain on this bucket.",
                )
            )
        except httpx.HTTPError as e:
            out.append(Check("r2", "bucket is private", "PARTIAL", f"could not test ({type(e).__name__})"))
        origin = origin or (s.origins[0] if s.origins else None)
        if not origin:
            out.append(
                Check(
                    "r2",
                    "CORS for the web app",
                    "PARTIAL",
                    "no web origin given",
                    "Run again with --origin http://localhost:3000 (or set ARO_ALLOWED_ORIGINS).",
                )
            )
        else:
            try:
                r = client.get(url, headers={"Origin": origin})
                allow = r.headers.get("access-control-allow-origin")
                good = allow in (origin, "*")
                out.append(
                    Check(
                        "r2",
                        "CORS for the web app",
                        "PASS" if good else "FAIL",
                        f"R2 allows the origin {origin}"
                        if good
                        else f"R2 did not allow the origin {origin} (answer: {allow or 'no CORS header'})",
                        None
                        if good
                        else "Bucket -> Settings -> CORS policy: allow your web origin, method GET, headers *.",
                    )
                )
            except httpx.HTTPError as e:
                out.append(Check("r2", "CORS for the web app", "PARTIAL", f"could not test ({type(e).__name__})"))
    finally:
        for k in created:
            try:
                store.delete(k)
            except StorageError:
                pass
    return out


# ======================================================================================================================== RunPod
def check_runpod(s: CloudSettings, *, http: httpx.Client | None = None) -> list[Check]:
    miss = _missing(
        s,
        "runpod",
        {"ARO_RUNPOD_API_KEY": bool(s.runpod_api_key), "ARO_RUNPOD_ENDPOINT_ID": bool(s.runpod_endpoint_id)},
    )
    if miss:
        return [miss]
    assert s.runpod_api_key and s.runpod_endpoint_id
    out = [Check("runpod", "configuration", "PASS", "API key and endpoint id are set")]
    url = f"{s.runpod_base_url.rstrip('/')}/{s.runpod_endpoint_id}/health"
    try:
        r = (http or httpx.Client(timeout=15)).get(
            url, headers={"Authorization": f"Bearer {s.runpod_api_key.get_secret_value()}"}
        )
    except httpx.HTTPError as e:
        return out + [Check("runpod", "endpoint health", "FAIL", f"could not reach RunPod ({type(e).__name__})")]
    if r.status_code in (401, 403):
        return out + [
            Check(
                "runpod",
                "endpoint health",
                "FAIL",
                f"RunPod rejected the API key (HTTP {r.status_code})",
                "Create a new API key in RunPod Settings -> API Keys.",
            )
        ]
    if r.status_code == 404:
        return out + [
            Check(
                "runpod",
                "endpoint health",
                "FAIL",
                "RunPod does not know this endpoint id",
                "Copy the id from the endpoint's page (Serverless -> your endpoint).",
            )
        ]
    if r.status_code != 200:
        return out + [Check("runpod", "endpoint health", "FAIL", f"RunPod answered HTTP {r.status_code}")]
    try:
        d = r.json()
    except ValueError:
        d = {}
    w, j = d.get("workers", {}), d.get("jobs", {})
    wtxt = ", ".join(f"{k} {v}" for k, v in w.items() if isinstance(v, int)) or "no worker counts"
    jtxt = ", ".join(f"{k} {v}" for k, v in j.items() if isinstance(v, int)) or "no job counts"
    return out + [
        Check(
            "runpod",
            "endpoint health",
            "PASS",
            f"the endpoint answers with this key. Workers: {wtxt}. Jobs: {jtxt}. (No job was submitted; zero workers is normal when scaled to zero.)",
        )
    ]


# ============================================================================================================================ CLI
def render(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        lines.append(f"{c.status:<8} [{c.area}] {c.name}: {c.detail}")
        if c.hint and c.status != "PASS":
            lines.append(f"{'':<8}   -> {c.hint}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("area", choices=["supabase", "r2", "runpod", "all"])
    ap.add_argument("--env-file", help="private file with ARO_* settings")
    ap.add_argument("--origin", help="the web app's origin, for the R2 CORS check (default: first ARO_ALLOWED_ORIGINS)")
    a = ap.parse_args(argv)
    load_env_file(a.env_file)
    s = CloudSettings()
    checks: list[Check] = []
    if a.area in ("supabase", "all"):
        checks += check_supabase(s)
    if a.area in ("r2", "all"):
        checks += check_r2(s, origin=a.origin)
    if a.area in ("runpod", "all"):
        checks += check_runpod(s)
    print(render(checks))
    failed = [c for c in checks if c.status == "FAIL"]
    print(
        "\nRESULT: "
        + (
            "FAIL (" + str(len(failed)) + " check(s) need fixing)"
            if failed
            else (
                "PASS"
                if all(c.status == "PASS" for c in checks)
                else "PARTIAL (nothing failed; read the PARTIAL lines)"
            )
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["Check", "check_r2", "check_runpod", "check_supabase", "main", "render"]
