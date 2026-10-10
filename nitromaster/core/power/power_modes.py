"""State-based mode engine: Normal / Battery Saver / Ultra Battery Saver / Performance / Gaming.

Each mode is a declarative :class:`ModeSpec`; :class:`ModeEngine` applies it step by step
and reports every step. Normal Mode restores the captured baseline exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from nitromaster.core.monitoring.sensors_backend import (
    FAN_MODE_AUTO, FAN_MODE_CUSTOM, FAN_MODE_MAX, PROFILE_BALANCED, PROFILE_ECO,
    PROFILE_NAMES, PROFILE_PERFORMANCE, PROFILE_QUIET, PROFILE_TURBO,
    AcerWmiBackend, AcerWmiError,
)
from nitromaster.core.power.baseline import BaselineManager, set_brightness
from nitromaster.core.power.focus_mode import FocusMode
from nitromaster.core.power.process_manager import BATTERY_SAVER_SERVICES, ServiceManager
from nitromaster.core.power.powercfg import (
    SCHEME_BALANCED, SCHEME_HIGH_PERFORMANCE, SCHEME_POWER_SAVER, SCHEME_ULTIMATE_PERFORMANCE,
    SET_PERFBOOSTMODE, SET_PERFBOOSTPOL, SET_PROCTHROTTLEMAX, SET_PROCTHROTTLEMIN,
    SET_VIDEO_POWERDOWN, SET_ASPM, SUB_PROCESSOR, SUB_PCIEXPRESS, SUB_VIDEO,
    PowerCfg,
)
from nitromaster.utils.logging_setup import get_logger

log = get_logger("modes")

MODE_NORMAL = "normal"
MODE_BATTERY_SAVER = "battery_saver"
MODE_ULTRA = "ultra_battery_saver"
MODE_PERFORMANCE = "performance"
MODE_GAMING = "gaming"


@dataclass
class ModeSpec:
    """Declarative description of one system mode."""
    key: str
    title: str
    description: str
    scheme_guid: Optional[str] = None            # power plan to activate (None = keep current)
    power_settings: list[tuple[str, str, Optional[int], Optional[int]]] = field(default_factory=list)
    # (subgroup, setting, ac_index, dc_index) applied to the active scheme
    fan_mode: Optional[int] = None               # FAN_MODE_* for both fans
    thermal_profile: Optional[int] = None        # firmware profile id (0/1/4/5/6)
    brightness: Optional[int] = None             # panel brightness percent
    process_policy: str = "normal"               # normal | battery | ultra
    oc_afterburner_profile: Optional[int] = None # MSI Afterburner profile number (1-5)
    stop_services: bool = False                  # opt-in service stop (Battery Saver family)

    def __post_init__(self) -> None:
        if self.fan_mode is not None and self.fan_mode not in (FAN_MODE_AUTO, FAN_MODE_MAX, FAN_MODE_CUSTOM):
            raise ValueError(f"invalid fan_mode {self.fan_mode}")
        if self.thermal_profile is not None and self.thermal_profile not in PROFILE_NAMES:
            raise ValueError(f"invalid thermal_profile {self.thermal_profile}")
        if self.brightness is not None and not 0 <= self.brightness <= 100:
            raise ValueError(f"invalid brightness {self.brightness}")


@dataclass
class ModeStepResult:
    """Outcome of one apply step."""
    step: str
    ok: bool
    detail: str = ""


class ModeEngine:
    """Applies modes across power plan, firmware fan/profile, brightness and process policy."""

    def __init__(self, powercfg: Optional[PowerCfg] = None,
                 acer: Optional[AcerWmiBackend] = None,
                 baselines: Optional[BaselineManager] = None,
                 focus: Optional[FocusMode] = None) -> None:
        self.powercfg = powercfg or PowerCfg()
        self.acer = acer
        self.baselines = baselines or BaselineManager(self.powercfg, acer)
        self.focus = focus or FocusMode()
        self.services = ServiceManager()
        self._afterburner: Optional[str] = self._find_afterburner()
        self.current_mode: str = MODE_NORMAL
        self._listeners: list[Callable[[str], None]] = []

    # --- mode registry --------------------------------------------------------------

    @staticmethod
    def specs() -> dict[str, ModeSpec]:
        """All built-in modes keyed by mode key."""
        boost_ac, boost_dc = 2, 1   # aggressive on AC, enabled on DC (verified value table)
        return {
            MODE_NORMAL: ModeSpec(
                MODE_NORMAL, "Normal Mode",
                "Restores the exact system state captured on first launch.",
            ),
            MODE_BATTERY_SAVER: ModeSpec(
                MODE_BATTERY_SAVER, "Battery Saver",
                "Standard power saving: capped CPU boost, dimmed display, longer sleep timers.",
                scheme_guid=SCHEME_POWER_SAVER,
                power_settings=[
                    (SUB_PROCESSOR, SET_PERFBOOSTMODE, 1, 0),
                    (SUB_PROCESSOR, SET_PROCTHROTTLEMAX, 100, 75),
                    (SUB_PROCESSOR, SET_PROCTHROTTLEMIN, 5, 5),
                    (SUB_VIDEO, SET_VIDEO_POWERDOWN, 300, 120),
                    (SUB_PCIEXPRESS, SET_ASPM, 1, 2),
                ],
                fan_mode=FAN_MODE_AUTO, thermal_profile=PROFILE_QUIET,
                brightness=50, process_policy="battery", stop_services=False,
            ),
            MODE_ULTRA: ModeSpec(
                MODE_ULTRA, "Ultra Battery Saver",
                "Xiaomi-style minimalism: single-app focus, background freeze, aggressive limits.",
                scheme_guid=SCHEME_POWER_SAVER,
                power_settings=[
                    (SUB_PROCESSOR, SET_PERFBOOSTMODE, 0, 0),
                    (SUB_PROCESSOR, SET_PERFBOOSTPOL, 0, 0),
                    (SUB_PROCESSOR, SET_PROCTHROTTLEMAX, 50, 50),
                    (SUB_PROCESSOR, SET_PROCTHROTTLEMIN, 5, 5),
                    (SUB_VIDEO, SET_VIDEO_POWERDOWN, 120, 60),
                    (SUB_PCIEXPRESS, SET_ASPM, 2, 2),
                ],
                fan_mode=FAN_MODE_AUTO, thermal_profile=PROFILE_ECO,
                brightness=30, process_policy="ultra", stop_services=True,
            ),
            MODE_PERFORMANCE: ModeSpec(
                MODE_PERFORMANCE, "Performance Mode",
                "Optimized for heavy multitasking: aggressive boost, high performance plan.",
                scheme_guid=SCHEME_HIGH_PERFORMANCE,
                power_settings=[
                    (SUB_PROCESSOR, SET_PERFBOOSTMODE, boost_ac, boost_dc),
                    (SUB_PROCESSOR, SET_PERFBOOSTPOL, 100, 100),
                    (SUB_PROCESSOR, SET_PROCTHROTTLEMAX, 100, 100),
                    (SUB_PROCESSOR, SET_PROCTHROTTLEMIN, 100, 5),
                ],
                fan_mode=FAN_MODE_AUTO, thermal_profile=PROFILE_PERFORMANCE,
                process_policy="normal",
            ),
            MODE_GAMING: ModeSpec(
                MODE_GAMING, "Gaming / Jailbreak Mode",
                "Max boost + Turbo fan profile + optional MSI Afterburner OC profile.",
                scheme_guid=SCHEME_ULTIMATE_PERFORMANCE,
                power_settings=[
                    (SUB_PROCESSOR, SET_PERFBOOSTMODE, boost_ac, boost_dc),
                    (SUB_PROCESSOR, SET_PERFBOOSTPOL, 100, 100),
                    (SUB_PROCESSOR, SET_PROCTHROTTLEMAX, 100, 100),
                    (SUB_PROCESSOR, SET_PROCTHROTTLEMIN, 100, 10),
                ],
                fan_mode=FAN_MODE_MAX, thermal_profile=PROFILE_TURBO,
                oc_afterburner_profile=1, process_policy="normal",
            ),
        }

    # --- lifecycle -------------------------------------------------------------------

    def on_mode_changed(self, fn: Callable[[str], None]) -> None:
        """Register a listener called with the new mode key after each apply."""
        self._listeners.append(fn)

    def apply(self, mode_key: str) -> list[ModeStepResult]:
        """Apply one mode; returns a per-step result report."""
        specs = self.specs()
        if mode_key not in specs:
            raise ValueError(f"unknown mode {mode_key!r}")
        spec = specs[mode_key]
        results: list[ModeStepResult] = []
        self.baselines.ensure_captured()

        if mode_key == MODE_NORMAL:
            for line in self.baselines.restore():
                results.append(ModeStepResult("restore baseline", "FAILED" not in line, line))
        else:
            if spec.scheme_guid:
                ok = self.powercfg.set_active(spec.scheme_guid)
                results.append(ModeStepResult("activate power plan", ok, spec.scheme_guid))
            else:
                results.append(ModeStepResult("activate power plan", True, "kept current scheme"))
            scheme = self.powercfg.get_active_scheme()
            for sub, setting, ac, dc in spec.power_settings:
                ok = self.powercfg.set_values(scheme or SCHEME_BALANCED, sub, setting, ac, dc)
                results.append(ModeStepResult(f"power setting {setting[:8]}", ok))
            if spec.fan_mode is not None and self.acer is not None:
                try:
                    st = self.acer.set_fan_behavior(spec.fan_mode, spec.fan_mode)
                    results.append(ModeStepResult("fan behavior", st == 0, f"status {st}"))
                except AcerWmiError as exc:
                    results.append(ModeStepResult("fan behavior", False, str(exc)))
            if spec.thermal_profile is not None and self.acer is not None:
                try:
                    st = self.acer.set_thermal_profile(spec.thermal_profile)
                    results.append(ModeStepResult("thermal profile", st == 0, f"status {st}"))
                except AcerWmiError as exc:
                    results.append(ModeStepResult("thermal profile", False, str(exc)))
            if spec.brightness is not None:
                ok = set_brightness(spec.brightness)
                results.append(ModeStepResult("display brightness", ok, f"{spec.brightness}%"))

        results.extend(self._apply_process_policy(spec))
        results.extend(self._apply_oc(spec))
        self.current_mode = mode_key
        for fn in self._listeners:
            try:
                fn(mode_key)
            except Exception as exc:
                log.warning("mode listener failed: %s", exc)
        log.info("mode %s applied: %d steps", mode_key, len(results))
        return results

    def _apply_process_policy(self, spec: ModeSpec) -> list[ModeStepResult]:
        """Process/service side of a mode (all reversible)."""
        out: list[ModeStepResult] = []
        if self.focus.active:
            self.focus.stop()
            out.append(ModeStepResult("focus mode", True, "released"))
        if spec.process_policy == "ultra":
            self.focus.suspend_background = False   # throttle only; suspend stays opt-in
            n = self.focus.start()
            out.append(ModeStepResult("single-app focus", True, f"{n} background processes throttled"))
            if spec.stop_services:
                snaps = self.services.snapshot(BATTERY_SAVER_SERVICES)
                failures = self.services.stop(s.name for s in snaps)
                out.append(ModeStepResult(
                    "stop background services", not failures,
                    f"{len(snaps) - len(failures)}/{len(snaps)} stopped",
                ))
        elif spec.process_policy == "battery":
            snaps = self.services.snapshot(BATTERY_SAVER_SERVICES[:3])  # gentle set only
            failures = self.services.stop(s.name for s in snaps)
            out.append(ModeStepResult("pause indexing services", not failures,
                                      f"{len(snaps) - len(failures)}/{len(snaps)} stopped"))
        else:
            failures = self.services.restore()
            out.append(ModeStepResult("restore services", not failures,
                                      "all restored" if not failures else f"failed: {failures}"))
        return out

    def _apply_oc(self, spec: ModeSpec) -> list[ModeStepResult]:
        """Apply an MSI Afterburner OC profile when available (gaming mode only)."""
        if spec.oc_afterburner_profile is None:
            return []
        if not self._afterburner:
            return [ModeStepResult("GPU overclock", False,
                                   "MSI Afterburner not found - install it to enable OC profile 1")]
        import subprocess
        try:
            subprocess.Popen([self._afterburner, f"-profile{spec.oc_afterburner_profile}"])
            return [ModeStepResult("GPU overclock", True,
                                   f"Afterburner profile {spec.oc_afterburner_profile} applied")]
        except OSError as exc:
            return [ModeStepResult("GPU overclock", False, str(exc))]

    @staticmethod
    def _find_afterburner() -> Optional[str]:
        """Locate MSIAfterburner.exe in the standard install locations."""
        import os
        from pathlib import Path
        candidates = [
            r"C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe",
            r"C:\Program Files\MSI Afterburner\MSIAfterburner.exe",
        ]
        env = os.environ.get("ProgramFiles(x86)")
        if env:
            candidates.append(str(Path(env) / "MSI Afterburner" / "MSIAfterburner.exe"))
        for c in candidates:
            if Path(c).is_file():
                return c
        return None

    def restore_normal(self) -> list[ModeStepResult]:
        """Shortcut for Normal Mode (baseline restore)."""
        return self.apply(MODE_NORMAL)
