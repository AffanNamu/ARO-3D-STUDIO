"""Supply-chain and checkpoint-loading security (Phase 1).

The fake ``torch`` / ``tsr`` / ``omegaconf`` modules below only RECORD how our loader calls them (that it verifies
checksums first, uses ``weights_only=True``, never downloads unpinned files). They do not run any model and no test here
claims inference works.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

from aro_studio.core.errors import EngineUnavailableError, ModelError
from aro_studio.engines import triposr
from aro_studio.engines.pinning import HubInfo, RealHub, pin_lock
from aro_studio.engines.registry import license_gate
from aro_studio.engines.weights import ModelLock, load_lock, resolve_weights, validate_config_classes, verify_file

REV = "a" * 40
AUX_REV = "b" * 40


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


CONFIG = b"image_tokenizer_cls: tsr.models.tokenizers.image.DINOSingleImageTokenizer\nbackbone_cls: tsr.models.transformer.transformer_1d.Transformer1D\n"
CKPT = b"not a real checkpoint - plain bytes used only for checksum tests"
AUX = b'{"model_type": "vit"}'


def complete_lock() -> ModelLock:
    d = load_lock("triposr").model_dump(by_alias=True, mode="json")
    d["weights"].update(revision=REV, pinned_on="2026-10-10", pinned_by="test")
    d["weights"]["files"] = {
        "config.yaml": {"sha256": sha(CONFIG), "size": len(CONFIG)},
        "model.ckpt": {"sha256": sha(CKPT), "size": len(CKPT)},
    }
    d["aux_files"][0].update(revision=AUX_REV, sha256=sha(AUX), size=len(AUX))
    return ModelLock.model_validate(d)


@pytest.fixture
def weights_dir(tmp_path):
    d = tmp_path / "w"
    (d / "aux" / "facebook__dino-vitb16").mkdir(parents=True)
    (d / "config.yaml").write_bytes(CONFIG)
    (d / "model.ckpt").write_bytes(CKPT)
    (d / "aux" / "facebook__dino-vitb16" / "config.json").write_bytes(AUX)
    return d


# ---- lock fixtures and the committed lock --------------------------------------------------------------------------
def incomplete_lock() -> ModelLock:
    """Deliberately remove integrity pins to test that the security gate remains closed."""
    d = load_lock("triposr").model_dump(by_alias=True, mode="json")
    d["weights"].update(revision=None, pinned_on=None, pinned_by=None)
    for file_lock in d["weights"]["files"].values():
        file_lock.update(sha256=None, size=None)
    for aux in d["aux_files"]:
        aux.update(revision=None, sha256=None, size=None)
    return ModelLock.model_validate(d)


def test_committed_lock_records_licence_evidence_and_complete_pin():
    lock = load_lock("triposr")
    assert lock.license.spdx == "MIT" and lock.code["commit"] == "107cefdc244c39106fa830359024f6a2f1c78871"
    ev = lock.license.evidence
    assert any(e.independently_fetched and "LICENSE" in e.source and e.file_sha256 for e in ev)
    assert any(e.independently_fetched and "README" in e.source for e in ev)
    owner = [e for e in ev if "huggingface.co" in e.source and not e.independently_fetched][0]
    assert "could NOT fetch" in owner.verified_by  # owner statement remains clearly identified
    assert lock.complete() and lock.missing() == []
    assert lock.weights.revision is not None and len(lock.weights.revision) == 40
    assert lock.weights.pinned_on and lock.weights.pinned_by
    for f in lock.weights.files.values():
        assert f.sha256 is not None and len(f.sha256) == 64 and f.size and f.size > 0
    for aux in lock.aux_files:
        assert aux.revision is not None and len(aux.revision) == 40
        assert aux.sha256 is not None and len(aux.sha256) == 64 and aux.size and aux.size > 0
    assert "intentionally null until" not in lock.note


def test_engine_stays_gated_and_blocked_while_lock_incomplete():
    e = triposr.TripoSREngine(lock=incomplete_lock())
    assert (
        e.info.license.status == "claimed"
        and "UNPINNED" in e.info.version
        and "NOT YET VERIFIED" in e.info.license.notes
    )
    with pytest.raises(EngineUnavailableError):
        license_gate(e, set())  # explicit gate still closed
    av = e.availability("cpu")
    assert (
        not av.ok
        and any("lock incomplete" in r for r in av.reasons)
        and any("pin_triposr_weights" in a for a in av.activation)
    )
    with pytest.raises(EngineUnavailableError, match="lock incomplete"):
        e.load("cpu")


def test_even_with_deployer_attestation_unpinned_weights_cannot_load():
    e = triposr.TripoSREngine(lock=incomplete_lock())
    license_gate(e, {"triposr"})  # the licence attestation alone passes the licence gate...
    with pytest.raises(EngineUnavailableError):  # ...but the integrity gate is independent and still closed
        e.load("cpu")


def test_licence_becomes_verified_only_when_lock_complete():
    e = triposr.TripoSREngine(lock=complete_lock())
    assert e.info.license.status == "verified" and e.info.revision == REV and e.info.version.endswith(REV)
    license_gate(e, set())


# ---- verification primitives -----------------------------------------------------------------------------
def test_verify_file_detects_tampering_wrong_size_and_missing(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello")
    verify_file(f, sha(b"hello"), 5, "x")
    with pytest.raises(ModelError, match="SHA-256 mismatch") as ei:
        verify_file(f, sha(b"HELLO"), 5, "x")
    assert ei.value.details["actual"] == sha(b"hello")
    with pytest.raises(ModelError, match="size"):
        verify_file(f, sha(b"hello"), 6, "x")
    with pytest.raises(ModelError, match="not found"):
        verify_file(tmp_path / "nope", sha(b"x"), None, "x")


def test_resolve_local_dir_ok_and_each_tamper_detected(weights_dir):
    r = resolve_weights(complete_lock(), str(weights_dir))
    assert (
        r.source.startswith("local:")
        and r.checkpoint.name == "model.ckpt"
        and ("facebook/dino-vitb16", "config.json") in r.aux
    )
    for rel in ("config.yaml", "model.ckpt", "aux/facebook__dino-vitb16/config.json"):
        p = weights_dir / rel
        orig = p.read_bytes()
        p.write_bytes(orig[:-1] + bytes([orig[-1] ^ 1]))  # flip one bit
        with pytest.raises(ModelError, match="mismatch"):
            resolve_weights(complete_lock(), str(weights_dir))
        p.write_bytes(orig)


def test_resolve_hub_uses_pinned_revision_and_verifies_downloads(tmp_path):
    calls = []
    store = {"config.yaml": CONFIG, "model.ckpt": CKPT, "config.json": AUX}

    def dl(repo, filename, revision):
        calls.append((repo, filename, revision))
        p = tmp_path / f"{repo.replace('/', '_')}_{filename}"
        p.write_bytes(store[filename])
        return str(p)

    r = resolve_weights(complete_lock(), "stabilityai/TripoSR", downloader=dl)
    assert r.source == f"hub:stabilityai/TripoSR@{REV}"
    assert {(c[0], c[1], c[2]) for c in calls} == {
        ("stabilityai/TripoSR", "config.yaml", REV),
        ("stabilityai/TripoSR", "model.ckpt", REV),
        ("facebook/dino-vitb16", "config.json", AUX_REV),
    }
    assert all(c[2] != "main" for c in calls)  # never a mutable ref
    store["model.ckpt"] = b"swapped upstream"  # a moved/poisoned artefact is rejected, not loaded
    with pytest.raises(ModelError, match="mismatch|size"):
        resolve_weights(complete_lock(), "stabilityai/TripoSR", downloader=dl)


def test_resolve_refuses_other_repositories_and_incomplete_lock(weights_dir):
    with pytest.raises(ModelError, match="Refusing to load weights"):
        resolve_weights(complete_lock(), "evil/TripoSR-pro")
    with pytest.raises(ModelError, match="incomplete") as ei:
        resolve_weights(incomplete_lock(), str(weights_dir))
    assert ei.value.details["missing"]


# ---- config class allow-list ---------------------------------------------------------------------------------------------
def test_config_class_allowlist():
    assert validate_config_classes({"a_cls": "tsr.x.Y", "n": {"b_cls": "tsr.z.W", "other": "builtins.eval"}}) == [
        "tsr.x.Y",
        "tsr.z.W",
    ]
    for bad in ("os.system", "builtins.eval", "subprocess.Popen", "tsrx.Evil"):
        with pytest.raises(ModelError, match="outside"):
            validate_config_classes({"image_tokenizer_cls": bad})
    with pytest.raises(ModelError):
        validate_config_classes({"n": {"deep": {"renderer_cls": "os.system"}}})


# ---- the real load path with recording stand-ins ----------------------------------------------------------------------
class _Rec:
    def __init__(self):
        self.events: list[tuple] = []


@pytest.fixture
def fake_stack(monkeypatch, weights_dir):
    rec = _Rec()
    torch = types.ModuleType("torch")
    torch.__version__ = "2.6.0+cpu"
    torch.cuda = types.SimpleNamespace(
        is_available=lambda: False, OutOfMemoryError=type("OOM", (RuntimeError,), {}), empty_cache=lambda: None
    )

    def tload(path, map_location=None, weights_only=None):
        rec.events.append(("torch.load", Path(path).name, weights_only))
        return {"w": 1}

    torch.load = tload
    torch.no_grad = lambda: types.SimpleNamespace(__enter__=lambda s: None, __exit__=lambda s, *a: None)
    omegaconf = types.ModuleType("omegaconf")

    class OmegaConf:
        @staticmethod
        def load(path):
            rec.events.append(("omegaconf.load", Path(path).name))
            return {
                "image_tokenizer_cls": "tsr.models.tokenizers.image.DINOSingleImageTokenizer",
                "n": {"renderer_cls": "tsr.models.nerf_renderer.TriplaneNeRFRenderer"},
            }

        @staticmethod
        def resolve(cfg):
            return None

    omegaconf.OmegaConf = OmegaConf
    tok = types.ModuleType("tsr.models.tokenizers.image")
    tok.hf_hub_download = lambda **kw: (_ for _ in ()).throw(AssertionError("unpatched network download"))
    system = types.ModuleType("tsr.system")

    class TSR:
        def __init__(self, cfg):
            rec.events.append(("TSR.__init__",))
            self.aux_path = tok.hf_hub_download(
                repo_id="facebook/dino-vitb16", filename="config.json"
            )  # what upstream does
            rec.events.append(("aux_download_served_from", Path(self.aux_path).name))
            if getattr(rec, "try_unpinned", False):
                tok.hf_hub_download(repo_id="someone/else", filename="x.bin")

        def load_state_dict(self, state):
            rec.events.append(("load_state_dict", state))

        def to(self, device):
            rec.events.append(("to", device))
            return self

    system.TSR = TSR
    for name, mod in {
        "torch": torch,
        "omegaconf": omegaconf,
        "tsr": types.ModuleType("tsr"),
        "tsr.models": types.ModuleType("tsr.models"),
        "tsr.models.tokenizers": types.ModuleType("tsr.models.tokenizers"),
        "tsr.models.tokenizers.image": tok,
        "tsr.system": system,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(triposr.importlib.util, "find_spec", lambda name: object())
    rec.dir = weights_dir
    return rec


def test_load_verifies_before_deserialising_uses_weights_only_and_blocks_unpinned_downloads(fake_stack):
    e = triposr.TripoSREngine(str(fake_stack.dir), lock=complete_lock())
    e.load("cpu")
    names = [x[0] for x in fake_stack.events]
    assert ("torch.load", "model.ckpt", True) in fake_stack.events  # weights_only=True, always
    assert (
        "aux_download_served_from",
        "config.json",
    ) in fake_stack.events  # upstream's DINO download served by the pinned file
    assert (
        names.index("omegaconf.load")
        < names.index("TSR.__init__")
        < names.index("torch.load")
        < names.index("load_state_dict")
    )
    assert e.is_loaded


def test_tampered_checkpoint_never_reaches_torch_load(fake_stack):
    (fake_stack.dir / "model.ckpt").write_bytes(CKPT + b"!")
    e = triposr.TripoSREngine(str(fake_stack.dir), lock=complete_lock())
    with pytest.raises(ModelError, match="mismatch|size"):
        e.load("cpu")
    assert not [x for x in fake_stack.events if x[0] in ("torch.load", "TSR.__init__", "omegaconf.load")]
    assert not e.is_loaded


def test_tampered_config_never_parsed(fake_stack):
    (fake_stack.dir / "config.yaml").write_bytes(CONFIG + b"backbone_cls: os.system\n")
    e = triposr.TripoSREngine(str(fake_stack.dir), lock=complete_lock())
    with pytest.raises(ModelError):
        e.load("cpu")
    assert not [x for x in fake_stack.events if x[0] == "omegaconf.load"]


def test_unpinned_download_attempt_during_construction_is_refused(fake_stack):
    fake_stack.try_unpinned = True
    e = triposr.TripoSREngine(str(fake_stack.dir), lock=complete_lock())
    with pytest.raises(ModelError, match="unpinned"):
        e.load("cpu")
    assert not [x for x in fake_stack.events if x[0] == "torch.load"]


def test_unsafe_pickle_failure_is_not_retried_in_unsafe_mode(fake_stack, monkeypatch):
    calls = []

    def strict_load(path, map_location=None, weights_only=None):
        calls.append(weights_only)
        raise RuntimeError("Weights only load failed: unsupported global os.system")

    sys.modules["torch"].load = strict_load
    e = triposr.TripoSREngine(str(fake_stack.dir), lock=complete_lock())
    with pytest.raises(ModelError, match="Failed to load") as ei:
        e.load("cpu")
    assert calls == [True] and "Unsafe loading is never used" in ei.value.recommended_action


# ---- pinning logic -------------------------------------------------------------------------------------------------------
class FakeHub:
    def __init__(self, tmp_path, *, lie_about_sha=False, licence="mit"):
        self.tmp, self.lie, self.licence = tmp_path, lie_about_sha, licence
        self.blobs = {
            ("stabilityai/TripoSR", "config.yaml"): CONFIG,
            ("stabilityai/TripoSR", "model.ckpt"): CKPT,
            ("facebook/dino-vitb16", "config.json"): AUX,
        }

    def model_info(self, repo_id, revision):
        files = {
            n: {"sha256": ("0" * 64 if self.lie else sha(b)), "size": len(b)}
            for (r, n), b in self.blobs.items()
            if r == repo_id
        }
        return HubInfo(sha=REV if repo_id.startswith("stability") else AUX_REV, license=self.licence, files=files)

    def download(self, repo_id, filename, revision):
        assert len(revision) == 40
        p = self.tmp / f"{repo_id.replace('/', '_')}_{filename}"
        p.write_bytes(self.blobs[(repo_id, filename)])
        return p


def test_pin_lock_produces_a_complete_verified_lock(tmp_path):
    out = pin_lock(load_lock("triposr"), FakeHub(tmp_path), by="tester", today="2026-10-10")
    lock = ModelLock.model_validate({k: v for k, v in out.items() if k != "_pin_report"})
    assert lock.complete() and lock.weights.revision == REV and lock.weights.files["model.ckpt"].sha256 == sha(CKPT)
    assert lock.aux_files[0].revision == AUX_REV
    assert lock.license.evidence[-1].independently_fetched and "mit" in lock.license.evidence[-1].finding
    assert triposr.TripoSREngine(lock=lock).info.license.status == "verified"


def test_pin_lock_aborts_on_hub_checksum_disagreement_and_licence_change(tmp_path):
    with pytest.raises(ModelError, match="differs from the Hub-reported"):
        pin_lock(load_lock("triposr"), FakeHub(tmp_path, lie_about_sha=True), by="t")
    with pytest.raises(ModelError, match="licence tag"):
        pin_lock(load_lock("triposr"), FakeHub(tmp_path, licence="other"), by="t")


def test_committed_lock_json_roundtrips_and_has_no_secrets():
    p = Path(__file__).resolve().parents[1] / "aro_studio" / "engines" / "locks" / "triposr.json"
    raw = p.read_text()
    assert json.loads(raw)["schema"] == 1 and "hf_" not in raw
    ModelLock.model_validate(json.loads(raw))
    assert copy.deepcopy(raw) == raw


def test_old_torch_is_refused_because_weights_only_had_a_bypass(fake_stack):
    sys.modules["torch"].__version__ = "2.5.1+cu121"
    e = triposr.TripoSREngine(str(fake_stack.dir), lock=complete_lock())
    av = e.availability("cpu")
    assert not av.ok and any("too old" in r for r in av.reasons)
    with pytest.raises(EngineUnavailableError, match="too old"):
        e.load("cpu")
    sys.modules["torch"].__version__ = "2.6.0+cu124"
    assert e.availability("cpu").ok
    assert triposr._version_tuple("2.10.0.dev20250101+cpu") == (2, 10, 0)



@pytest.mark.parametrize("dictionary_payload", [True, False])
def test_realhub_model_info_accepts_dict_and_object_sibling_metadata(monkeypatch, dictionary_payload):
    """The supported Hub client must handle the dict payloads returned by older huggingface_hub versions."""
    config_lfs = None
    checkpoint_lfs = {"sha256": sha(CKPT)} if dictionary_payload else types.SimpleNamespace(sha256=sha(CKPT))
    rows = [
        {"rfilename": "config.yaml", "lfs": config_lfs, "size": len(CONFIG)},
        {"rfilename": "model.ckpt", "lfs": checkpoint_lfs, "size": len(CKPT)},
    ]
    card = {"license": "mit"} if dictionary_payload else types.SimpleNamespace(license="mit")
    if not dictionary_payload:
        rows = [types.SimpleNamespace(**row) for row in rows]
        rows[0].lfs = None

    model_info = types.SimpleNamespace(sha=REV, siblings=rows, card_data=card)

    class FakeHfApi:
        def __init__(self, token=None):
            assert token == "test-token"

        def model_info(self, repo_id, revision=None, files_metadata=False):
            assert repo_id == "stabilityai/TripoSR"
            assert revision is None
            assert files_metadata is True
            return model_info

    fake_hub_module = types.ModuleType("huggingface_hub")
    fake_hub_module.HfApi = FakeHfApi
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub_module)

    actual = RealHub(token="test-token").model_info("stabilityai/TripoSR", None)

    assert actual.sha == REV
    assert actual.license == "mit"
    assert actual.files == {
        "config.yaml": {"sha256": None, "size": len(CONFIG)},
        "model.ckpt": {"sha256": sha(CKPT), "size": len(CKPT)},
    }
