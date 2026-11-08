"""ARO 3D AI STUDIO cloud platform: authenticated multi-user API, job orchestration, credits, storage and GPU-provider integration.

Layout (docs/cto/04-architecture.md):

* ``settings``      environment configuration, validated at start-up
* ``db``/``migrate`` PostgreSQL access (Supabase) and the SQL migrations in ``migrations/``
* ``auth``          Supabase JWT verification
* ``storage``       Cloudflare R2 (S3 API): validated writes, pre-signed reads
* ``providers``     GPU providers behind one contract (RunPod Serverless)
* ``orchestrator``  job state machine, idempotency, credit reservation/capture/release, reconciliation
* ``output_gate``   a provider's output is only accepted after the GLB itself has been validated
* ``api``           the FastAPI application the web app talks to

The existing ``aro_studio`` package is the processing library (geometry, textures, validation); ``aro_worker`` holds the GPU worker.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
