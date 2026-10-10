"""RAM telemetry for the 16 GB AN515-45 (psutil-based)."""
from __future__ import annotations

from dataclasses import dataclass

import psutil


@dataclass
class RamSample:
    """One memory telemetry sample (all sizes in bytes)."""
    total: int = 0
    used: int = 0
    available: int = 0
    percent: float = 0.0
    swap_total: int = 0
    swap_used: int = 0
    swap_percent: float = 0.0

    @property
    def used_gb(self) -> float:
        """Used memory in GiB."""
        return self.used / (1024 ** 3)

    @property
    def total_gb(self) -> float:
        """Total memory in GiB."""
        return self.total / (1024 ** 3)


class RamMonitor:
    """Wraps psutil memory counters."""

    def sample(self) -> RamSample:
        """Collect one memory sample (non-blocking)."""
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        return RamSample(
            total=vm.total, used=vm.used, available=vm.available, percent=vm.percent,
            swap_total=sw.total, swap_used=sw.used, swap_percent=sw.percent,
        )
