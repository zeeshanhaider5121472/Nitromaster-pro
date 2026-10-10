"""Combined GPU telemetry for the GTX 1650 (dGPU) and Radeon Vega (iGPU)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from nitromaster.core.monitoring.amd_backend import AmdBackend, AmdSample
from nitromaster.core.monitoring.nvidia_backend import NvidiaBackend, NvidiaSample
from nitromaster.core.monitoring.sensors_backend import (
    AcerSensorReading, AcerWmiBackend, AcerWmiError, LhmBridge, SYS_GPU_TEMP,
)
from nitromaster.utils.logging_setup import get_logger

log = get_logger("gpu_monitor")


@dataclass
class GpuSample:
    """Unified GPU snapshot: dedicated NVIDIA + integrated AMD + firmware extras."""
    nvidia: Optional[NvidiaSample] = None
    amd: Optional[AmdSample] = None
    gpu_temp_c: Optional[float] = None       # firmware sensor (Acer WMI)
    gpu_fan_rpm: Optional[int] = None        # firmware sensor (Acer WMI)
    cpu_fan_rpm: Optional[int] = None        # firmware sensor (Acer WMI)
    temp_source: str = "none"


class GpuMonitor:
    """Aggregates both GPUs; NVIDIA dGPU metrics may vanish when Optimus powers it down."""

    def __init__(self, acer: Optional[AcerWmiBackend] = None,
                 lhm: Optional[LhmBridge] = None) -> None:
        self.acer = acer
        self.nvidia = NvidiaBackend()
        self.amd = AmdBackend(lhm)

    def sample(self) -> GpuSample:
        """Collect one GPU sample (non-blocking)."""
        s = GpuSample(nvidia=self.nvidia.sample(), amd=self.amd.sample())
        if self.acer is not None:
            try:
                reading: AcerSensorReading = self.acer.read_sensors()
                if reading.gpu_temp_c is not None:
                    s.gpu_temp_c = reading.gpu_temp_c
                    s.temp_source = "acer-wmi"
                s.gpu_fan_rpm = reading.gpu_fan_rpm
                s.cpu_fan_rpm = reading.cpu_fan_rpm
            except AcerWmiError as exc:
                log.debug("Acer GPU sensors failed: %s", exc)
        if s.gpu_temp_c is None and s.nvidia is not None and s.nvidia.temp_c is not None:
            s.gpu_temp_c = s.nvidia.temp_c
            s.temp_source = "nvml"
        return s

    def close(self) -> None:
        """Release NVML and AMD resources."""
        self.nvidia.close()
        self.amd.close()
