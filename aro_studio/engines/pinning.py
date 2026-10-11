"""Pin model weights: resolve a Hub revision, download, hash, cross-check, and update the lock (never by hand).

Run through ``scripts/pin_triposr_weights.py`` on a host with Hugging Face access. The Hub is abstracted so the logic is
unit-tested without network access.
"""

from __future__ import annotations

import copy
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from aro_studio.core.errors import ModelError
from aro_studio.engines.weights import ModelLock, sha256_file


@dataclass
class HubInfo:
    sha: str  # commit hash of the revision
    license: str | None  # model-card licence tag
    files: dict[str, dict[str, Any]]  # filename -> {"sha256": hub-reported LFS sha or None, "size": int | None}


class HubClient(Protocol):
    def model_info(self, repo_id: str, revision: str | None) -> HubInfo: ...
    def download(self, repo_id: str, filename: str, revision: str) -> Path: ...


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read an API field from both dict payloads (older huggingface_hub) and objects (newer versions)."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


class RealHub:
    """huggingface_hub-backed client (imported lazily so the Studio runs without it)."""

    def __init__(self, token: str | None = None):
        self.token = token

    def model_info(self, repo_id: str, revision: str | None) -> HubInfo:
        from huggingface_hub import HfApi

        info = HfApi(token=self.token).model_info(repo_id, revision=revision, files_metadata=True)
        files: dict[str, dict[str, Any]] = {}
        for sib in info.siblings or []:
            filename = _field(sib, "rfilename")
            if not isinstance(filename, str) or not filename:
                raise ModelError(f"Hugging Face returned a sibling without a valid filename for {repo_id}.")
            lfs = _field(sib, "lfs")
            # LFS metadata can be either a nested dict or an object. Preserve the raw value;
            # the pinning step still hashes the downloaded bytes and compares when a SHA is supplied.
            hub_sha = _field(lfs, "sha256") if lfs is not None else None
            size = _field(sib, "size")
            files[filename] = {
                "sha256": hub_sha if isinstance(hub_sha, str) else None,
                "size": size if isinstance(size, int) and not isinstance(size, bool) else None,
            }
        card = getattr(info, "card_data", None)
        license_tag = _field(card, "license") if card is not None else None
        return HubInfo(
            sha=str(info.sha),
            license=license_tag if isinstance(license_tag, str) else None,
            files=files,
        )

    def download(self, repo_id: str, filename: str, revision: str) -> Path:
        from huggingface_hub import hf_hub_download

        return Path(hf_hub_download(repo_id=repo_id, filename=filename, revision=revision, token=self.token))


def pin_lock(
    lock: ModelLock, hub: HubClient, *, by: str, revision: str | None = None, today: str | None = None
) -> dict[str, Any]:
    """Return the updated lock JSON (as a dict). Raises ModelError on any inconsistency; writes nothing."""
    today = today or dt.date.today().isoformat()
    out: dict[str, Any] = copy.deepcopy(lock.model_dump(by_alias=True, mode="json"))
    w = lock.weights
    info = hub.model_info(w.repo_id, revision)
    rev = info.sha
    if len(rev) != 40:
        raise ModelError(f"Hub returned an invalid commit hash for {w.repo_id}: {rev!r}")
    if revision and revision != rev:
        raise ModelError(f"Requested revision {revision} but the Hub resolved {rev}.")
    files: dict[str, dict[str, Any]] = {}
    for name in w.files:
        if name not in info.files:
            raise ModelError(f"{w.repo_id}/{name}: file is not listed at the resolved Hub revision {rev}.")
        path = hub.download(w.repo_id, name, rev)
        digest, size = sha256_file(path), path.stat().st_size
        hub_sha = info.files.get(name, {}).get("sha256")
        if hub_sha and hub_sha != digest:
            raise ModelError(
                f"{w.repo_id}/{name}: downloaded SHA-256 {digest[:16]}… differs from the Hub-reported {hub_sha[:16]}…; aborting (corrupt or tampered download)."
            )
        hub_size = info.files.get(name, {}).get("size")
        if hub_size is not None and hub_size != size:
            raise ModelError(f"{w.repo_id}/{name}: downloaded size {size} differs from the Hub-reported {hub_size}.")
        files[name] = {"sha256": digest, "size": size, "hub_reported_sha256": hub_sha}
    out["weights"].update(revision=rev, pinned_on=today, pinned_by=by)
    out["weights"]["files"] = {k: {"sha256": v["sha256"], "size": v["size"]} for k, v in files.items()}
    for i, a in enumerate(lock.aux_files):
        ainfo = hub.model_info(a.repo_id, a.revision)
        if a.filename not in ainfo.files:
            raise ModelError(f"{a.repo_id}/{a.filename}: file is not listed at the resolved Hub revision {ainfo.sha}.")
        apath = hub.download(a.repo_id, a.filename, ainfo.sha)
        aux_digest, aux_size = sha256_file(apath), apath.stat().st_size
        hub_aux = ainfo.files.get(a.filename, {})
        if hub_aux.get("sha256") and hub_aux["sha256"] != aux_digest:
            raise ModelError(
                f"{a.repo_id}/{a.filename}: downloaded SHA-256 differs from the Hub-reported checksum; aborting."
            )
        if hub_aux.get("size") is not None and hub_aux["size"] != aux_size:
            raise ModelError(
                f"{a.repo_id}/{a.filename}: downloaded size {aux_size} differs from the Hub-reported {hub_aux['size']}."
            )
        out["aux_files"][i].update(revision=ainfo.sha, sha256=aux_digest, size=aux_size)
    # The Hub's own licence tag at the pinned revision is independent evidence (machine-fetched, not typed in).
    if info.license:
        out["license"]["evidence"].append(
            {
                "source": f"https://huggingface.co/{w.repo_id}/tree/{rev}",
                "finding": f"Model card licence tag at the pinned revision: '{info.license}' (fetched via the Hub API).",
                "file_sha256": None,
                "verified_on": today,
                "verified_by": f"scripts/pin_triposr_weights.py run by {by}",
                "independently_fetched": True,
            }
        )
        if info.license.lower() != lock.license.spdx.lower():
            raise ModelError(
                f"Hub licence tag '{info.license}' differs from the recorded licence '{lock.license.spdx}'. Stop and review before pinning."
            )
    out["_pin_report"] = {"files": files, "revision": rev}
    return out
