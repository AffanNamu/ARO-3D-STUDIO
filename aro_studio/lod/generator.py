"""LOD generation (spec §18). Fully configurable; never touches LOD0."""

from __future__ import annotations

from dataclasses import dataclass, field

import trimesh
from pydantic import BaseModel, Field

from aro_studio.core.errors import InvalidInputError
from aro_studio.core.tm import as_mesh
from aro_studio.geometry import ops
from aro_studio.scene.model import LodDef, PartDef
from aro_studio.scene.store import Scene

# Parts driven by animation must stay separate nodes so they can still rotate/steer at every LOD.
ANIMATED_ROLES = {"wheel", "wheel_detail", "tire", "door", "mirror", "wiper"}


class LodLevelConfig(BaseModel):
    level: int = Field(ge=1, le=7)
    ratio: float = Field(gt=0.0, le=1.0)  # target triangle ratio relative to LOD0
    screen_height: float = Field(ge=0.0, le=1.0)  # Unity LODGroup transition height
    drop_roles: list[str] = Field(default_factory=list)  # component roles removed at this LOD
    merge_static_by_material: bool = False
    min_faces_per_part: int = Field(12, ge=4)


class LodConfig(BaseModel):
    levels: list[LodLevelConfig]
    lod0_screen_height: float = 0.6

    @staticmethod
    def vehicle_default() -> LodConfig:
        return LodConfig(
            levels=[
                LodLevelConfig(level=1, ratio=0.55, screen_height=0.30),
                LodLevelConfig(level=2, ratio=0.28, screen_height=0.15, drop_roles=["interior", "wiper"]),
                LodLevelConfig(
                    level=3,
                    ratio=0.12,
                    screen_height=0.05,
                    drop_roles=["interior", "wiper", "mirror"],
                    merge_static_by_material=True,
                ),
            ]
        )

    @staticmethod
    def generic_default() -> LodConfig:
        return LodConfig(
            levels=[
                LodLevelConfig(level=1, ratio=0.5, screen_height=0.4),
                LodLevelConfig(level=2, ratio=0.25, screen_height=0.2),
                LodLevelConfig(level=3, ratio=0.1, screen_height=0.08),
            ]
        )

    def validate_monotonic(self) -> None:
        lv = sorted(self.levels, key=lambda x: x.level)
        if [x.level for x in lv] != list(range(1, len(lv) + 1)):
            raise InvalidInputError("LOD levels must be consecutive starting at 1.")
        prev_r, prev_s = 1.0, self.lod0_screen_height
        for x in lv:
            if x.ratio >= prev_r:
                raise InvalidInputError(
                    f"LOD{x.level} ratio ({x.ratio}) must be lower than LOD{x.level - 1} ({prev_r})."
                )
            if x.screen_height >= prev_s:
                raise InvalidInputError(f"LOD{x.level} screen_height must decrease with distance.")
            prev_r, prev_s = x.ratio, x.screen_height


@dataclass
class LodResult:
    level: int
    target_ratio: float
    achieved_ratio: float
    triangles: int
    parts: int
    dropped_parts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def generate_lods(scene: Scene, config: LodConfig | None = None, *, is_vehicle: bool | None = None) -> list[LodResult]:
    """Replace ``scene.lod_meshes`` / ``manifest.lods`` with freshly generated levels."""
    man = scene.manifest
    if not scene.meshes:
        raise InvalidInputError("Nothing to build LODs from.")
    if is_vehicle is None:
        is_vehicle = man.vehicle is not None
    config = config or (LodConfig.vehicle_default() if is_vehicle else LodConfig.generic_default())
    config.validate_monotonic()
    base_tris = scene.triangle_count
    scene.lod_meshes, man.lods = {}, []
    results: list[LodResult] = []
    for lv in sorted(config.levels, key=lambda x: x.level):
        meshes: dict[str, trimesh.Trimesh] = {}
        parts: list[PartDef] = []
        dropped: list[str] = []
        notes: list[str] = []
        merge_groups: dict[str, list[trimesh.Trimesh]] = {}
        # Budget decimation by part size: big parts carry the reduction.
        for p in man.parts:
            if p.component in lv.drop_roles:
                dropped.append(p.name)
                continue
            m = scene.meshes[p.name]
            target = max(lv.min_faces_per_part, int(len(m.faces) * lv.ratio))
            if len(m.faces) > target:
                # a staged ladder pinches the surface less than one big step; what is still pinched is repaired (judged on the
                # position-welded topology, so UV seams and texture coordinates are untouched)
                dm, rep = ops.decimate(m, target_faces=target, stages=4)
                if rep.faces_after >= len(m.faces):
                    dm = m.copy()
                else:
                    dm, _ = ops.remove_non_manifold(dm)
            else:
                dm = m.copy()
            if lv.merge_static_by_material and p.component not in ANIMATED_ROLES:
                merge_groups.setdefault(p.material or "unassigned", []).append(dm)
                continue
            meshes[p.name] = dm
            parts.append(p.model_copy(deep=True))
        for mat, group in merge_groups.items():
            name = f"Merged_{mat}"
            merged = as_mesh(trimesh.util.concatenate(group)) if len(group) > 1 else group[0]
            if len(merged.faces) > lv.min_faces_per_part * 4:
                merged, _ = ops.decimate(
                    merged, target_faces=max(lv.min_faces_per_part * 4, int(sum(len(g.faces) for g in group)))
                )
            meshes[name] = merged
            parts.append(
                PartDef(
                    name=name,
                    component="body",
                    material=None if mat == "unassigned" else mat,
                    mesh_file="",
                    parent=None,
                    pivot=(0.0, 0.0, 0.0),
                )
            )
            notes.append(f"{len(group)} static parts merged by material '{mat}'")
        scene.lod_meshes[lv.level] = meshes
        man.lods.append(LodDef(level=lv.level, target_ratio=lv.ratio, screen_height=lv.screen_height, parts=parts))
        tris = int(sum(len(m.faces) for m in meshes.values()))
        results.append(LodResult(lv.level, lv.ratio, tris / max(base_tris, 1), tris, len(parts), dropped, notes))
    scene.refresh_counts()
    return results
