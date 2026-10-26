"""Validation engine and production-readiness report (spec §24-25, §43).

Rules are explicit, individually testable functions. Every rule returns PASSED / FAILED / WARNING /
SKIPPED / NOT_APPLICABLE; only rules that were actually evaluated count towards a score. Scores NEVER
override critical failures: any failed critical rule makes the asset NEEDS_REVIEW regardless of percentage.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from aro_studio.assets.taxonomy import get_category
from aro_studio.core.enums import AssetStatus, CheckStatus, Severity
from aro_studio.core.tm import has_vertex_colors
from aro_studio.geometry.inspect import inspect_mesh
from aro_studio.materials.library import check_pbr
from aro_studio.scene.model import ColliderKind
from aro_studio.scene.store import Scene
from aro_studio.textures.process import is_power_of_two

CATEGORY_WEIGHTS = {
    "geometry": 20,
    "materials": 10,
    "textures": 10,
    "lod": 15,
    "collision": 10,
    "vehicle": 20,
    "unity": 15,
}
SEVERITY_WEIGHT = {Severity.CRITICAL: 5, Severity.MAJOR: 3, Severity.MINOR: 1, Severity.INFO: 0}
READY_THRESHOLD = 90.0
UNITY_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
ALLOWED_TEX_RES = (512, 1024, 2048, 4096)
MAX_CONVEX_TRIS = 255


@dataclass
class ValidationConfig:
    tri_budget_lod0: int = 150_000
    check_intersections: bool = True
    intersection_budget_s: float = 8.0
    required_lods: int = 3  # LOD levels above 0 that must exist for vehicles
    min_lod_reduction: float = 0.10  # each LOD must have >=10% fewer triangles than the previous
    ready_threshold: float = READY_THRESHOLD
    # None = nobody asserted anything (an authored asset); False = the size is an ASSUMED placeholder (e.g. an AI reconstruction whose real
    # size nobody supplied); True = a person confirmed the real-world size.
    size_confirmed: bool | None = None


@dataclass
class CheckResult:
    id: str
    category: str
    title: str
    severity: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Ctx:
    scene: Scene
    config: ValidationConfig
    category_id: str
    is_vehicle: bool
    group: str
    part_reports: dict[str, Any] = field(default_factory=dict)
    dry_export: dict[str, Any] | None = None


Rule = Callable[[Ctx], CheckResult]
RULES: list[tuple[str, str, Severity, str, Rule]] = []


def rule(rid: str, category: str, severity: Severity, title: str):
    def deco(fn: Callable[[Ctx], tuple[CheckStatus, str, dict] | tuple[CheckStatus, str]]):
        def run(ctx: Ctx) -> CheckResult:
            try:
                out = fn(ctx)
                status, msg = out[0], out[1]
                details = out[2] if len(out) > 2 else {}
            except Exception as e:  # noqa: BLE001 - a crashing rule is a failed check, never a crashed validation
                status, msg, details = CheckStatus.FAILED, f"Rule raised {type(e).__name__}: {e}", {}
            return CheckResult(rid, category, title, severity.value, status.value, msg, details)

        RULES.append((rid, category, severity, title, run))
        return fn

    return deco


P, F, W, S, NA = (
    CheckStatus.PASSED,
    CheckStatus.FAILED,
    CheckStatus.WARNING,
    CheckStatus.SKIPPED,
    CheckStatus.NOT_APPLICABLE,
)


def _parts_inspected(ctx: Ctx) -> dict[str, Any]:
    if not ctx.part_reports:
        for name, m in ctx.scene.meshes.items():
            ctx.part_reports[name] = inspect_mesh(
                m,
                category_group=None,
                tri_budget=None,
                check_intersections=ctx.config.check_intersections,
                intersection_budget_s=ctx.config.intersection_budget_s / max(1, len(ctx.scene.meshes)),
            )
    return ctx.part_reports


# ================= GEOMETRY =======================================================================
@rule("G001", "geometry", Severity.CRITICAL, "Mesh exists")
def g001(c: Ctx):
    n = c.scene.triangle_count
    return (P, f"{len(c.scene.meshes)} part(s), {n:,} triangles") if n > 0 else (F, "The asset has no triangles.")


@rule("G002", "geometry", Severity.CRITICAL, "Mesh is readable and finite")
def g002(c: Ctx):
    bad = [
        n
        for n, m in c.scene.meshes.items()
        if not np.isfinite(np.asarray(m.vertices)).all()
        or (len(m.faces) and (np.asarray(m.faces).max() >= len(m.vertices)))
    ]
    return (P, "all vertex data finite and indices valid") if not bad else (F, f"corrupt geometry in: {bad[:5]}")


@rule("G003", "geometry", Severity.MAJOR, "Topology is valid (no non-manifold edges)")
def g003(c: Ctx):
    bad = {n: r.nonmanifold_edges for n, r in _parts_inspected(c).items() if r.nonmanifold_edges}
    return (
        (P, "no non-manifold edges")
        if not bad
        else (F, f"non-manifold edges in {len(bad)} part(s)", {"parts": dict(list(bad.items())[:10])})
    )


@rule("G004", "geometry", Severity.MAJOR, "No degenerate or duplicate triangles")
def g004(c: Ctx):
    bad = {
        n: (r.degenerate_faces, r.duplicate_faces)
        for n, r in _parts_inspected(c).items()
        if r.degenerate_faces or r.duplicate_faces
    }
    return (
        (P, "no degenerate/duplicate triangles")
        if not bad
        else (F, f"degenerate/duplicate triangles in {len(bad)} part(s)", {"parts": dict(list(bad.items())[:10])})
    )


@rule("G005", "geometry", Severity.MAJOR, "Normals are valid and winding consistent")
def g005(c: Ctx):
    bad = [n for n, r in _parts_inspected(c).items() if r.invalid_normals or not r.is_winding_consistent or r.inverted]
    return (
        (P, "normals valid, winding consistent, no inverted parts")
        if not bad
        else (F, f"invalid/inconsistent normals in: {bad[:6]}")
    )


@rule("G006", "geometry", Severity.MAJOR, "Triangle count within budget")
def g006(c: Ctx):
    n, b = c.scene.triangle_count, c.config.tri_budget_lod0
    return (
        (P, f"{n:,} ≤ {b:,}")
        if n <= b
        else (F, f"{n:,} triangles exceed the LOD0 budget of {b:,}", {"triangles": n, "budget": b})
    )


@rule("G007", "geometry", Severity.MINOR, "No duplicate vertices")
def g007(c: Ctx):
    n = sum(r.duplicate_vertices for r in _parts_inspected(c).values())
    return (P, "no duplicate vertices") if n == 0 else (W, f"{n} duplicate vertices (weld them)")


@rule("G008", "geometry", Severity.MINOR, "Parts are closed (no holes)")
def g008(c: Ctx):
    bad = {n: r.hole_count for n, r in _parts_inspected(c).items() if r.hole_count}
    return (
        (P, "all parts are closed")
        if not bad
        else (
            W,
            f"open boundaries in {len(bad)} part(s) (may be intentional for thin shells)",
            {"parts": dict(list(bad.items())[:10])},
        )
    )


@rule("G009", "geometry", Severity.MINOR, "No floating fragments")
def g009(c: Ctx):
    bad = {n: r.small_component_count for n, r in _parts_inspected(c).items() if r.small_component_count}
    return (P, "no tiny floating components") if not bad else (W, f"tiny disconnected fragments in {len(bad)} part(s)")


@rule("G010", "geometry", Severity.MINOR, "No self-intersections")
def g010(c: Ctx):
    reps = _parts_inspected(c).values()
    pairs = sum(r.self_intersections["intersecting_pairs"] for r in reps)
    unchecked = [r for r in reps if r.self_intersections["status"] != "checked"]
    if unchecked and not pairs:
        return S, f"{len(unchecked)} part(s) were not fully checked (size/time budget)"
    return (
        (P, "no self-intersections found (coplanar overlaps are not detectable)")
        if not pairs
        else (W, f"{pairs} intersecting triangle pairs")
    )


# ================= MATERIALS ======================================================================
@rule("M001", "materials", Severity.CRITICAL, "Materials exist")
def m001(c: Ctx):
    return (
        (P, f"{len(c.scene.manifest.materials)} material(s)")
        if c.scene.manifest.materials
        else (F, "The asset has no materials.")
    )


@rule("M002", "materials", Severity.MAJOR, "Every part has a valid material")
def m002(c: Ctx):
    man = c.scene.manifest
    names = {m.name for m in man.materials}
    bad = [p.name for p in man.parts if not p.material or p.material not in names]
    return (
        (P, "all parts have a valid material")
        if not bad
        else (F, f"{len(bad)} part(s) without a valid material: {bad[:6]}")
    )


@rule("M003", "materials", Severity.MAJOR, "PBR channels are valid")
def m003(c: Ctx):
    probs = {m.name: check_pbr(m) for m in c.scene.manifest.materials}
    probs = {k: v for k, v in probs.items() if v}
    return (
        (P, "all PBR values valid for their category")
        if not probs
        else (F, f"PBR problems in {len(probs)} material(s)", {"problems": probs})
    )


@rule("M004", "materials", Severity.MINOR, "No unused materials")
def m004(c: Ctx):
    man = c.scene.manifest
    used = {p.material for p in man.parts} | {p.material for lod in man.lods for p in lod.parts}
    un = [m.name for m in man.materials if m.name not in used]
    return (P, "no unused materials") if not un else (W, f"unused materials: {un}")


@rule("M005", "materials", Severity.MINOR, "Vehicle material categories covered")
def m005(c: Ctx):
    if not c.is_vehicle:
        return NA, "not a vehicle"
    cats = {m.category.value for m in c.scene.manifest.materials}
    need = {"paint", "glass", "rubber"}
    miss = need - cats
    return (P, "paint, glass and rubber present") if not miss else (W, f"missing categories: {sorted(miss)}")


# ================= TEXTURES =======================================================================
def _has_tex(c: Ctx) -> bool:
    return bool(c.scene.manifest.textures) or any(m.textures for m in c.scene.manifest.materials)


@rule("T001", "textures", Severity.CRITICAL, "Texture files exist")
def t001(c: Ctx):
    if not _has_tex(c):
        return NA, "asset uses flat-colour materials (no textures)"
    miss = [t.file for t in c.scene.manifest.textures if t.file not in c.scene.texture_data]
    return (
        (P, f"{len(c.scene.manifest.textures)} texture file(s) present")
        if not miss
        else (F, f"missing texture files: {miss[:5]}")
    )


@rule("T002", "textures", Severity.CRITICAL, "Texture references are valid")
def t002(c: Ctx):
    if not _has_tex(c):
        return NA, "no textures"
    man = c.scene.manifest
    bad = [(m.name, ch, tn) for m in man.materials for ch, tn in m.textures.items() if man.texture(tn) is None]
    return (P, "all material texture references resolve") if not bad else (F, f"dangling references: {bad[:5]}")


@rule("T003", "textures", Severity.MAJOR, "Texture formats are valid")
def t003(c: Ctx):
    if not _has_tex(c):
        return NA, "no textures"
    from aro_studio.textures.process import open_image

    bad = []
    for t in c.scene.manifest.textures:
        try:
            im = open_image(c.scene.texture_data[t.file])
            if (im.width, im.height) != (t.width, t.height) or im.format not in ("PNG", "JPEG"):
                bad.append(t.name)
        except Exception:  # noqa: BLE001
            bad.append(t.name)
    return (P, "all textures decode as PNG/JPEG with declared size") if not bad else (F, f"invalid textures: {bad}")


@rule("T004", "textures", Severity.MAJOR, "Texture resolutions are valid")
def t004(c: Ctx):
    if not _has_tex(c):
        return NA, "no textures"
    bad = [
        f"{t.name} {t.width}x{t.height}"
        for t in c.scene.manifest.textures
        if not (
            is_power_of_two(t.width) and is_power_of_two(t.height) and max(t.width, t.height) <= max(ALLOWED_TEX_RES)
        )
    ]
    return (P, "power-of-two, ≤ 4096") if not bad else (F, f"invalid resolutions: {bad}")


@rule("T005", "textures", Severity.MAJOR, "Textured parts have in-range UVs")
def t005(c: Ctx):
    man = c.scene.manifest
    tex_mats = {m.name for m in man.materials if m.textures.get("base_color") or m.textures.get("normal")}
    if not tex_mats:
        return NA, "no textured materials"
    bad = []
    for p in man.parts:
        if p.material in tex_mats:
            uv = getattr(c.scene.meshes[p.name].visual, "uv", None)
            if uv is None or not np.isfinite(uv).all() or uv.min() < -1e-4 or uv.max() > 1 + 1e-4:
                bad.append(p.name)
    return (P, "UVs present and within 0..1") if not bad else (F, f"missing/out-of-range UVs: {bad[:6]}")


@rule("T006", "textures", Severity.MINOR, "Vertex colours are baked to textures")
def t006(c: Ctx):
    vc = [p.name for p in c.scene.manifest.parts if has_vertex_colors(c.scene.meshes[p.name])]
    if not vc:
        return NA, "no vertex-colour parts"
    return (W, f"{len(vc)} part(s) rely on vertex colours; Unity Lit shaders ignore them - bake to a texture")


# ================= LOD ============================================================================
@rule("L001", "lod", Severity.CRITICAL, "LOD0 exists")
def l001(c: Ctx):
    return (P, "LOD0 present") if c.scene.meshes else (F, "no LOD0 geometry")


def _lod_level(c: Ctx, lv: int):
    return next((lod for lod in c.scene.manifest.lods if lod.level == lv), None)


for _lv, _sev in ((1, Severity.MAJOR), (2, Severity.MAJOR), (3, Severity.MAJOR)):

    def _mk(lv: int, sev: Severity):
        @rule(f"L00{lv + 1}", "lod", sev, f"LOD{lv} exists")
        def lx(c: Ctx):
            if not c.is_vehicle and lv >= c.config.required_lods + 1:
                return NA, "not required"
            if lv > c.config.required_lods and not c.is_vehicle:
                return NA, "not required"
            return (
                (P, f"LOD{lv}: {_lod_level(c, lv).triangle_count:,} triangles")
                if _lod_level(c, lv)
                else ((F if c.is_vehicle or lv <= 2 else W), f"LOD{lv} is missing")
            )

    _mk(_lv, _sev)


@rule("L005", "lod", Severity.MAJOR, "LOD complexity decreases")
def l005(c: Ctx):
    lods = sorted(c.scene.manifest.lods, key=lambda x: x.level)
    if not lods:
        return S, "no LODs to compare"
    seq = [c.scene.triangle_count] + [lod.triangle_count for lod in lods]
    bad = [
        f"LOD{i}→LOD{i + 1}: {seq[i]:,}→{seq[i + 1]:,}"
        for i in range(len(seq) - 1)
        if seq[i + 1] > seq[i] * (1 - c.config.min_lod_reduction)
    ]
    return (
        (P, "triangles " + " > ".join(f"{x:,}" for x in seq), {"triangles": seq})
        if not bad
        else (F, "insufficient reduction: " + "; ".join(bad), {"triangles": seq})
    )


@rule("L006", "lod", Severity.MINOR, "LOD materials and parts are consistent")
def l006(c: Ctx):
    man = c.scene.manifest
    names = {m.name for m in man.materials}
    bad = [f"LOD{lod.level}:{p.name}" for lod in man.lods for p in lod.parts if p.material and p.material not in names]
    anim_missing = []
    for lod in man.lods:
        have = {p.name for p in lod.parts}
        anim_missing += [
            f"LOD{lod.level}:{p.name}"
            for p in man.parts
            if p.component in ("wheel", "wheel_detail", "tire") and p.name not in have
        ]
    if not man.lods:
        return S, "no LODs"
    return (
        (P, "LOD parts reference valid materials; wheels present at every LOD")
        if not (bad or anim_missing)
        else (W, f"issues: {(bad + anim_missing)[:6]}")
    )


@rule("L007", "lod", Severity.MINOR, "LOD reduction close to target")
def l007(c: Ctx):
    base = max(c.scene.triangle_count, 1)
    off = [
        f"LOD{lod.level}: {lod.triangle_count / base:.2f} vs target {lod.target_ratio}"
        for lod in c.scene.manifest.lods
        if lod.triangle_count / base > lod.target_ratio * 1.5 + 0.02
    ]
    if not c.scene.manifest.lods:
        return S, "no LODs"
    return (P, "within tolerance of targets") if not off else (W, "; ".join(off))


# ================= COLLISION ======================================================================
@rule("C001", "collision", Severity.CRITICAL, "Collision exists")
def c001(c: Ctx):
    n = len(c.scene.manifest.colliders)
    if n:
        return P, f"{n} collider(s)"
    return (F, "no collision geometry") if c.is_vehicle else (W, "no collision geometry")


@rule("C002", "collision", Severity.MAJOR, "Collision is optimised for runtime")
def c002(c: Ctx):
    cols = c.scene.manifest.colliders
    if not cols:
        return S, "no colliders"
    bad = [
        f"{x.name}:{x.triangle_count}"
        for x in cols
        if x.kind in (ColliderKind.CONVEX_HULL, ColliderKind.VEHICLE_MESH) and x.triangle_count > MAX_CONVEX_TRIS
    ]
    return (
        (P, f"convex colliders ≤ {MAX_CONVEX_TRIS} triangles") if not bad else (F, f"convex colliders too dense: {bad}")
    )


@rule("C003", "collision", Severity.MAJOR, "Collision encloses the visual body")
def c003(c: Ctx):
    cols = c.scene.manifest.colliders
    if not cols:
        return S, "no colliders"
    vis = np.array([m.bounds for m in c.scene.meshes.values()])
    lo, hi = vis[:, 0].min(axis=0), vis[:, 1].max(axis=0)
    ext = hi - lo
    mlo, mhi = [], []
    for col in cols:
        if col.purpose == "wheel":
            continue
        if col.name in c.scene.collision_meshes:
            b = c.scene.collision_meshes[col.name].bounds
            mlo.append(b[0])
            mhi.append(b[1])  # noqa: E702
        elif col.kind is ColliderKind.BOX and col.size:
            mlo.append(np.array(col.center) - np.array(col.size) / 2)
            mhi.append(np.array(col.center) + np.array(col.size) / 2)  # noqa: E702
        elif col.radius:
            r = col.radius
            mlo.append(np.array(col.center) - r)
            mhi.append(np.array(col.center) + r)  # noqa: E702
    if not mlo:
        return S, "no body colliders to compare"
    clo, chi = np.min(mlo, axis=0), np.max(mhi, axis=0)
    # collision must cover the main mass: it should sit inside the visual bounds (+10%) and span ≥ 50% of each axis
    inside = np.all(clo >= lo - 0.1 * ext) and np.all(chi <= hi + 0.1 * ext)
    cover = np.all((chi - clo) >= 0.5 * ext)
    return (
        (P, "collision bounds are consistent with the visual bounds")
        if inside and cover
        else (
            F,
            "collision bounds do not match the visual body",
            {"collision": [clo.tolist(), chi.tolist()], "visual": [lo.tolist(), hi.tolist()]},
        )
    )


@rule("C004", "collision", Severity.CRITICAL, "Collision is separate from visual geometry")
def c004(c: Ctx):
    names = [p.name for p in c.scene.manifest.parts]
    bad = [n for n in names if n.upper().startswith(("COL_", "UCX_", "UBX_"))]
    return (
        (P, "visual parts contain no collision meshes")
        if not bad
        else (F, f"collision-named parts in visual set: {bad}")
    )


# ================= VEHICLE ========================================================================
def _veh(c: Ctx, fn):
    if not c.is_vehicle:
        return NA, "not a vehicle"
    if c.scene.manifest.vehicle is None:
        return F, "vehicle metadata is missing (configure the vehicle)"
    return fn(c.scene.manifest.vehicle)


@rule("V001", "vehicle", Severity.CRITICAL, "Vehicle metadata exists")
def v001(c: Ctx):
    if not c.is_vehicle:
        return NA, "not a vehicle"
    return (P, "vehicle spec present") if c.scene.manifest.vehicle else (F, "vehicle metadata is missing")


@rule("V002", "vehicle", Severity.CRITICAL, "Wheels exist")
def v002(c: Ctx):
    def f(v):
        if not v.wheels:
            return F, "no wheels defined"
        m = re.match(r"^(\d+)x(\d+)$", v.identity.drive_configuration or "")
        if m:
            positions = int(m.group(1))
            axles = positions // 2
            if len(v.axles) < axles:
                return F, f"{v.identity.drive_configuration} implies ≥ {axles} axles, found {len(v.axles)}"
            if len(v.wheels) < positions:
                return (
                    F,
                    f"{v.identity.drive_configuration} implies ≥ {positions} wheel positions, found {len(v.wheels)}",
                )
        return P, f"{len(v.wheels)} wheels"

    return _veh(c, f)


@rule("V003", "vehicle", Severity.CRITICAL, "Axles exist")
def v003(c: Ctx):
    return _veh(c, lambda v: (P, f"{len(v.axles)} axles") if v.axles else (F, "no axles defined"))


@rule("V004", "vehicle", Severity.MAJOR, "Wheels reference axles and parts")
def v004(c: Ctx):
    def f(v):
        ax = {a.name for a in v.axles}
        parts = {p.name for p in c.scene.manifest.parts}
        bad = [
            w.name
            for w in v.wheels
            if (
                w.axle not in ax
                or (w.part and w.part not in parts)
                or (w.tire_part and w.tire_part not in parts)
                or any(detail not in parts for detail in w.detail_parts)
            )
        ]
        return (
            (P, "all wheels reference an axle and existing parts")
            if not bad
            else (F, f"broken wheel references: {bad[:6]}")
        )

    return _veh(c, f)


@rule("V005", "vehicle", Severity.MAJOR, "Pivots exist for articulated parts")
def v005(c: Ctx):
    def f(v):
        parts = {p.name: p for p in c.scene.manifest.parts}
        need = [n for n, p in parts.items() if p.component in ("door", "mirror") and n.startswith(("Door_", "Mirror_"))]
        piv = {pv.part for pv in v.pivots}
        miss = [n for n in need if n not in piv]
        bad = [pv.name for pv in v.pivots if pv.part and pv.part not in parts]
        if not need and not v.pivots:
            return W, "no doors/mirrors/pivots defined"
        return (
            (P, f"{len(v.pivots)} pivots cover doors and mirrors")
            if not (miss or bad)
            else (F, f"missing pivots for {miss}; dangling pivots {bad}")
        )

    return _veh(c, f)


@rule("V006", "vehicle", Severity.MAJOR, "Wheel positions are consistent")
def v006(c: Ctx):
    def f(v):
        bad = [
            f"{w.name}: y={w.position[1]:.3f} vs r={w.radius:.3f}"
            for w in v.wheels
            if abs(w.position[1] - w.radius) > 0.03
        ]
        # tyre part bounds should agree with declared radius
        for w in v.wheels:
            m = c.scene.meshes.get(w.tire_part or "")
            if m is not None and abs(m.extents[1] / 2 - w.radius) > 0.03:
                bad.append(f"{w.name}: tyre mesh radius {m.extents[1] / 2:.3f} vs declared {w.radius:.3f}")
        return (
            (P, "wheel centres sit one radius above the ground; tyre meshes match declared radius")
            if not bad
            else (F, "; ".join(bad[:5]))
        )

    return _veh(c, f)


@rule("V007", "vehicle", Severity.MAJOR, "Axle positions match their wheels")
def v007(c: Ctx):
    def f(v):
        bad = []
        for a in v.axles:
            ws = [w for w in v.wheels if w.axle == a.name]
            if not ws:
                bad.append(f"{a.name}: no wheels")
                continue
            if any(abs(w.position[2] - a.position[2]) > 0.02 for w in ws):
                bad.append(f"{a.name}: wheel z differs from axle z")
        return (P, "axles line up with their wheels") if not bad else (F, "; ".join(bad))

    return _veh(c, f)


@rule("V008", "vehicle", Severity.MAJOR, "Centre of mass is plausible")
def v008(c: Ctx):
    def f(v):
        if v.center_of_mass is None:
            return F, "centre of mass is not set"
        zs = [a.position[2] for a in v.axles]
        com = np.array(v.center_of_mass)
        lo, hi = (
            np.min([m.bounds[0] for m in c.scene.meshes.values()], axis=0),
            np.max([m.bounds[1] for m in c.scene.meshes.values()], axis=0),
        )
        ok = np.all(com >= lo) and np.all(com <= hi) and (min(zs) <= com[2] <= max(zs)) and com[1] > 0
        return (
            (P, "centre of mass lies inside the body, between the outer axles")
            if ok
            else (F, f"centre of mass {com.round(2).tolist()} is outside the body / axle span")
        )

    return _veh(c, f)


@rule("V009", "vehicle", Severity.MAJOR, "Attachment points are valid")
def v009(c: Ctx):
    def f(v):
        lo = np.min([m.bounds[0] for m in c.scene.meshes.values()], axis=0) - 0.5
        hi = np.max([m.bounds[1] for m in c.scene.meshes.values()], axis=0) + 0.5
        span = hi - lo
        bad = []
        for a in v.attachment_points:
            pos = np.array(a.position)
            if not np.isfinite(pos).all():
                bad.append(a.name)
            elif a.kind == "camera":  # virtual points (chase camera) legitimately sit outside the body
                if not (np.all(pos >= lo - 2 * span) and np.all(pos <= hi + 2 * span)):
                    bad.append(a.name)
            elif not (np.all(pos >= lo) and np.all(pos <= hi)):
                bad.append(a.name)
        names = [a.name for a in v.attachment_points]
        dup = len(names) != len(set(names))
        tractor = (v.identity.body_type or "") == "tractor_unit"
        if tractor and not any(a.kind == "fifth_wheel" for a in v.attachment_points):
            return F, "tractor unit has no fifth-wheel attachment point"
        return (
            (P, f"{len(names)} attachment points valid")
            if not (bad or dup)
            else (F, f"invalid attachment points: {bad}{' (duplicate names)' if dup else ''}")
        )

    return _veh(c, f)


@rule("V010", "vehicle", Severity.MINOR, "Wheels are left/right symmetric")
def v010(c: Ctx):
    def f(v):
        bad = []
        for a in v.axles:
            L = sorted(w.position[0] for w in v.wheels if w.axle == a.name and w.side == "left")
            R = sorted(-w.position[0] for w in v.wheels if w.axle == a.name and w.side == "right")
            if len(L) != len(R) or any(abs(x - y) > 0.03 for x, y in zip(L, R, strict=False)):
                bad.append(a.name)
        return (P, "symmetric about the centreline") if not bad else (W, f"asymmetric axles: {bad}")

    return _veh(c, f)


# ================= UNITY ==========================================================================
@rule("U001", "unity", Severity.CRITICAL, "Scale is valid (metres)")
def u001(c: Ctx):
    lo = np.min([m.bounds[0] for m in c.scene.meshes.values()], axis=0)
    hi = np.max([m.bounds[1] for m in c.scene.meshes.values()], axis=0)
    ext = hi - lo
    if c.is_vehicle:
        L = float(ext[2])
        return (
            (P, f"vehicle length {L:.2f} m")
            if 2.0 <= L <= 25.0
            else (F, f"vehicle length {L:.3f} m is outside 2–25 m (is the unit wrong?)")
        )
    longest = float(ext.max())
    return (
        (P, f"largest extent {longest:.2f} m")
        if 0.01 <= longest <= 500
        else (F, f"largest extent {longest:.4f} m is implausible")
    )


@rule("U008", "unity", Severity.MAJOR, "Real-world size is confirmed")
def u008(c: Ctx):
    if c.config.size_confirmed is None:
        return NA, "no claim about the size was made for this asset"
    if c.config.size_confirmed:
        return P, "the real-world size was supplied by a person"
    return F, (
        "the size is an ASSUMED placeholder (a single image cannot tell the real size): a plausible-looking scale is not a verified scale, "
        "so this asset cannot be PRODUCTION_READY until the real dimensions are entered"
    )


@rule("U002", "unity", Severity.CRITICAL, "Orientation is valid (+Y up, +Z forward)")
def u002(c: Ctx):
    if not c.is_vehicle:
        return NA, "orientation rule applies to vehicles"
    lo = np.min([m.bounds[0] for m in c.scene.meshes.values()], axis=0)
    hi = np.max([m.bounds[1] for m in c.scene.meshes.values()], axis=0)
    ext = hi - lo
    probs = []
    if int(np.argmax(ext)) != 2:
        probs.append(f"longest axis is {'XYZ'[int(np.argmax(ext))]}, expected Z")
    v = c.scene.manifest.vehicle
    if v and v.wheels:
        ys = [w.position[1] for w in v.wheels]
        if max(ys) > ext[1] * 0.4:
            probs.append("wheels are not near the bottom (+Y up?)")
        zs = [w.position[2] for w in v.wheels]
        if max(zs) - min(zs) < 0.5 * ext[2] * 0.5:
            probs.append("wheelbase is not along Z")
        for w in v.wheels:
            m = c.scene.meshes.get(w.tire_part or "")
            if m is not None and not (m.extents[0] < m.extents[1] and m.extents[0] < m.extents[2]):
                probs.append(f"{w.name}: tyre axis is not X")
                break
    return (P, "longest axis Z, wheels at the bottom with X axles") if not probs else (F, "; ".join(probs))


@rule("U003", "unity", Severity.MAJOR, "Naming is valid")
def u003(c: Ctx):
    man = c.scene.manifest
    names = (
        [p.name for p in man.parts]
        + [n.name for n in (man.rig.nodes if man.rig else [])]
        + [x.name for x in man.colliders]
    )
    bad = [n for n in names if not UNITY_NAME.match(n)]
    dup = {n for n in names if names.count(n) > 1}
    return (
        (P, f"{len(names)} names valid and unique")
        if not (bad or dup)
        else (F, f"invalid names {bad[:5]} duplicates {sorted(dup)[:5]}")
    )


@rule("U004", "unity", Severity.MAJOR, "Hierarchy is valid")
def u004(c: Ctx):
    man = c.scene.manifest
    if not man.rig:
        return (W, "no rig hierarchy: parts export as a flat list") if c.is_vehicle else (NA, "flat asset")
    nodes = {n.name: n for n in man.rig.nodes}
    roots = [n for n in man.rig.nodes if n.parent is None]
    bad = [n.name for n in man.rig.nodes if n.parent is not None and n.parent not in nodes]
    badp = [p.name for p in man.parts if p.parent and p.parent not in nodes]
    cyc = []
    for n in nodes.values():
        seen, cur = set(), n
        while cur.parent:
            if cur.name in seen:
                cyc.append(n.name)
                break
            seen.add(cur.name)
            cur = nodes.get(cur.parent, cur)
            if cur.parent not in nodes and cur.parent:
                break
    ok = len(roots) == 1 and not (bad or badp or cyc)
    return (
        (P, f"{len(nodes)} rig nodes, single root")
        if ok
        else (F, f"roots={len(roots)} missing parents={bad[:4]} part parents={badp[:4]} cycles={cyc[:3]}")
    )


@rule("U005", "unity", Severity.MINOR, "Materials map to Unity")
def u005(c: Ctx):
    bad = [m.name for m in c.scene.manifest.materials if m.alpha_mode == "BLEND" and m.base_color[3] >= 1.0]
    return (P, "materials map cleanly to URP/HDRP Lit") if not bad else (W, f"BLEND materials with alpha 1.0: {bad}")


@rule("U006", "unity", Severity.MAJOR, "Pivot at ground and centreline")
def u006(c: Ctx):
    if not c.is_vehicle:
        return NA, "vehicle rule"
    lo = np.min([m.bounds[0] for m in c.scene.meshes.values()], axis=0)
    hi = np.max([m.bounds[1] for m in c.scene.meshes.values()], axis=0)
    ok = abs(lo[1]) <= 0.03 and abs((lo[0] + hi[0]) / 2) <= 0.05
    return (
        (P, "origin on the ground, centred in X")
        if ok
        else (F, f"origin offset: min y={lo[1]:.3f}, centre x={(lo[0] + hi[0]) / 2:.3f}")
    )


@rule("U007", "unity", Severity.MAJOR, "Export integrity (dry-run GLB)")
def u007(c: Ctx):
    from aro_studio.export.gltf import ExportOptions, export_glb
    from aro_studio.export.verify import verify_glb

    data, rep = export_glb(c.scene, ExportOptions())
    ver = verify_glb(data, c.scene)
    c.dry_export = {"bytes": rep["bytes"], "nodes": rep["nodes"], "triangles": rep["triangles"]}
    bad = [ch["message"] for ch in ver["checks"] if not ch["ok"]]
    return (
        (P, f"GLB builds and re-verifies ({rep['bytes'] / 1e6:.2f} MB, {rep['nodes']} nodes)", c.dry_export)
        if ver["ok"]
        else (F, "; ".join(bad[:4]))
    )


# ================= engine =========================================================================
def _category_score(results: list[CheckResult]) -> float | None:
    num = den = 0.0
    for r in results:
        if r.status in (CheckStatus.SKIPPED.value, CheckStatus.NOT_APPLICABLE.value):
            continue
        w = SEVERITY_WEIGHT[Severity(r.severity)]
        if w == 0:
            continue
        credit = {CheckStatus.PASSED.value: 1.0, CheckStatus.WARNING.value: 0.6, CheckStatus.FAILED.value: 0.0}[
            r.status
        ]
        num += w * credit
        den += w
    return None if den == 0 else 100.0 * num / den


def run_validation(scene: Scene, category_id: str, config: ValidationConfig | None = None) -> dict[str, Any]:
    config = config or ValidationConfig()
    cat = get_category(category_id)
    ctx = Ctx(scene=scene, config=config, category_id=category_id, is_vehicle=cat.group == "vehicles", group=cat.group)
    t0 = time.perf_counter()
    results: list[CheckResult] = [run(ctx) for _, _, _, _, run in RULES]
    cats: dict[str, dict[str, Any]] = {}
    for name in CATEGORY_WEIGHTS:
        rs = [r for r in results if r.category == name]
        sc = _category_score(rs)
        cats[name] = {
            "score": None if sc is None else round(sc, 1),
            "weight": CATEGORY_WEIGHTS[name],
            "applicable": sc is not None,
            "failed": sum(r.status == CheckStatus.FAILED.value for r in rs),
            "warnings": sum(r.status == CheckStatus.WARNING.value for r in rs),
        }
    num = sum(c["score"] * c["weight"] for c in cats.values() if c["score"] is not None)
    den = sum(c["weight"] for c in cats.values() if c["score"] is not None)
    overall = round(num / den, 1) if den else 0.0
    failed = [r for r in results if r.status == CheckStatus.FAILED.value]
    crit = [r for r in failed if r.severity == Severity.CRITICAL.value]
    major = [r for r in failed if r.severity == Severity.MAJOR.value]
    geometry_dead = any(r.id in ("G001", "G002") and r.status == CheckStatus.FAILED.value for r in results)
    if geometry_dead:
        status = AssetStatus.FAILED
    elif crit or major or overall < config.ready_threshold:
        status = AssetStatus.NEEDS_REVIEW
    else:
        status = AssetStatus.PRODUCTION_READY
    reasons = []
    if crit:
        reasons.append(f"{len(crit)} critical failure(s): " + ", ".join(r.id for r in crit))
    if major:
        reasons.append(f"{len(major)} major failure(s): " + ", ".join(r.id for r in major))
    if overall < config.ready_threshold:
        reasons.append(f"overall score {overall}% is below the {config.ready_threshold:.0f}% threshold")
    return {
        "asset_name": scene.manifest.name,
        "category": category_id,
        "status": status.value,
        "overall": overall,
        "critical_failures": len(crit),
        "major_failures": len(major),
        "score_never_overrides_critical": True,
        "blocking_reasons": reasons,
        "categories": cats,
        "checks": [r.to_dict() for r in results],
        "recommendations": [
            f"{r.id} {r.title}: {r.message}"
            for r in sorted(failed, key=lambda x: SEVERITY_WEIGHT[Severity(x.severity)], reverse=True)
        ],
        "seconds": round(time.perf_counter() - t0, 3),
        "config": asdict(config),
    }
