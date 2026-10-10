# System architecture

```
Browser (static SPA, three.js viewer)
   │  HTTPS, JSON, Bearer token (optional)
   ▼
FastAPI app ── middleware: auth → rate limit → security headers → error translation
   │                                      
   ├── services (projects, assets, sources, exports, validation)   ── SQLite (WAL) + data/ directory
   ├── JobQueue ── worker thread(s) ── handlers: generation | processing | export | cleanup
   │                                     │
   │                                     ├── GenerationService ── ModelManager ── ImageTo3DEngine (TripoSR)
   │                                     └── ProcessingService ── geometry/materials/textures/vehicle/collision/lod/rig
   └── static files (UI + vendored three.js)
```

## Threads and processes

* One uvicorn process. HTTP handlers are short; anything long becomes a **job**.
* `ARO_WORKERS` worker threads (default 1: free GPUs are small and shared). The `ModelManager` lock additionally serialises model use.
* UV unwrapping (native `xatlas`) runs in a **child process** with a timeout — it was observed to segfault on an 82k-face mesh, and a native crash must never take down the Studio.
* Cancellation is cooperative (`CancellationToken.check()` between steps); timeouts use the same token. A job blocked in native code cannot be pre-empted — only xatlas has a hard (subprocess) timeout.

## API surface (`/api`, OpenAPI at `/api/docs`)

| Area | Endpoints |
|---|---|
| System | `GET /health` (no auth), `/system`, `/taxonomy`, `/audit`, `POST /maintenance/cleanup`, `/models/unload` |
| Projects | CRUD, `archive`, `restore`, `duplicate`, `history`, `archive.zip`, soft/permanent delete |
| Sources | `POST /projects/{id}/sources` (validated upload), image + `preprocessed.png` preview |
| Assets/versions | CRUD, `status`, `versions`, `preview.glb`, `inspect`, `reports/{name}`, `designate-production`, mesh `import`, `reference/titan480` |
| Generation | `GET /engines`, `GET /models`, `POST /assets/{id}/generate`, `GET /generations` |
| Processing | `POST /versions/{id}/process` (`geometry`, `materials`, `textures`, `vehicle`, `collision`, `lod`, `rig`, `finalize`, `validate`) |
| Export | `POST /versions/{id}/export`, `GET /exports`, `/exports/{id}/download` |
| Jobs | list/get, `events`, `cancel`, `requeue`, SSE `stream` |

Errors are always `{"error": {"code", "message", "recommended_action", "details"}}`; tracebacks never reach the client.

## Security architecture

* **Uploads:** magic-byte sniffing (extension and MIME are ignored), size limits enforced while streaming, pixel limit, decode-validated, stored under the SHA-256 of their content. Filenames are sanitised for *display only*; paths come from validated ids.
* **Paths:** every filesystem path is built by `safe_join` (rejects absolute paths, `..`, NULs, symlink escapes); ids are regex-validated before use.
* **Archives:** every member is validated before extraction (traversal, absolute, symlinks, encryption, member count, total size, compression ratio).
* **No code execution from uploads:** `.npz` is loaded with `allow_pickle=False`; meshes are parsed by trimesh as data; no `eval`.
* **Auth:** optional single shared Bearer token (`ARO_ACCESS_TOKEN`, constant-time compare). This is intentionally minimal — there are no user accounts yet.
* **Abuse limits:** sliding-window rate limits (general + heavy endpoints), job timeouts, resource preflight, disk/RAM checks.
* **Headers:** CSP (`script-src 'self'`), `nosniff`, `no-referrer`, `frame-ancestors` for Hugging Face embedding, `no-store` on API responses.
* **Secrets:** environment only; log redaction for bearer tokens, `hf_…` tokens and `password=`/`token=` pairs; the settings endpoint never returns secrets.
* **Audit log:** project/asset/version/export actions are recorded in SQLite (`audit_log`).

## Observability

JSON logs (`app.log`, `error.log`, rotating), per-job event log, timing metrics, resource snapshots at job start/end, model load/unload events, validation and export reports persisted with the data. `/api/system` exposes it all.
