"""First-run baseline capture and exact restore (Normal Mode).

Captures: active power scheme (+ .pow export of the settings we touch), fan
behavior/duty, firmware thermal profile, keyboard backlight state and display
brightness. Everything degrades gracefully: a missing sensor is simply left out.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from nitromaster.core.monitoring.sensors_backend import (
    FAN_CPU, FAN_GPU, AcerWmiBackend, AcerWmiError, FAN_MODE_CUSTOM,
)
from nitromaster.core.power.powercfg import (
    SET_PERFBOOSTMODE, SET_PERFBOOSTPOL, SET_PROCTHROTTLEMAX, SET_PROCTHROTTLEMIN,
    SET_VIDEO_BRIGHTNESS, SET_VIDEO_POWERDOWN, SET_STANDBY_TIMEOUT,
    SUB_PROCESSOR, SUB_VIDEO, SUB_SLEEP, PowerCfg,
)
from nitromaster.utils.logging_setup import get_logger
from nitromaster.utils.state_store import StateStore

log = get_logger("baseline")

BASELINE_KEY = "baseline"
_TOUCHED_SETTINGS = [
    (SUB_PROCESSOR, SET_PERFBOOSTMODE), (SUB_PROCESSOR, SET_PERFBOOSTPOL),
    (SUB_PROCESSOR, SET_PROCTHROTTLEMAX), (SUB_PROCESSOR, SET_PROCTHROTTLEMIN),
    (SUB_VIDEO, SET_VIDEO_BRIGHTNESS), (SUB_VIDEO, SET_VIDEO_POWERDOWN),
    (SUB_SLEEP, SET_STANDBY_TIMEOUT),
]


@dataclass
class Baseline:
    """Serializable snapshot of the machine's first-run state."""
    created_at: float = 0.0
    power_scheme_guid: str = ""
    power_scheme_name: str = ""
    power_settings: dict[str, dict[str, Optional[int]]] = field(default_factory=dict)
    pow_file: str = ""
    fan_cpu_mode: Optional[int] = None
    fan_gpu_mode: Optional[int] = None
    fan_cpu_duty: Optional[int] = None
    fan_gpu_duty: Optional[int] = None
    thermal_profile: Optional[int] = None
    kb_state: Optional[dict] = None
    brightness: Optional[int] = None

    def to_dict(self) -> dict:
        """JSON-friendly dict."""
        return {
            "created_at": self.created_at,
            "power_scheme_guid": self.power_scheme_guid,
            "power_scheme_name": self.power_scheme_name,
            "power_settings": self.power_settings,
            "pow_file": self.pow_file,
            "fan_cpu_mode": self.fan_cpu_mode, "fan_gpu_mode": self.fan_gpu_mode,
            "fan_cpu_duty": self.fan_cpu_duty, "fan_gpu_duty": self.fan_gpu_duty,
            "thermal_profile": self.thermal_profile,
            "kb_state": self.kb_state, "brightness": self.brightness,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Baseline":
        """Rebuild from :meth:`to_dict` output."""
        b = cls()
        for k, v in d.items():
            if hasattr(b, k):
                setattr(b, k, v)
        return b


class BaselineManager:
    """Captures once on first load and restores exactly (Normal Mode)."""

    def __init__(self, powercfg: Optional[PowerCfg] = None,
                 acer: Optional[AcerWmiBackend] = None,
                 store: Optional[StateStore] = None) -> None:
        self.powercfg = powercfg or PowerCfg()
        self.acer = acer
        self.store = store or StateStore()
        self._baseline: Optional[Baseline] = None

    @property
    def baseline(self) -> Optional[Baseline]:
        """The loaded baseline, or None when never captured."""
        if self._baseline is None:
            data = self.store.load(BASELINE_KEY)
            if data:
                self._baseline = Baseline.from_dict(data)
        return self._baseline

    def ensure_captured(self) -> Optional[Baseline]:
        """Capture the baseline on first call; later calls load from disk."""
        if self.baseline is not None:
            return self.baseline
        return self.capture()

    def capture(self) -> Optional[Baseline]:
        """Snapshot the current system state and persist it."""
        b = Baseline(created_at=time.time())
        b.power_scheme_guid = self.powercfg.get_active_scheme() or ""
        for s in self.powercfg.list_schemes():
            if s.guid == b.power_scheme_guid:
                b.power_scheme_name = s.name
        if b.power_scheme_guid:
            for sub, setting in _TOUCHED_SETTINGS:
                values = self.powercfg.query(b.power_scheme_guid, sub).get(setting)
                b.power_settings[setting] = {
                    "ac": values.ac if values else None,
                    "dc": values.dc if values else None,
                    "sub": sub,
                }
            pow_path = self.store.root / "baseline-scheme.pow"
            if self.powercfg.export_scheme(b.power_scheme_guid, str(pow_path)):
                b.pow_file = str(pow_path)
        if self.acer is not None:
            try:
                cpu_mode, gpu_mode, status = self.acer.get_fan_behavior()
                if status == 0:
                    b.fan_cpu_mode, b.fan_gpu_mode = cpu_mode, gpu_mode
                if cpu_mode == FAN_MODE_CUSTOM:
                    st, duty = self.acer.get_fan_speed(FAN_CPU)
                    if st == 0:
                        b.fan_cpu_duty = duty
                if gpu_mode == FAN_MODE_CUSTOM:
                    st, duty = self.acer.get_fan_speed(FAN_GPU)
                    if st == 0:
                        b.fan_gpu_duty = duty
                st, profile = self.acer.get_thermal_profile()
                if st == 0:
                    b.thermal_profile = profile
                b.kb_state = self.acer.get_kb_state()
            except AcerWmiError as exc:
                log.warning("baseline firmware capture incomplete: %s", exc)
        b.brightness = read_brightness()
        self._baseline = b
        self.store.save(BASELINE_KEY, b.to_dict())
        log.info("baseline captured: scheme=%s", b.power_scheme_guid)
        return b

    def restore(self) -> list[str]:
        """Restore every captured setting; returns human-readable step results."""
        report: list[str] = []
        b = self.baseline
        if b is None:
            return ["no baseline captured yet"]
        if b.pow_file and Path(b.pow_file).exists():
            ok = self.powercfg.import_scheme(b.pow_file, b.power_scheme_guid or None)
            report.append(f"power scheme import: {'ok' if ok else 'FAILED'}")
        if b.power_scheme_guid:
            ok = self.powercfg.set_active(b.power_scheme_guid)
            report.append(f"activate scheme {b.power_scheme_name or b.power_scheme_guid}: {'ok' if ok else 'FAILED'}")
            for setting, vals in b.power_settings.items():
                sub = vals.get("sub")
                if sub:
                    ok = self.powercfg.set_values(b.power_scheme_guid, sub, setting, vals.get("ac"), vals.get("dc"))
                    report.append(f"restore setting {setting[:8]}: {'ok' if ok else 'FAILED'}")
        if self.acer is not None and b.fan_cpu_mode is not None:
            try:
                st = self.acer.set_fan_behavior(b.fan_cpu_mode, b.fan_gpu_mode or b.fan_cpu_mode)
                report.append(f"fan behavior restore (status {st})")
                if b.fan_cpu_mode == FAN_MODE_CUSTOM and b.fan_cpu_duty is not None:
                    self.acer.set_fan_speed(FAN_CPU, b.fan_cpu_duty)
                if b.fan_gpu_mode == FAN_MODE_CUSTOM and b.fan_gpu_duty is not None:
                    self.acer.set_fan_speed(FAN_GPU, b.fan_gpu_duty)
            except AcerWmiError as exc:
                report.append(f"fan restore FAILED: {exc}")
            if b.thermal_profile is not None:
                try:
                    st = self.acer.set_thermal_profile(b.thermal_profile)
                    report.append(f"thermal profile restore (status {st})")
                except AcerWmiError as exc:
                    report.append(f"thermal profile restore FAILED: {exc}")
            if b.kb_state:
                kb = b.kb_state
                try:
                    self.acer.set_kb_effect(
                        kb.get("mode", 0), kb.get("speed", 0), kb.get("brightness", 100),
                        kb.get("r", 255), kb.get("g", 0), kb.get("b", 0), kb.get("direction", 0),
                    )
                    report.append("keyboard backlight restored")
                except AcerWmiError as exc:
                    report.append(f"keyboard restore FAILED: {exc}")
        if b.brightness is not None:
            ok = set_brightness(b.brightness)
            report.append(f"brightness {b.brightness}%: {'ok' if ok else 'FAILED'}")
        return report


# --- Display brightness (WMI WmiMonitorBrightnessMethods) ---------------------------

def set_brightness(percent: int, timeout_s: int = 5) -> bool:
    """Set the panel brightness 0-100 via root\\wmi WmiMonitorBrightnessMethods."""
    if not 0 <= percent <= 100:
        raise ValueError("brightness must be 0..100")
    try:
        import wmi  # Windows-only
        for mon in wmi.WMI(namespace="root/wmi").WmiMonitorBrightnessMethods():
            mon.WmiSetBrightness(timeout_s, percent)
        return True
    except Exception as exc:
        log.debug("brightness write failed: %s", exc)
        return False


def read_brightness() -> Optional[int]:
    """Read current panel brightness percent; None when unavailable."""
    try:
        import wmi  # Windows-only
        for lvl in wmi.WMI(namespace="root/wmi").WmiMonitorBrightness():
            return int(lvl.CurrentBrightness)
    except Exception as exc:
        log.debug("brightness read failed: %s", exc)
    return None
