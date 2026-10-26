"""Engines that run on a remote GPU worker (aro_worker) and are used through the same ``ImageTo3DEngine`` contract as any local model.

Trust boundary: the worker reports its own manifest, but the LICENCE of every remote engine is taken from the table below (maintained
here and read by a person), never from the worker, so a misconfigured or hostile worker cannot claim a model is "verified". The existing
licence gate still applies: a deployer must set ARO_VERIFIED_MODEL_LICENSES after reading the model card.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
import trimesh

from aro_studio.core.errors import EngineUnavailableError, InvalidInputError, ModelError
from aro_studio.engines.base import (
    Availability,
    EngineInfo,
    GenerationOutput,
    GenerationRequest,
    ImageTo3DEngine,
    ModelLicense,
    ResourceEstimate,
)

PROTOCOL = 1
log = logging.getLogger(__name__)

KNOWN: dict[str, dict[str, Any]] = {
    "trellis2": {
        "name": "TRELLIS.2 (4B, PBR) - remote GPU",
        "license": ModelLicense(
            spdx="MIT",
            source_url="https://github.com/microsoft/TRELLIS.2/blob/main/LICENSE",
            commercial_use="allowed",
            status="claimed",
            notes="Code MIT (read 2026-10). Weights licence: read the model card before setting ARO_VERIFIED_MODEL_LICENSES. nvdiffrec "
            "(non-commercial) must not be installed on the worker; DINOv3 conditioning weights are gated (Meta licence).",
        ),
        "description": "Microsoft TRELLIS.2: 4B-parameter image-to-3D with native PBR materials (up to 1536^3). Needs a 24 GB-class GPU.",
        "source_url": "https://github.com/microsoft/TRELLIS.2",
    },
    "triposg": {
        "name": "TripoSG (1.5B, geometry) - remote GPU",
        "license": ModelLicense(
            spdx="MIT",
            source_url="https://github.com/VAST-AI-Research/TripoSG/blob/main/LICENSE",
            commercial_use="allowed",
            status="claimed",
            notes="Code MIT. Weights licence: read the model card. BRIA RMBG-1.4 (non-commercial) is not used. Geometry only: no texture.",
        ),
        "description": "VAST-AI TripoSG: high-resolution geometry from one image (~8 GB VRAM); the Studio adds colour from the reference image.",
        "source_url": "https://github.com/VAST-AI-Research/TripoSG",
    },
    "fake": {
        "name": "TEST DOUBLE (procedural, NOT AI) - remote",
        "license": ModelLicense("MIT", "https://github.com/", "allowed", "claimed", "test double"),
        "description": "Procedural stand-in used to test the worker protocol. Not AI.",
        "source_url": "https://github.com/",
    },
}


class RemoteEngine(ImageTo3DEngine):
    def __init__(
        self,
        base_url: str,
        token: str,
        engine_id: str,
        *,
        client: httpx.Client | None = None,
        poll_s: float = 1.0,
        timeout_s: float = 3600.0,
        availability_ttl_s: float = 5.0,
    ) -> None:
        if engine_id not in KNOWN:
            raise InvalidInputError(
                f"Unknown remote engine '{engine_id}'.", recommended_action=f"Known: {sorted(KNOWN)}"
            )
        self.engine_id, self.base_url, self._token = engine_id, base_url.rstrip("/"), token
        self._client = client or httpx.Client(timeout=httpx.Timeout(60.0, read=600.0))
        self.poll_s, self.timeout_s, self.availability_ttl_s = poll_s, timeout_s, availability_ttl_s
        self._av: tuple[float, Availability] | None = None
        k = KNOWN[engine_id]
        self.info = EngineInfo(
            id=engine_id,
            name=k["name"],
            capability="image_to_3d",
            version=f"{engine_id}@remote-unresolved",
            revision=None,
            source_url=k["source_url"],
            license=k["license"],
            description=k["description"],
            requirements={"remote_worker": self.base_url, "protocol": PROTOCOL},
        )
        self._manifest: dict[str, Any] | None = None
        self._manifest_at = 0.0
        self._loaded = False

    # -- http ------------------------------------------------------------------------------------
    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _engines(self, max_age_s: float = 20.0) -> dict[str, Any]:
        if self._manifest is not None and time.time() - self._manifest_at < max_age_s:
            return self._manifest
        r = self._client.get(f"{self.base_url}/v1/engines", headers=self._h())
        if r.status_code == 401:
            raise EngineUnavailableError(
                "The GPU worker rejected the token.", recommended_action="Set ARO_WORKER_TOKEN to the worker's token."
            )
        r.raise_for_status()
        self._manifest, self._manifest_at = r.json(), time.time()
        return self._manifest

    def _mine(self) -> dict[str, Any] | None:
        for e in self._engines().get("engines", []):
            if e["id"] == self.engine_id:
                return e
        return None

    # -- contract --------------------------------------------------------------------------------
    def availability(self, device: str) -> Availability:
        """Cached for a few seconds: the UI asks for every engine's status on each page load, and an unreachable worker must not
        stall each of those requests for a full network timeout."""
        now = time.time()
        if self._av is not None and now - self._av[0] < self.availability_ttl_s:
            return self._av[1]
        av = self._availability()
        self._av = (now, av)
        return av

    def _availability(self) -> Availability:
        how = [
            "Start the GPU worker (docs/architecture/gpu-worker.md) and set ARO_WORKER_URL and ARO_WORKER_TOKEN for the Studio.",
        ]
        try:
            ping = self._client.get(f"{self.base_url}/ping", timeout=4.0)
            ping.raise_for_status()
        except (httpx.HTTPError, ValueError) as e:
            return Availability(
                False, [f"The GPU worker at {self.base_url} is not reachable ({type(e).__name__})."], [], how
            )
        try:
            m = self._mine()
            manifest = self._engines()
        except EngineUnavailableError as e:
            return Availability(False, [e.message], [], how)
        except (httpx.HTTPError, ValueError) as e:
            return Availability(False, [f"The GPU worker answered badly ({type(e).__name__}: {e})."], [], how)
        if manifest.get("protocol") != PROTOCOL:
            return Availability(
                False, [f"Worker protocol {manifest.get('protocol')} != Studio protocol {PROTOCOL}."], [], how
            )
        if m is None:
            ids = [e["id"] for e in manifest.get("engines", [])]
            return Availability(False, [f"The worker does not offer '{self.engine_id}' (it offers {ids})."], [], how)
        self._adopt_version(m.get("version"))
        warn = [str(w) for w in m.get("warnings", [])]
        gpu = manifest.get("gpu") or {}
        if gpu:
            warn.append(f"runs on the worker GPU: {gpu.get('name')} ({gpu.get('total_mb')} MB)")
        if not m.get("available"):
            return Availability(
                False,
                [str(r) for r in m.get("reasons", [])] or ["the worker reports the engine unavailable"],
                warn,
                how,
            )
        self._loaded = True
        return Availability(True, [], warn, [])

    def _adopt_version(self, version: str | None) -> None:
        if version and version != self.info.version:
            self.info = EngineInfo(**{**self.info.__dict__, "version": version})

    def presets(self) -> dict[str, dict[str, Any]]:
        try:
            m = self._mine()
            if m and m.get("presets"):
                return {k: dict(v) for k, v in m["presets"].items()}
        except (EngineUnavailableError, httpx.HTTPError, ValueError):
            pass
        return {"STANDARD": {}}

    def normalize_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        presets = self.presets()
        name = str(settings.get("preset") or "STANDARD")
        if name not in presets:
            raise InvalidInputError(f"Unknown preset '{name}'.", recommended_action=f"Use one of {sorted(presets)}")
        out = dict(presets[name])
        for k, v in settings.items():
            if k in out and v is not None:
                try:
                    out[k] = type(out[k])(v)
                except (TypeError, ValueError):
                    raise InvalidInputError(f"Setting '{k}' has an invalid value.") from None
        out["preset"] = name
        out["foreground_ratio"] = float(settings.get("foreground_ratio", 0.85))  # the Studio's own preprocessing input
        return out

    def estimate_resources(self, settings: dict[str, Any], device: str) -> ResourceEstimate:
        return ResourceEstimate(None, None, False, "runs on the remote GPU worker (its own resource check applies)")

    def load(self, device: str) -> None:
        self._av = None  # a real load is a fresh check
        av = self.availability(device)
        if not av.ok:
            raise EngineUnavailableError(" ".join(av.reasons), recommended_action=" ".join(av.activation))
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def generate(self, request: GenerationRequest) -> GenerationOutput:
        t0 = time.perf_counter()
        s = self.normalize_settings(request.settings)
        sent = {k: v for k, v in s.items() if k != "foreground_ratio"}
        img = (request.cutout or request.image).convert("RGBA")
        alpha: Any = img.getchannel("A").getextrema()  # (min, max)
        if int(alpha[0]) >= 250:
            raise InvalidInputError(
                f"{self.info.name} needs the subject cut out of its background, but this image has no transparency.",
                recommended_action="Set background removal to Automatic (or a plain-background matte), or upload an image with a transparent background.",
            )
        buf = io.BytesIO()
        img.save(buf, "PNG")
        if request.progress:
            request.progress(0.02, f"Sending the image to the GPU worker ({self.engine_id})")
        try:
            r = self._client.post(
                f"{self.base_url}/v1/generate",
                headers=self._h(),
                files={"image": ("input.png", buf.getvalue(), "image/png")},
                data={"engine": self.engine_id, "settings": json.dumps(sent)},
            )
        except httpx.HTTPError as e:
            raise EngineUnavailableError(f"The GPU worker is not reachable ({type(e).__name__}).") from e
        if r.status_code == 409:
            raise EngineUnavailableError(f"The worker refused the job: {r.json().get('detail')}")
        if r.status_code >= 400:
            raise ModelError(f"The worker rejected the request ({r.status_code}): {r.text[:300]}")
        jid = r.json()["job_id"]
        job = self._wait(jid, request)
        res = self._client.get(f"{self.base_url}/v1/jobs/{jid}/result", headers=self._h())
        res.raise_for_status()
        want = res.headers.get("X-ARO-SHA256") or job.get("sha256")
        got = hashlib.sha256(res.content).hexdigest()
        if want and want != got:
            raise ModelError(
                "The GLB received from the worker does not match its checksum.",
                recommended_action="Retry; check the network path.",
            )
        details = job.get("details") or {}
        self._adopt_version(details.get("engine_version"))
        request.workdir.mkdir(parents=True, exist_ok=True)
        raw = request.workdir / "raw_output.glb"
        raw.write_bytes(res.content)  # the engine's artefact, untouched
        mesh = _load_single_mesh(raw)
        if len(mesh.faces) == 0:
            raise ModelError("The worker returned an empty mesh.")
        gpu = (details.get("gpu") or {}).get("name") or "remote"
        return GenerationOutput(
            raw_file=raw,
            output_format="glb",
            mesh=mesh,
            device=f"remote:{gpu}",
            execution_time_s=time.perf_counter() - t0,
            details={
                "remote_worker": self.base_url,
                "engine_version": details.get("engine_version"),
                "worker_seconds": details.get("seconds"),
                "peak_vram_allocated_mb": details.get("peak_vram_allocated_mb"),
                "pbr": details.get("pbr"),
                "worker_details": {k: v for k, v in details.items() if k not in ("gpu",)},
                "coordinate_frame": "engine native (glTF, +Y up as written by the worker)",
                "extents": [float(x) for x in mesh.extents],
            },
        )

    def _abandon(self, jid: str) -> None:
        """Best effort: tell the worker to stop a job nobody is waiting for any more (it would otherwise hold the GPU)."""
        try:
            self._client.delete(f"{self.base_url}/v1/jobs/{jid}", headers=self._h())
        except httpx.HTTPError:
            pass

    def _wait(self, jid: str, request: GenerationRequest) -> dict[str, Any]:
        end = time.time() + self.timeout_s
        while time.time() < end:
            if request.cancel:
                try:
                    request.cancel.check()  # cancelled or timed out in the Studio
                except Exception:
                    self._abandon(jid)
                    raise
            r = self._client.get(f"{self.base_url}/v1/jobs/{jid}", headers=self._h())
            r.raise_for_status()
            j = r.json()
            if request.progress:
                wait = f" (queue position {j['queue_position']})" if j.get("queue_position") else ""
                request.progress(0.05 + 0.9 * float(j.get("progress", 0)), f"GPU worker: {j.get('message', '')}{wait}")
            if j["state"] == "done":
                return j
            if j["state"] in ("failed", "cancelled"):
                raise ModelError(
                    f"The GPU worker {j['state']}: {j.get('error') or 'cancelled'}",
                    recommended_action="See the worker log.",
                )
            time.sleep(self.poll_s)
        raise ModelError(
            "The GPU worker did not finish in time.",
            recommended_action="Raise the job timeout or use a smaller preset.",
        )


def _load_single_mesh(path: Path) -> trimesh.Trimesh:
    """One mesh for the Studio's raw version. Texture colours become vertex colours so the existing preparation bakes them; the full
    PBR GLB stays untouched next to it (raw_output.glb)."""
    loaded: Any = trimesh.load(str(path), force="scene")
    geoms = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh) and len(g.faces)]
    if not geoms:
        raise ModelError("The GLB from the worker contains no mesh.")
    parts = []
    for g in geoms:
        g = g.copy()
        try:
            visual: Any = g.visual
            if getattr(visual, "kind", None) == "texture":
                g.visual = visual.to_color()  # texture -> per-vertex colour
        except Exception:  # noqa: BLE001 - colourless geometry is still valid output
            g.visual = trimesh.visual.ColorVisuals(mesh=g)
        parts.append(g)
    mesh: trimesh.Trimesh = trimesh.util.concatenate(parts) if len(parts) > 1 else parts[0]  # type: ignore[assignment]
    return mesh


def remote_engines(
    base_url: str, token: str, engine_ids: list[str], *, client: httpx.Client | None = None
) -> list[RemoteEngine]:
    """One RemoteEngine per configured id; unknown ids are skipped with a log line rather than breaking Studio start-up."""
    out: list[RemoteEngine] = []
    shared = client or httpx.Client(timeout=httpx.Timeout(60.0, read=600.0))
    for eid in engine_ids:
        eid = eid.strip()
        if not eid:
            continue
        if eid not in KNOWN:
            log.warning("ARO_WORKER_ENGINES: unknown remote engine '%s' ignored (known: %s)", eid, sorted(KNOWN))
            continue
        out.append(RemoteEngine(base_url, token, eid, client=shared))
    return out
