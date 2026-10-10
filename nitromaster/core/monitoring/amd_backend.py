"""AMD Radeon Vega iGPU (Cezanne) telemetry via LibreHardwareMonitor + WMI static info.

There is no NVML-equivalent for AMD; LHM/ADL2 is the verified path (see docs/research/03).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from nitromaster.core.monitoring.sensors_backend import LhmBridge
from nitromaster.utils.logging_setup import get_logger
from nitromaster.utils.platform import IS_WINDOWS

log = get_logger("amd")


@dataclass
class AmdSample:
    """One Radeon iGPU telemetry sample."""
    name: str = ""
    temp_c: Optional[float] = None
    core_mhz: Optional[float] = None
    mem_mhz: Optional[float] = None
    load_pct: Optional[float] = None
    fan_pct: Optional[float] = None
    driver: str = ""
    error: str = ""


class AmdBackend:
    """Reads GpuAmd sensors from LHM; static identity from Win32_VideoController."""

    def __init__(self, lhm: Optional[LhmBridge] = None) -> None:
        self.lhm = lhm
        self.name = "AMD Radeon Graphics"
        self.driver = ""
        self._read_static()

    def _read_static(self) -> None:
        """Fill name/driver from WMI (static data only; no live sensors there)."""
        if not IS_WINDOWS:
            return
        try:
            import wmi  # Windows-only
            for vc in wmi.WMI().Win32_VideoController():
                n = (vc.Name or "")
                if "amd" in n.lower() or "radeon" in n.lower():
                    self.name = n
                    self.driver = vc.DriverVersion or ""
        except Exception as exc:
            log.debug("WMI video controller query failed: %s", exc)

    def sample(self) -> AmdSample:
        """Collect one iGPU sample; empty values when LHM is unavailable."""
        s = AmdSample(name=self.name, driver=self.driver)
        if self.lhm is None or not self.lhm.available:
            s.error = "LibreHardwareMonitor unavailable"
            return s
        sensors = self.lhm.read()
        for key, val in sensors.items():
            grp, name = key
            if grp != "gpu":
                continue
            low = name.lower()
            if "temperature" in low and s.temp_c is None:
                s.temp_c = val
            elif "core" in low and "clock" in low and s.core_mhz is None:
                s.core_mhz = val
            elif "memory" in low and "clock" in low and s.mem_mhz is None:
                s.mem_mhz = val
            elif low in ("load", "gpu load") and s.load_pct is None:
                s.load_pct = val
            elif "fan" in low and s.fan_pct is None:
                s.fan_pct = val
        return s

    def close(self) -> None:
        """No owned resources (LHM lifetime belongs to the owner of the bridge)."""
        return
