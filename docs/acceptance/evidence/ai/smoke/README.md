# Real-inference smoke evidence — one complete four-image run (PASS), visual review PENDING

`smoke-evidence.json` is the unmodified output of `scripts/real_inference_smoke.py` from a Colab Tesla T4 run on **2026-10-26** at Studio
commit `92570513` (real TripoSR `stabilityai/TripoSR@5b521936…`, licence verified, `transformers` 4.46.3, u2net matting). Four different
images went through the real engine and the Studio path (preview → automatic preparation → validation → verified GLB export):

| Item | Category | Raw triangles | Result |
|---|---|---|---|
| ARO 480 Truck at Golden Hour (owner image) | heavy_truck | 176,628 | PASS |
| Chair (TripoSR example) | furniture | 82,833 | PASS |
| Teapot (TripoSR example) | household_object | 83,476 | PASS |
| Toy robot (TripoSR example) | equipment | 158,779 | PASS |

`aro_studio.verification.evidence.read_smoke_evidence` returns **PASS** for it. Checked independently of Colab: all four raw meshes
(`raw_mesh_file`) have the SHA-256 recorded as `output_sha256`; the prepared GLBs of the teapot and the robot match `export.sha256_download`,
pass the per-node audit and the Khronos validator (0 errors, 0 warnings); inputs of chair/teapot/robot equal the SHA-256 pins; four distinct
inputs gave four distinct raw outputs; no cache hit; invalid-file probe PASS.

## What this does NOT say
* **Visual quality is PENDING_HUMAN_REVIEW** for every item; `production_ready` is `NOT_CLAIMED`.
* **The sizes are 1 m placeholders** (a single image cannot give the real size). The `PRODUCTION_READY (99.6 %)` labels the Studio's
  validator printed for the chair, teapot and robot in this run came from a validator that did not know the size was assumed; that was a
  bug, fixed afterwards (rule `U008`: an assumed size now yields NEEDS_REVIEW). The JSON is left exactly as recorded.
* The truck is NEEDS_REVIEW (75.3 %): vehicle metadata is missing (artist work) and the size is a placeholder.

## What is in this directory, and what is not
In git: `smoke-evidence.json`, `smoke-report.md`. **Not in git yet:** the repo zip's `inputs/`, `views/` and the prepared GLBs of the truck
and chair (not received), the raw meshes (3.5 MB each at most; kept out of git by design, hashes above). Add the prepared GLBs and views
from `smoke-evidence-repo.zip` to complete the package.
