"""Declarative data model of a Studio asset.

Canonical conventions (documented in docs/unity/unity-integration.md):
  * metres, right-handed, +Y up, vehicle forward = +Z (glTF convention)
  * origin on the ground plane (y=0 at the bottom of the tyres), x=0 on the centreline
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Vec3 = tuple[float, float, float]
Vec4 = tuple[float, float, float, float]

SCHEMA_VERSION = 1


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MaterialCategory(str, Enum):
    PAINT = "paint"
    METAL = "metal"
    CHROME = "chrome"
    RUBBER = "rubber"
    GLASS = "glass"
    PLASTIC = "plastic"
    LIGHTS = "lights"
    INTERIOR = "interior"
    GENERIC = "generic"


class MaterialDef(_M):
    """Metallic-roughness PBR material (glTF 2.0 compatible, Unity URP/HDRP mappable)."""

    name: str
    category: MaterialCategory = MaterialCategory.GENERIC
    base_color: Vec4 = (0.8, 0.8, 0.8, 1.0)
    metallic: float = Field(0.0, ge=0.0, le=1.0)
    roughness: float = Field(0.5, ge=0.0, le=1.0)
    emissive: Vec3 = (0.0, 0.0, 0.0)
    emissive_strength: float = Field(1.0, ge=0.0, le=1000.0)
    alpha_mode: Literal["OPAQUE", "BLEND", "MASK"] = "OPAQUE"
    alpha_cutoff: float = Field(0.5, ge=0.0, le=1.0)
    double_sided: bool = False
    # channel -> texture name (see TextureDef). Channels: base_color, normal, roughness, metallic,
    # occlusion, emission
    textures: dict[str, str] = Field(default_factory=dict)

    @field_validator("textures")
    @classmethod
    def _channels(cls, v: dict[str, str]) -> dict[str, str]:
        allowed = {"base_color", "normal", "roughness", "metallic", "occlusion", "emission"}
        bad = set(v) - allowed
        if bad:
            raise ValueError(f"unknown PBR channel(s): {sorted(bad)}")
        return v


class TextureDef(_M):
    name: str
    file: str  # path relative to version dir, e.g. textures/body_basecolor.png
    width: int
    height: int
    sha256: str
    colorspace: Literal["srgb", "linear"] = "srgb"
    channel: str = "base_color"
    mipmaps: bool = False
    format: str = "png"


class PartDef(_M):
    name: str
    component: str = "other"  # ComponentRole value
    material: str | None = None
    mesh_file: str
    parent: str | None = None  # parent part name (hierarchy)
    pivot: Vec3 = (0.0, 0.0, 0.0)  # node origin in asset space
    vertex_count: int = 0
    triangle_count: int = 0
    has_uv: bool = False
    has_vertex_colors: bool = False
    visible: bool = True


class LodDef(_M):
    level: int = Field(ge=0, le=7)
    target_ratio: float = Field(1.0, gt=0.0, le=1.0)
    screen_height: float = Field(1.0, ge=0.0, le=1.0)  # Unity LODGroup transition (fraction of screen)
    parts: list[PartDef] = Field(default_factory=list)
    triangle_count: int = 0
    vertex_count: int = 0


class ColliderKind(str, Enum):
    BOX = "box"
    SPHERE = "sphere"
    CAPSULE = "capsule"
    CONVEX_HULL = "convex_hull"
    MESH = "mesh"
    VEHICLE_MESH = "vehicle_mesh"


class ColliderDef(_M):
    name: str
    kind: ColliderKind
    purpose: str = "body"  # body | wheel | cabin | custom
    center: Vec3 = (0.0, 0.0, 0.0)
    size: Vec3 | None = None  # box full extents
    radius: float | None = None  # sphere/capsule
    height: float | None = None  # capsule total height
    axis: Literal["X", "Y", "Z"] = "Y"
    mesh_file: str | None = None  # hull/mesh colliders
    triangle_count: int = 0
    source_part: str | None = None


class PivotDef(_M):
    name: str
    kind: str  # door | mirror | wiper | hood | steering | custom
    position: Vec3
    axis: Vec3 = (0.0, 1.0, 0.0)
    limits_deg: tuple[float, float] = (0.0, 0.0)
    part: str | None = None  # part driven by this pivot
    children: list[str] = Field(default_factory=list)  # further parts that move with it (e.g. door glass)


class WheelDef(_M):
    name: str
    axle: str
    side: Literal["left", "right"]
    position: Vec3  # wheel centre
    radius: float = Field(gt=0.0)
    width: float = Field(gt=0.0)
    steering: bool = False
    driven: bool = False
    part: str | None = None  # visual part name
    tire_part: str | None = None
    detail_parts: list[str] = Field(default_factory=list)  # extra geometry parented to the wheel spin node


class AxleDef(_M):
    name: str
    position: Vec3  # axle centre line (x≈0)
    track_width: float = Field(gt=0.0)
    steering: bool = False
    driven: bool = False
    lift: bool = False
    suspension_travel: float = Field(0.15, ge=0.0)


class SuspensionPoint(_M):
    name: str
    axle: str
    side: Literal["left", "right", "center"] = "center"
    position: Vec3
    travel: float = Field(0.15, ge=0.0)


class AttachmentPoint(_M):
    name: str
    kind: str  # fifth_wheel | trailer_connector | air_hose | camera | exhaust | custom
    position: Vec3
    direction: Vec3 = (0.0, 1.0, 0.0)


class LightDef(_M):
    name: str
    kind: Literal["head", "tail", "brake", "indicator", "reverse", "marker", "fog", "work"]
    side: Literal["left", "right", "center"] = "center"
    position: Vec3
    direction: Vec3 = (0.0, 0.0, 1.0)
    color: Vec3 = (1.0, 1.0, 1.0)
    part: str | None = None


class VehicleIdentity(_M):
    manufacturer: str
    brand: str
    model: str
    category: str  # heavy_truck, bus, car ...
    body_type: str = ""
    drive_configuration: str = ""
    asset_version: str = "0.1.0"


class VehicleSpec(_M):
    identity: VehicleIdentity
    axles: list[AxleDef] = Field(default_factory=list)
    wheels: list[WheelDef] = Field(default_factory=list)
    suspension_points: list[SuspensionPoint] = Field(default_factory=list)
    steering_points: list[Vec3] = Field(default_factory=list)
    center_of_mass: Vec3 | None = None
    attachment_points: list[AttachmentPoint] = Field(default_factory=list)
    pivots: list[PivotDef] = Field(default_factory=list)
    mirror_positions: list[Vec3] = Field(default_factory=list)
    lights: list[LightDef] = Field(default_factory=list)
    wheelbase: float | None = None
    components: dict[str, list[str]] = Field(default_factory=dict)  # role -> part names
    mass_kg: float | None = None


class RigNode(_M):
    name: str
    parent: str | None
    role: str  # root | body | steering | wheel_spin | suspension | door | mirror | wiper | light | attachment
    pivot: Vec3
    axis: Vec3 | None = None
    limits_deg: tuple[float, float] | None = None
    part: str | None = None


class RigSpec(_M):
    nodes: list[RigNode] = Field(default_factory=list)


class Provenance(_M):
    source: str = "unknown"  # ai_reconstruction | import | procedural_reference | derived
    engine_id: str | None = None
    model_version: str | None = None
    generation_id: str | None = None
    input_image_sha256: str | None = None
    native_up: str | None = None  # the raw mesh's up axis (+Y, -Z, ...), when it was detected rather than assumed
    note: str = ""


class SceneManifest(_M):
    schema_version: int = SCHEMA_VERSION
    name: str
    category: str = "other"
    units: Literal["m"] = "m"
    up_axis: Literal["Y"] = "Y"
    forward_axis: Literal["+Z"] = "+Z"
    parts: list[PartDef] = Field(default_factory=list)
    materials: list[MaterialDef] = Field(default_factory=list)
    textures: list[TextureDef] = Field(default_factory=list)
    lods: list[LodDef] = Field(default_factory=list)  # levels >= 1; LOD0 is `parts`
    colliders: list[ColliderDef] = Field(default_factory=list)
    vehicle: VehicleSpec | None = None
    rig: RigSpec | None = None
    provenance: Provenance = Field(default_factory=Provenance)
    files: dict[str, str] = Field(default_factory=dict)  # relpath -> sha256 (integrity)

    def part(self, name: str) -> PartDef | None:
        return next((p for p in self.parts if p.name == name), None)

    def material(self, name: str | None) -> MaterialDef | None:
        return next((m for m in self.materials if m.name == name), None) if name else None

    def texture(self, name: str) -> TextureDef | None:
        return next((t for t in self.textures if t.name == name), None)

    @property
    def lod_levels(self) -> list[int]:
        return [0, *sorted(lod.level for lod in self.lods)]
