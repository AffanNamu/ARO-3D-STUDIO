# Security policy

## Reporting a vulnerability

Please report privately to the project owner (ARO Motors) rather than opening a public issue. Include steps to reproduce, affected version and impact. We aim to acknowledge within a few days.

## What the Studio does (and does not) protect against

Implemented and tested (`tests/test_security.py`, `tests/test_api_integration.py`):

* upload validation by **content** (magic bytes), streamed size limits, pixel limits, decode validation;
* filename sanitisation; storage paths derived from validated ids only; path-traversal and symlink-escape guard (`safe_join`);
* safe zip extraction (traversal, absolute paths, symlinks, encryption, member-count/size/compression-ratio limits);
* no unpickling of stored data (`allow_pickle=False`); no code execution from uploaded files;
* optional Bearer-token access control (constant-time compare), sliding-window rate limiting, job timeouts, resource preflight;
* CSP, `nosniff`, `no-referrer`, `no-store`; error responses never contain tracebacks; log redaction of tokens/passwords;
* audit log of destructive/security-relevant actions; secrets only from environment variables.

Known limitations (be aware before exposing publicly):

* Access control is a **single shared token**, not per-user accounts or roles.
* Rate limits are in-process and keyed by client address/token.
* Native libraries (xatlas, trimesh parsers, Pillow) process untrusted files: xatlas is isolated in a subprocess; keep dependencies updated (CI runs `pip-audit` and `bandit`).
* The Unity importer script and Unity package are generated artefacts that run inside your Unity Editor: review them before use.
* AI model weights are third-party; verify licences (see `docs/models/model-licenses.md`).

## Secrets

Never commit tokens, Hugging Face access tokens, passwords, private keys or cloud credentials. Use `.env` locally (git-ignored) and Space/host secrets in deployment. `.env.example` contains no secrets.
