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
    ram_total, ram_avail = vm.total // 2**20, vm.available // 2**20
    cg = cgroup_memory()
    if cg:  # the tighter of host and container limits is what actually applies
        ram_total = min(ram_total, cg[0])
        ram_avail = min(ram_avail, max(0, cg[0] - cg[1]))
    p = Path(data_dir)
    du = shutil.disk_usage(p if p.exists() else ".")
    return ResourceSnapshot(
        cpu_count=os.cpu_count() or 1,
        cpu_percent=psutil.cpu_percent(interval=None),
        ram_total_mb=ram_total,
        ram_available_mb=ram_avail,
        disk_total_mb=du.total // 2**20,
        disk_free_mb=du.free // 2**20,
        process_rss_mb=psutil.Process().memory_info().rss // 2**20,
        gpu=gpu_info(),
    )


_CGROUP_FILES = (
    # (limit file, usage file) for cgroup v2 then v1
    ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),
    ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "/sys/fs/cgroup/memory/memory.usage_in_bytes"),
)


def cgroup_memory() -> tuple[int, int] | None:
    """(limit_mb, used_mb) of the container's cgroup, or None when unconstrained/unavailable.

    Containers (Docker, Hugging Face Spaces) are limited by their cgroup, not by host RAM: psutil alone would
    over-report free memory and the resource preflight would green-light jobs that the kernel then OOM-kills.
    """
    for limit_f, usage_f in _CGROUP_FILES:
        try:
            raw = Path(limit_f).read_text().strip()
            if not raw.isdigit() or int(raw) >= 2**50:  # "max" or the v1 "unlimited" sentinel
                continue
            return int(raw) // 2**20, int(Path(usage_f).read_text().strip()) // 2**20
        except (OSError, ValueError):
            continue
    return None


def cgroup_memory_limit_mb() -> int | None:
    cg = cgroup_memory()
    return cg[0] if cg else None
