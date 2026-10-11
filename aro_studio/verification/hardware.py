"""Hardware/runtime facts and GPU memory sampling for verification evidence (no torch import unless it is installed)."""

from __future__ import annotations

import platform
import subprocess
import sys
import threading


def sh(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False).stdout.strip() or None  # noqa: S603 - fixed argv, no shell
    except (OSError, subprocess.SubprocessError):
        return None


class VramPoller(threading.Thread):
    """Samples nvidia-smi (all processes on the GPU) so the peak is not only torch's own allocator view."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak_mb = 0
        self.samples = 0
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            out = sh(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"])
            if out:
                try:
                    self.peak_mb = max(self.peak_mb, max(int(x) for x in out.split()))
                    self.samples += 1
                except ValueError:
                    pass
            self._stop.wait(0.5)

    def stop(self) -> None:
        self._stop.set()


def environment() -> dict:
    env: dict = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
        "nvidia_smi": sh(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"]),
        "torch": None,
        "cuda": None,
    }
    try:
        import torch

        env["torch"] = torch.__version__
        env["cuda"] = {
            "available": bool(torch.cuda.is_available()),
            "version": torch.version.cuda,
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "total_vram_mb": int(torch.cuda.get_device_properties(0).total_memory / 2**20)
            if torch.cuda.is_available()
            else None,
        }
    except Exception as e:  # noqa: BLE001
        env["torch_error"] = f"{type(e).__name__}: {e}"
    try:
        import tsr  # noqa: F401

        env["tsr_importable"] = True
    except Exception as e:  # noqa: BLE001
        env["tsr_importable"] = False
        env["tsr_error"] = f"{type(e).__name__}: {e}"
    from importlib import metadata

    pk: dict[str, str | None] = {}
    for name in (
        "torch",
        "torchvision",
        "transformers",
        "omegaconf",
        "einops",
        "huggingface-hub",
        "numpy",
        "trimesh",
        "pillow",
        "rembg",
        "onnxruntime",
        "torchmcubes",
        "xatlas",
    ):
        try:
            pk[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pk[name] = None
    env["packages"] = pk
    return env
