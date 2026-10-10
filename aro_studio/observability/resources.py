"""Resource monitoring: CPU, RAM, disk, GPU/VRAM (spec §30)."""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: S404
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil


@dataclass
class GpuInfo:
    available: bool = False
    name: str | None = None
    total_mb: int | None = None
    free_mb: int | None = None
    driver: str | None = None
    source: str = "none"


@dataclass
class ResourceSnapshot:
    cpu_count: int
    cpu_percent: float
    ram_total_mb: int
    ram_available_mb: int
    disk_total_mb: int
    disk_free_mb: int
    process_rss_mb: int
    gpu: GpuInfo = field(default_factory=GpuInfo)
    torch_cuda: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def gpu_info() -> GpuInfo:
    """Query the GPU via ``nvidia-smi`` (no torch import needed, so safe on CPU-only hosts)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return GpuInfo()
    try:
        out = (
            subprocess.run(  # noqa: S603
                [exe, "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            .stdout.strip()
            .splitlines()
        )
        name, total, free, driver = [x.strip() for x in out[0].split(",")]
        return GpuInfo(True, name, int(total), int(free), driver, "nvidia-smi")
    except Exception:  # noqa: BLE001 - monitoring must never raise
        return GpuInfo()


def snapshot(data_dir: str | Path = ".") -> ResourceSnapshot:
    vm = psutil.virtual_memory()
    p = Path(data_dir)
    du = shutil.disk_usage(p if p.exists() else ".")
    return ResourceSnapshot(
        cpu_count=os.cpu_count() or 1,
        cpu_percent=psutil.cpu_percent(interval=None),
        ram_total_mb=vm.total // 2**20,
        ram_available_mb=vm.available // 2**20,
        disk_total_mb=du.total // 2**20,
        disk_free_mb=du.free // 2**20,
        process_rss_mb=psutil.Process().memory_info().rss // 2**20,
        gpu=gpu_info(),
    )


def cgroup_memory_limit_mb() -> int | None:
    """Containers (HF Spaces) are limited by cgroups, not by host RAM."""
    for f in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            v = Path(f).read_text().strip()
            if v.isdigit() and int(v) < 2**50:
                return int(v) // 2**20
        except OSError:
            continue
    return None
