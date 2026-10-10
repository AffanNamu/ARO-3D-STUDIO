"""Supply-chain controls for model weights: pinned revision, SHA-256 verification, licence-evidence lock.

The lock (``engines/locks/<engine>.json``) is the single source of truth. A model may only be loaded when its lock is
*complete*: licence evidence recorded, weights revision pinned to a 40-hex commit, and a SHA-256 + size recorded for every
file that will be loaded (including auxiliary downloads made by the upstream code). Files are verified **before** they are
handed to any deserialiser.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aro_studio.core.errors import ModelError

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1 << 20


class FileLock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str | None = None
    size: int | None = None


class AuxFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo_id: str
    filename: str
    purpose: str = ""
    revision: str | None = None
    sha256: str | None = None
    size: int | None = None
    licence_note: str = ""


class WeightsLock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo_id: str
    revision: str | None = None
    files: dict[str, FileLock] = Field(default_factory=dict)
    pinned_on: str | None = None
    pinned_by: str | None = None


class LicenceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    finding: str
    file_sha256: str | None = None
    verified_on: str
    verified_by: str
    independently_fetched: bool


class LicenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spdx: str
    commercial_use: str
    scope: str
    evidence: list[LicenceEvidence]


class ModelLock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(alias="schema")
    engine_id: str
    note: str = ""
    code: dict[str, Any]
    weights: WeightsLock
    aux_files: list[AuxFile] = Field(default_factory=list)
    license: LicenceRecord

    def missing(self) -> list[str]:
        """Everything still required before the engine may load. Empty list == lock complete."""
        out: list[str] = []
        lic = self.license
        if not lic.evidence or not any(e.independently_fetched and e.verified_on for e in lic.evidence):
            out.append("licence evidence: at least one independently fetched source with a verification date")
        if not self.weights.revision or not _HEX40.match(self.weights.revision):
            out.append(f"weights revision of {self.weights.repo_id} pinned to a 40-hex commit")
        if not self.weights.files:
            out.append("weights file list")
        for name, f in self.weights.files.items():
            if not (f.sha256 and _HEX64.match(f.sha256)) or not f.size:
                out.append(f"SHA-256 + size of {self.weights.repo_id}/{name}")
        for a in self.aux_files:
            if not (a.revision and _HEX40.match(a.revision)) or not (a.sha256 and _HEX64.match(a.sha256)) or not a.size:
                out.append(f"revision + SHA-256 + size of auxiliary file {a.repo_id}/{a.filename}")
        if not self.code.get("commit") or not _HEX40.match(str(self.code.get("commit"))):
            out.append("code commit pin")
        return out

    def complete(self) -> bool:
        return not self.missing()


def load_lock(engine_id: str) -> ModelLock:
    try:
        text = resources.files("aro_studio.engines.locks").joinpath(f"{engine_id}.json").read_text(encoding="utf-8")
    except FileNotFoundError as e:  # pragma: no cover - packaging error
        raise ModelError(f"No model lock for engine '{engine_id}'.") from e
    return ModelLock.model_validate(json.loads(text))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: Path, expected_sha256: str, expected_size: int | None, label: str) -> None:
    """Raise ModelError unless ``path`` matches the recorded size and SHA-256. Never returns on mismatch."""
    p = Path(path)
    if not p.is_file():
        raise ModelError(f"{label}: file not found at {p}.", recommended_action="Re-download the pinned files.")
    if expected_size is not None and p.stat().st_size != expected_size:
        raise ModelError(
            f"{label}: size {p.stat().st_size} does not match the pinned size {expected_size}.",
            recommended_action="Delete the file and download the pinned revision again. Do not load it.",
            details={"file": str(p)},
        )
    actual = sha256_file(p)
    if actual != expected_sha256:
        raise ModelError(
            f"{label}: SHA-256 mismatch (expected {expected_sha256[:16]}…, got {actual[:16]}…). The file is NOT the pinned artefact and was not loaded.",
            recommended_action="Delete the file and re-download the pinned revision; if it still differs, treat the source as compromised and stop.",
            details={"file": str(p), "expected": expected_sha256, "actual": actual},
        )


@dataclass
class ResolvedWeights:
    config: Path
    checkpoint: Path
    aux: dict[tuple[str, str], Path]  # (repo_id, filename) -> verified local path
    source: str  # "local:<dir>" or "hub:<repo>@<revision>"


Downloader = Callable[[str, str, str], str]  # (repo_id, filename, revision) -> local path


def default_downloader(repo_id: str, filename: str, revision: str) -> str:
    from huggingface_hub import hf_hub_download

    return hf_hub_download(repo_id=repo_id, filename=filename, revision=revision)


def resolve_weights(
    lock: ModelLock,
    model_path: str,
    *,
    downloader: Downloader | None = None,
    config_name: str = "config.yaml",
    ckpt_name: str = "model.ckpt",
) -> ResolvedWeights:
    """Return verified local paths for every file the engine will load, or raise ModelError.

    ``model_path`` is either a local directory (files are verified against the lock) or the lock's own repo id (files are
    downloaded at the pinned revision, then verified). Any other repo id is refused: using different weights requires a
    reviewed change to the lock.
    """
    missing = lock.missing()
    if missing:
        raise ModelError(
            "Model weights cannot be loaded: the supply-chain lock is incomplete (" + "; ".join(missing) + ").",
            recommended_action="On a host with Hugging Face access run `python scripts/pin_triposr_weights.py`, review the diff of engines/locks/triposr.json and commit it.",
            details={"missing": missing},
        )
    w = lock.weights
    local = Path(model_path)
    aux: dict[tuple[str, str], Path] = {}
    if local.is_dir():
        cfg_p, ckpt_p = local / config_name, local / ckpt_name
        source = f"local:{local}"
    elif model_path == w.repo_id:
        dl = downloader or default_downloader
        assert w.revision is not None
        cfg_p, ckpt_p = Path(dl(w.repo_id, config_name, w.revision)), Path(dl(w.repo_id, ckpt_name, w.revision))
        source = f"hub:{w.repo_id}@{w.revision}"
    else:
        raise ModelError(
            f"Refusing to load weights from '{model_path}': only the pinned repository '{w.repo_id}' or a local directory whose files match the lock are allowed.",
            recommended_action="To use other weights, update engines/locks/triposr.json through a reviewed change (new revision, checksums, licence evidence).",
        )
    for name, p in ((config_name, cfg_p), (ckpt_name, ckpt_p)):
        f = w.files[name]
        assert f.sha256 is not None
        verify_file(p, f.sha256, f.size, f"{w.repo_id}/{name}")
    for a in lock.aux_files:
        assert a.revision and a.sha256
        dl = downloader or default_downloader
        if local.is_dir() and (local / "aux" / a.repo_id.replace("/", "__") / a.filename).is_file():
            ap = local / "aux" / a.repo_id.replace("/", "__") / a.filename
        else:
            ap = Path(dl(a.repo_id, a.filename, a.revision))
        verify_file(ap, a.sha256, a.size, f"{a.repo_id}/{a.filename}")
        aux[(a.repo_id, a.filename)] = ap
    return ResolvedWeights(cfg_p, ckpt_p, aux, source)


def validate_config_classes(cfg: Any, allowed_prefix: str = "tsr.") -> list[str]:
    """Return every ``*_cls`` import path in a config tree; raise ModelError if one escapes ``allowed_prefix``.

    Upstream's ``find_class`` imports whatever dotted path the YAML names, so an unverified/tampered config could import
    arbitrary modules. The config is checksum-verified first; this is defence in depth.
    """
    found: list[str] = []

    def walk(node: Any) -> None:
        items = node.items() if hasattr(node, "items") else []
        for k, v in items:
            if hasattr(v, "items"):
                walk(v)
            elif str(k).endswith("_cls"):
                found.append(str(v))
                if not str(v).startswith(allowed_prefix):
                    raise ModelError(
                        f"Config names a class outside '{allowed_prefix}*' ({v!r}); refusing to import it.",
                        recommended_action="The config does not match the audited TripoSR layout. Stop and re-verify the weights source.",
                    )

    walk(cfg)
    return found
