# LOD pipeline

`lod/generator.py` builds LOD1…LODn from LOD0 (never modified). Default vehicle config: ratios 0.55 / 0.28 / 0.12 with Unity screen-height transitions 0.30 / 0.15 / 0.05 (LOD0 0.60); generic assets 0.5 / 0.25 / 0.1.

Per level: decimate each part (minimum faces per part), optionally **drop roles** (e.g. interior, wipers, mirrors at far LODs) and optionally **merge static parts by material** (LOD3). Animated roles (wheel, tire, door, mirror, wiper) are never merged, so steering/spin/doors still work at every LOD. `LodConfig.validate_monotonic` rejects ratios or screen heights that do not strictly decrease.

Achieved vs target ratio is reported (TITAN 480: 0.567 / 0.296 / 0.149 for 0.55 / 0.28 / 0.12 — primitives cannot be reduced below their minimum faces, and the report says so). Validation requires each level to be ≥ 10 % smaller than the previous.

In exports, LOD nodes are named `<Part>_LOD<n>` under the **shared** rig nodes, so one wheel-spin transform drives every LOD.
