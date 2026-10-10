"""NVIDIA GTX 1650 telemetry: pynvml primary, nvidia-smi CSV fallback.

Units are converted to app-standard: temp °C, fan %, clocks MHz, memory bytes, power W.
"""
from __future__ import annotations

import csv
import io
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from nitromaster.utils.logging_setup import get_logger
from nitromaster.utils.platform import IS_WINDOWS

log = get_logger("nvidia")


@dataclass
class NvidiaSample:
    """One GTX 1650 telemetry sample; None fields = not available (e.g. dGPU powered down)."""
    name: str = ""
    temp_c: Optional[float] = None
    fan_pct: Optional[float] = None
    core_mhz: Optional[float] = None
    mem_mhz: Optional[float] = None
    mem_used: Optional[int] = None
    mem_total: Optional[int] = None
    power_w: Optional[float] = None
    power_limit_w: Optional[float] = None
    util_gpu: Optional[float] = None
    util_mem: Optional[float] = None
    driver: str = ""
    error: str = ""


class NvidiaBackend:
    """Lazy NVML wrapper with sleep/resume recovery and a CLI fallback."""

    def __init__(self) -> None:
        self.available = False
        self._pynvml = None
        self._handle = None
        self._init_nvml()

    def _init_nvml(self) -> None:
        try:
            import pynvml  # nvidia-ml-py
            pynvml.nvmlInit()
            self._pynvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.available = True
        except Exception as exc:
            log.info("NVML unavailable: %s", exc)
            self.available = False

    def _recover(self) -> bool:
        """Re-init NVML after GpuIsLost (sleep/resume) and re-acquire the handle."""
        try:
            self._pynvml.nvmlShutdown()
            self._pynvml.nvmlInit()
            self._handle = self._pynvml.nvmlDeviceGetHandleByIndex(0)
            return True
        except Exception:
            self.available = False
            return False

    def sample(self) -> NvidiaSample:
        """Collect one GPU sample via NVML, falling back to nvidia-smi."""
        if self.available:
            s = self._sample_nvml()
            if s.error == "":
                return s
            if s.error == "GPU_IS_LOST" and self._recover():
                s = self._sample_nvml()
                if s.error == "":
                    return s
        return self._sample_smi()

    def _sample_nvml(self) -> NvidiaSample:
        """Read all NVML metrics; Optimus power-down surfaces as NOT_SUPPORTED fields."""
        p = self._pynvml
        s = NvidiaSample()
        try:
            name = p.nvmlDeviceGetName(self._handle)
            s.name = name.decode() if isinstance(name, bytes) else str(name)
            def safe(fn, default=None):
                try:
                    return fn()
                except p.NVMLError_NotSupported:
                    return default
                except Exception:
                    return default
            s.temp_c = safe(lambda: float(p.nvmlDeviceGetTemperature(self._handle, p.NVML_TEMPERATURE_GPU)))
            s.fan_pct = safe(lambda: float(p.nvmlDeviceGetFanSpeed(self._handle)))
            s.core_mhz = safe(lambda: float(p.nvmlDeviceGetClockInfo(self._handle, p.NVML_CLOCK_GRAPHICS)))
            s.mem_mhz = safe(lambda: float(p.nvmlDeviceGetClockInfo(self._handle, p.NVML_CLOCK_MEM)))
            mem = safe(lambda: p.nvmlDeviceGetMemoryInfo(self._handle))
            if mem is not None:
                s.mem_used, s.mem_total = int(mem.used), int(mem.total)
            s.power_w = safe(lambda: p.nvmlDeviceGetPowerUsage(self._handle) / 1000.0)
            s.power_limit_w = safe(lambda: p.nvmlDeviceGetEnforcedPowerLimit(self._handle) / 1000.0)
            util = safe(lambda: p.nvmlDeviceGetUtilizationRates(self._handle))
            if util is not None:
                s.util_gpu, s.util_mem = float(util.gpu), float(util.memory)
            try:
                drv = p.nvmlSystemGetDriverVersion()
                s.driver = drv.decode() if isinstance(drv, bytes) else str(drv)
            except Exception:
                pass
            return s
        except p.NVMLError_GpuIsLost:
            s.error = "GPU_IS_LOST"
            return s
        except Exception as exc:
            s.error = f"NVML_ERROR: {exc}"
            return s

    def _sample_smi(self) -> NvidiaSample:
        """nvidia-smi CSV fallback (power fields in W here, unlike NVML's mW)."""
        s = NvidiaSample()
        exe = shutil.which("nvidia-smi")
        if not exe:
            s.error = "nvidia-smi not found"
            return s
        query = ("name,temperature.gpu,fan.speed,clocks.gr,clocks.mem,"
                 "utilization.gpu,utilization.memory,memory.used,memory.total,"
                 "power.draw,power.limit,driver_version")
        try:
            out = subprocess.run(
                [exe, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
            )
            if out.returncode != 0 or not out.stdout.strip():
                s.error = "nvidia-smi returned no data"
                return s
            row = next(csv.reader(io.StringIO(out.stdout)))
            vals = [v.strip() for v in row]
            def num(i):
                try:
                    return float(vals[i])
                except (ValueError, IndexError):
                    return None
            s.name, s.temp_c, s.fan_pct = vals[0], num(1), num(2)
            s.core_mhz, s.mem_mhz = num(3), num(4)
            s.util_gpu, s.util_mem = num(5), num(6)
            s.mem_used, s.mem_total = num(7), num(8)
            s.power_w, s.power_limit_w = num(9), num(10)
            s.driver = vals[11] if len(vals) > 11 else ""
            return s
        except Exception as exc:
            s.error = f"nvidia-smi failed: {exc}"
            return s

    def close(self) -> None:
        """Shut NVML down (never raises)."""
        try:
            if self._pynvml and self.available:
                self._pynvml.nvmlShutdown()
        except Exception:
            pass
