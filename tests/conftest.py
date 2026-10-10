from __future__ import annotations

import io

import numpy as np
import pytest
import trimesh
from PIL import Image, ImageDraw

from aro_studio.assets.service import AssetService
from aro_studio.db.database import Database
from aro_studio.projects.service import ProjectService
from aro_studio.security.audit import AuditLog
from aro_studio.storage.layout import StorageLayout


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def layout(tmp_path):
    return StorageLayout(tmp_path / "data")


@pytest.fixture
def services(db, layout):
    audit = AuditLog(db)
    assets = AssetService(db, layout, audit)
    projects = ProjectService(db, layout, assets, audit)
    return projects, assets


@pytest.fixture
def concept_png() -> bytes:
    """A synthetic test image (flat-shaded block on plain background). Not an AI concept."""
    im = Image.new("RGB", (800, 600), (238, 238, 238))
    d = ImageDraw.Draw(im)
    d.rectangle((180, 200, 620, 420), fill=(190, 30, 30))
    d.rectangle((300, 250, 360, 300), fill=(238, 238, 238))
    d.ellipse((230, 380, 330, 480), fill=(20, 20, 20))
    d.ellipse((470, 380, 570, 480), fill=(20, 20, 20))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def make_scene_from_mesh(mesh: trimesh.Trimesh, name: str = "body", category: str = "prop"):
    from aro_studio.materials.library import make_material
    from aro_studio.scene.model import PartDef, SceneManifest
    from aro_studio.scene.store import Scene

    mat = make_material("raw_surface", "generic")
    man = SceneManifest(
        name="test",
        category=category,
        parts=[PartDef(name=name, component="body", material=mat.name, mesh_file="x")],
        materials=[mat],
    )
    sc = Scene(manifest=man, meshes={name: mesh})
    sc.refresh_counts()
    return sc


@pytest.fixture
def box_scene():
    return make_scene_from_mesh(trimesh.creation.box((2.0, 1.5, 6.0)))


@pytest.fixture
def sphere():
    return trimesh.creation.icosphere(subdivisions=3)


def rng():
    return np.random.default_rng(1234)
