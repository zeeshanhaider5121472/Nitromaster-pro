"""CPU telemetry: usage (psutil), effective clocks (PDH), temperature (Acer WMI -> LHM)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import psutil

from nitromaster.core.monitoring.sensors_backend import (
    AcerSensorReading, AcerWmiBackend, AcerWmiError, LhmBridge,
)
from nitromaster.utils.logging_setup import get_logger
from nitromaster.utils.platform import IS_WINDOWS

log = get_logger("cpu")

NOMINAL_MHZ = 3300  # Ryzen 5 5600H base clock (CPUID leaf 0x16); UI reference only


@dataclass
class CpuSample:
    """One CPU telemetry sample."""
    usage_total: float = 0.0
    usage_per_core: list[float] = field(default_factory=list)
    effective_mhz: Optional[float] = None
    nominal_mhz: int = NOMINAL_MHZ
    temp_c: Optional[float] = None
    temp_source: str = "none"
    core_count: int = 0
    thread_count: int = 0


class PerfCounterReader:
    """Windows PDH reader for '\\Processor Information(*)\\% Processor Performance'.

    Effective frequency = nominal MHz * %ProcessorPerformance / 100 (Task-Manager semantics).
    """

    def __init__(self) -> None:
        self.available = False
        self._query = None
        self._counters: dict[str, int] = {}
        if not IS_WINDOWS:
            return
        try:
            import win32pdh  # Windows-only
            self._win32pdh = win32pdh
            path_total = r"\Processor Information(_Total)\% Processor Performance"
            q = win32pdh.OpenQuery()
            h = win32pdh.AddCounter(q, path_total, 0)
            self._query = q
            self._counters["_total"] = h
            # Per-core instances "0,0".."N,0" (NUMA,core); tolerate missing ones.
            for i in range(psutil.cpu_count(logical=True) or 0):
                try:
                    self._counters[str(i)] = win32pdh.AddCounter(
                        q, rf"\Processor Information({i},0)\% Processor Performance", 0
                    )
                except Exception:
                    continue
            win32pdh.CollectQueryData(q)
            self.available = True
        except Exception as exc:
            log.info("PDH counters unavailable: %s", exc)
            self.available = False

    def read_percent(self) -> dict[str, float]:
        """Return {'_total': pct, '0': pct, ...}; empty dict when unavailable."""
        if not self.available:
            return {}
        out: dict[str, float] = {}
        try:
            self._win32pdh.CollectQueryData(self._query)
            for name, handle in self._counters.items():
                _status, value = self._win32pdh.GetFormattedCounterValue(handle, self._win32pdh.PDH_FMT_DOUBLE)
                out[name] = float(value)
        except Exception as exc:
            log.debug("PDH read failed: %s", exc)
        return out

    def close(self) -> None:
        """Release the PDH query (never raises)."""
        try:
            if self._query is not None:
                self._win32pdh.CloseQuery(self._query)
        except Exception:
            pass


class CpuMonitor:
    """Aggregates CPU usage, effective clocks and temperature from the best available source."""

    def __init__(self, acer: Optional[AcerWmiBackend] = None,
                 lhm: Optional[LhmBridge] = None) -> None:
        self.acer = acer
        self.lhm = lhm
        self.pdh = PerfCounterReader()
        self._cpu_count = psutil.cpu_count(logical=True) or 1
        psutil.cpu_percent(interval=None, percpu=True)  # prime the sampler

    def sample(self) -> CpuSample:
        """Collect one CPU sample (non-blocking)."""
        s = CpuSample(
            usage_total=psutil.cpu_percent(interval=None),
            usage_per_core=psutil.cpu_percent(interval=None, percpu=True),
            core_count=psutil.cpu_count(logical=False) or 0,
            thread_count=self._cpu_count,
            nominal_mhz=NOMINAL_MHZ,
        )
        pct = self.pdh.read_percent()
        if "_total" in pct:
            s.effective_mhz = NOMINAL_MHZ * pct["_total"] / 100.0
        self._fill_temperature(s)
        return s

    def _fill_temperature(self, s: CpuSample) -> None:
        """Temperature fallback chain: Acer firmware Tctl -> LHM 'CPU Package' -> None."""
        if self.acer is not None:
            try:
                reading: AcerSensorReading = self.acer.read_sensors()
                if reading.cpu_temp_c is not None:
                    s.temp_c = reading.cpu_temp_c
                    s.temp_source = "acer-wmi"
                    return
            except AcerWmiError as exc:
                log.debug("Acer temp read failed: %s", exc)
        if self.lhm is not None and self.lhm.available:
            sensors = self.lhm.read()
            for key in (("cpu", "CPU Package"), ("cpu", "Core Average"), ("cpu", "Tctl")):
                if key in sensors:
                    s.temp_c = sensors[key]
                    s.temp_source = "librehardwaremonitor"
                    return
            for (_grp, name), val in sensors.items():
                if name.lower().startswith("core") and "temperature" in name.lower():
                    s.temp_c = val
                    s.temp_source = "librehardwaremonitor"
                    return

    def close(self) -> None:
        """Release underlying handles."""
        self.pdh.close()
