# Validation and production readiness

`validation/engine.py` runs **46 explicit rules** (each individually tested). A rule returns `passed / failed / warning / skipped / not_applicable`; a crashing rule becomes a *failed check*, never a crashed validation. Only evaluated rules count towards scores (a flat-colour asset has no "textures %", it is shown as n/a — not faked as 100 %).

| Category (weight) | Rules |
|---|---|
| Geometry (20) | G001 mesh exists ★ · G002 readable/finite ★ · G003 no non-manifold edges · G004 no degenerate/duplicate triangles · G005 normals/winding · G006 triangle budget · G007 duplicate vertices (minor) · G008 closed parts (minor) · G009 floating fragments (minor) · G010 self-intersections (minor) |
| Materials (10) | M001 exist ★ · M002 every part has a valid material · M003 PBR values valid for the category · M004 unused (minor) · M005 vehicle categories covered (minor) |
| Textures (10) | T001 files exist ★ · T002 references resolve ★ · T003 formats decode · T004 power-of-two ≤ 4096 · T005 textured parts have UVs in 0..1 · T006 un-baked vertex colours (minor) |
| LOD (15) | L001 LOD0 ★ · L002–L004 LOD1–3 exist · L005 each LOD ≥ 10 % smaller · L006 LOD materials/wheels consistent (minor) · L007 near target ratio (minor) |
| Collision (10) | C001 exists ★(vehicles) · C002 convex ≤ 255 tris · C003 encloses the body · C004 separate from visuals ★ |
| Vehicle (20) | V001 spec ★ · V002 wheels ★ (drive config) · V003 axles ★ · V004 references valid · V005 pivots · V006 wheel positions · V007 axle/wheel alignment · V008 centre of mass · V009 attachments (tractor ⇒ fifth wheel) · V010 symmetry (minor) |
| Unity (15) | U001 scale ★ · U002 orientation ★ · U003 naming · U004 hierarchy · U005 materials map (minor) · U006 pivot at ground/centre · U007 dry-run GLB export + verification |

★ = critical. Others are *major* (weight 3) or *minor* (weight 1); critical = 5.

## Status logic

```
geometry unreadable (G001/G002)        → FAILED
any critical OR major failure           → NEEDS_REVIEW   (whatever the score)
overall score < 90 %                    → NEEDS_REVIEW
otherwise                               → PRODUCTION_READY  (eligible; a human still designates the version)
```

Category weights: geometry 20, materials 10, textures 10, LOD 15, collision 10, vehicle 20, Unity 15 (non-applicable categories are excluded). Warnings give 60 % credit.

## Proof that scores don't override failures

`tests/test_export_validation.py::test_critical_or_blocking_failure_prevents_production_ready_even_with_high_score` removes wheels / axles / collision / materials / LODs or rescales ×100 on the reference vehicle: the overall score stays > 70 % (often > 90 %) and the status is still `NEEDS_REVIEW` with the blocking reason listed.

## Where results go

`validation_results` (full JSON report), the Validation page, the Studio inspector, and the Unity package (`Metadata/validation_report.json`, README). Validation is per **version**; any change creates a new version that must be re-validated before it can be designated the production version.
