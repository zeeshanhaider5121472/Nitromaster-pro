"""Fan control for the AN515-45: Auto / Max / Custom duty + userspace fan curves.

The firmware has NO curve interface — only Auto/Max/Custom duty percentages.
Curves are therefore implemented here as a userspace loop that polls temperature
and rewrites duty (same approach as the Linux reference daemons).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from nitromaster.core.monitoring.sensors_backend import (
    FAN_CPU, FAN_GPU, FAN_MODE_AUTO, FAN_MODE_CUSTOM, FAN_MODE_MAX,
    AcerWmiBackend, AcerWmiError,
)
from nitromaster.utils.logging_setup import get_logger

log = get_logger("fans")

PROFILE_AUTO = "auto"
PROFILE_MAX = "max"
PROFILE_CUSTOM = "custom"
PROFILE_CURVE = "curve"


@dataclass
class CurvePoint:
    """One fan-curve point: at ``temp_c`` the fan runs at ``duty`` percent."""
    temp_c: float
    duty: int

    def __post_init__(self) -> None:
        if not 0 <= self.duty <= 100:
            raise ValueError(f"curve duty {self.duty} out of range 0..100")
        if not -20 <= self.temp_c <= 120:
            raise ValueError(f"curve temperature {self.temp_c} out of range")


@dataclass
class FanCurve:
    """Piecewise-linear temperature -> duty mapping (points sorted by temperature)."""
    points: list[CurvePoint] = field(default_factory=list)

    def normalized(self) -> list[CurvePoint]:
        """Return points sorted by temperature."""
        return sorted(self.points, key=lambda p: p.temp_c)

    def duty_for(self, temp_c: float) -> int:
        """Interpolate the duty percent for a temperature (clamped at both ends)."""
        pts = self.normalized()
        if not pts:
            raise ValueError("fan curve has no points")
        if temp_c <= pts[0].temp_c:
            return pts[0].duty
        if temp_c >= pts[-1].temp_c:
            return pts[-1].duty
        for lo, hi in zip(pts, pts[1:]):
            if lo.temp_c <= temp_c <= hi.temp_c:
                span = hi.temp_c - lo.temp_c
                if span <= 0:
                    return hi.duty
                frac = (temp_c - lo.temp_c) / span
                return int(round(lo.duty + frac * (hi.duty - lo.duty)))
        return pts[-1].duty

    def to_dict(self) -> dict:
        """JSON-friendly dict."""
        return {"points": [{"temp_c": p.temp_c, "duty": p.duty} for p in self.normalized()]}

    @classmethod
    def from_dict(cls, d: dict) -> "FanCurve":
        """Rebuild from :meth:`to_dict` output."""
        return cls(points=[CurvePoint(float(p["temp_c"]), int(p["duty"])) for p in d.get("points", [])])

    @classmethod
    def default_cool(cls) -> "FanCurve":
        """Balanced default curve for the AN515-45 dual-fan chassis."""
        return cls(points=[
            CurvePoint(40, 20), CurvePoint(55, 35), CurvePoint(65, 50),
            CurvePoint(75, 70), CurvePoint(85, 90), CurvePoint(90, 100),
        ])


@dataclass
class FanState:
    """Last known fan state."""
    cpu_mode: Optional[int] = None
    gpu_mode: Optional[int] = None
    cpu_duty: Optional[int] = None
    gpu_duty: Optional[int] = None
    cpu_rpm: Optional[int] = None
    gpu_rpm: Optional[int] = None


class FanController:
    """High-level fan control over the Acer firmware WMI interface."""

    def __init__(self, acer: Optional[AcerWmiBackend] = None) -> None:
        self.acer = acer
        self.state = FanState()
        self.curve = FanCurve.default_cool()
        self._curve_thread: Optional[threading.Thread] = None
        self._curve_stop = threading.Event()
        self._curve_duty: dict[str, int] = {}

    # --- static profiles -------------------------------------------------------------

    def set_profile(self, profile: str, cpu_duty: int = 60, gpu_duty: int = 60) -> bool:
        """Apply a named profile: auto / max / custom (with duties). False on firmware refusal."""
        if profile not in (PROFILE_AUTO, PROFILE_MAX, PROFILE_CUSTOM):
            raise ValueError(f"unknown fan profile {profile!r}")
        if self.acer is None:
            return False
        try:
            if profile == PROFILE_AUTO:
                st = self.acer.set_fan_behavior(FAN_MODE_AUTO, FAN_MODE_AUTO)
                ok = st == 0
            elif profile == PROFILE_MAX:
                st = self.acer.set_fan_behavior(FAN_MODE_MAX, FAN_MODE_MAX)
                ok = st == 0
            else:  # PROFILE_CUSTOM
                statuses = self.acer.apply_custom_duty(cpu_duty, gpu_duty)
                ok = all(s == 0 for s in statuses)
                self.state.cpu_duty, self.state.gpu_duty = cpu_duty, gpu_duty
            self.refresh_state()
            return ok
        except AcerWmiError as exc:
            log.warning("set_profile(%s) failed: %s", profile, exc)
            return False

    def refresh_state(self) -> FanState:
        """Read back fan behavior/duty/RPM (verified readback pattern)."""
        if self.acer is None:
            return self.state
        try:
            cpu_mode, gpu_mode, st = self.acer.get_fan_behavior()
            if st == 0:
                self.state.cpu_mode, self.state.gpu_mode = cpu_mode, gpu_mode
            for fan, attr in ((FAN_CPU, "cpu_duty"), (FAN_GPU, "gpu_duty")):
                s2, duty = self.acer.get_fan_speed(fan)
                if s2 == 0:
                    setattr(self.state, attr, duty)
            reading = self.acer.read_sensors()
            self.state.cpu_rpm = reading.cpu_fan_rpm
            self.state.gpu_rpm = reading.gpu_fan_rpm
        except AcerWmiError as exc:
            log.debug("refresh_state failed: %s", exc)
        return self.state

    # --- userspace curve engine -------------------------------------------------------

    def start_curve(self, temp_fn: Callable[[], Optional[float]], interval_s: float = 5.0) -> bool:
        """Start the userspace curve loop (CPU temp -> both fans). Safe to call repeatedly."""
        if self.acer is None:
            return False
        self.stop_curve()
        self._curve_stop.clear()
        self._curve_duty = {}

        def loop() -> None:
            while not self._curve_stop.is_set():
                temp = temp_fn()
                if temp is not None:
                    duty = self.curve.duty_for(temp)
                    self._curve_duty = {"cpu": duty, "gpu": duty}
                    try:
                        # Re-assert CUSTOM then duties; profile switches reset custom duty.
                        self.acer.apply_custom_duty(duty, duty)
                    except AcerWmiError as exc:
                        log.debug("curve duty write failed: %s", exc)
                self._curve_stop.wait(interval_s)

        self._curve_thread = threading.Thread(target=loop, name="fan-curve", daemon=True)
        self._curve_thread.start()
        log.info("fan curve started (interval %.1fs)", interval_s)
        return True

    def stop_curve(self) -> None:
        """Stop the curve loop and hand fans back to firmware Auto."""
        self._curve_stop.set()
        if self._curve_thread and self._curve_thread.is_alive():
            self._curve_thread.join(timeout=2.0)
        self._curve_thread = None
        if self.acer is not None:
            try:
                self.acer.set_fan_behavior(FAN_MODE_AUTO, FAN_MODE_AUTO)
            except AcerWmiError as exc:
                log.debug("auto restore failed: %s", exc)

    @property
    def curve_duty(self) -> dict:
        """Last duty written by the curve engine (for UI display)."""
        return dict(self._curve_duty)

    @property
    def curve_running(self) -> bool:
        """True while the userspace curve loop is active."""
        return self._curve_thread is not None and self._curve_thread.is_alive()
