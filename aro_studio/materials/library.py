"""PBR material presets and assignment (spec §14).

Presets are physically *plausible starting points*, not measured data. All are metallic-roughness
(glTF 2.0), which maps directly to Unity URP/HDRP Lit (Metallic/Smoothness = 1 - roughness).
"""

from __future__ import annotations

from aro_studio.core.errors import InvalidInputError
from aro_studio.scene.model import MaterialCategory, MaterialDef
from aro_studio.scene.store import Scene

C = MaterialCategory

CATEGORY_DEFAULTS: dict[MaterialCategory, dict] = {
    C.PAINT: dict(base_color=(0.8, 0.8, 0.8, 1.0), metallic=0.35, roughness=0.32),
    C.METAL: dict(base_color=(0.45, 0.46, 0.48, 1.0), metallic=0.9, roughness=0.5),
    C.CHROME: dict(base_color=(0.92, 0.92, 0.93, 1.0), metallic=1.0, roughness=0.08),
    C.RUBBER: dict(base_color=(0.04, 0.04, 0.04, 1.0), metallic=0.0, roughness=0.92),
    C.GLASS: dict(
        base_color=(0.6, 0.72, 0.78, 0.25), metallic=0.0, roughness=0.04, alpha_mode="BLEND", double_sided=True
    ),
    C.PLASTIC: dict(base_color=(0.1, 0.1, 0.11, 1.0), metallic=0.0, roughness=0.55),
    C.LIGHTS: dict(
        base_color=(1.0, 1.0, 0.9, 1.0), metallic=0.0, roughness=0.15, emissive=(1.0, 0.95, 0.8), emissive_strength=2.0
    ),
    C.INTERIOR: dict(base_color=(0.12, 0.12, 0.13, 1.0), metallic=0.0, roughness=0.85),
    C.GENERIC: dict(base_color=(0.7, 0.7, 0.7, 1.0), metallic=0.0, roughness=0.6),
}


def make_material(name: str, category: MaterialCategory | str = C.GENERIC, **overrides) -> MaterialDef:
    cat = MaterialCategory(category)
    params = {**CATEGORY_DEFAULTS[cat], **overrides}
    return MaterialDef(name=name, category=cat, **params)


# ARO Motors reference palette (original colours, no third-party livery)
ARO_PAINT = make_material("body_paint", C.PAINT, base_color=(0.86, 0.33, 0.07, 1.0))
CHASSIS_STEEL = make_material("chassis_steel", C.METAL, base_color=(0.09, 0.09, 0.1, 1.0), metallic=0.7, roughness=0.62)
CHROME = make_material("chrome", C.CHROME)
GLASS = make_material("glass", C.GLASS)
RUBBER = make_material("rubber", C.RUBBER)
PLASTIC = make_material("plastic", C.PLASTIC)
ALUMINIUM = make_material("aluminium", C.METAL, base_color=(0.72, 0.73, 0.75, 1.0), metallic=0.95, roughness=0.38)
RIM_STEEL = make_material("rim_steel", C.METAL, base_color=(0.62, 0.63, 0.65, 1.0), metallic=0.95, roughness=0.35)
HEADLIGHT = make_material("headlight", C.LIGHTS)
TAILLIGHT = make_material(
    "taillight", C.LIGHTS, base_color=(0.8, 0.02, 0.02, 1.0), emissive=(1.0, 0.05, 0.05), emissive_strength=1.5
)
INDICATOR = make_material(
    "indicator", C.LIGHTS, base_color=(1.0, 0.55, 0.0, 1.0), emissive=(1.0, 0.5, 0.0), emissive_strength=1.2
)
INTERIOR = make_material("interior", C.INTERIOR)

REFERENCE_MATERIALS = [
    ARO_PAINT,
    CHASSIS_STEEL,
    CHROME,
    GLASS,
    RUBBER,
    PLASTIC,
    ALUMINIUM,
    RIM_STEEL,
    HEADLIGHT,
    TAILLIGHT,
    INDICATOR,
    INTERIOR,
]


def upsert_material(scene: Scene, material: MaterialDef) -> None:
    mats = scene.manifest.materials
    for i, m in enumerate(mats):
        if m.name == material.name:
            mats[i] = material
            return
    mats.append(material)


def assign_material(scene: Scene, part_name: str, material_name: str) -> None:
    part = scene.manifest.part(part_name)
    if part is None:
        raise InvalidInputError(f"Unknown part '{part_name}'.")
    if scene.manifest.material(material_name) is None:
        raise InvalidInputError(f"Unknown material '{material_name}'.", recommended_action="Create the material first.")
    part.material = material_name
    for lod in scene.manifest.lods:
        for p in lod.parts:
            if p.name == part_name:
                p.material = material_name


def material_usage(scene: Scene) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {m.name: [] for m in scene.manifest.materials}
    for p in scene.manifest.parts:
        if p.material:
            out.setdefault(p.material, []).append(p.name)
    return out


def check_pbr(m: MaterialDef) -> list[str]:
    """Return a list of problems with a material's PBR values (empty = valid)."""
    problems: list[str] = []
    if not all(0.0 <= c <= 1.0 for c in m.base_color):
        problems.append("base_color components must be within 0..1")
    if m.category is MaterialCategory.GLASS and m.alpha_mode == "OPAQUE":
        problems.append("glass should use alpha_mode BLEND or MASK")
    if m.category is MaterialCategory.CHROME and (m.metallic < 0.8 or m.roughness > 0.3):
        problems.append("chrome should be highly metallic (>=0.8) and smooth (roughness <=0.3)")
    if m.category is MaterialCategory.RUBBER and m.metallic > 0.1:
        problems.append("rubber should be non-metallic")
    if m.category is MaterialCategory.LIGHTS and max(m.emissive) <= 0:
        problems.append("light materials should be emissive")
    if m.category in (MaterialCategory.PAINT, MaterialCategory.PLASTIC) and m.metallic > 0.9:
        problems.append(f"{m.category.value} should not be fully metallic")
    return problems
