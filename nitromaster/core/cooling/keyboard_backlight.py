"""4-zone RGB keyboard backlight for the AN515-45.

Firmware quirks handled here (verified on this model):
- Colour writes are silently ignored unless the enable sequence runs first →
  :meth:`KeyboardBacklight` re-enables before every write.
- Custom colors do NOT survive a power cycle (boot default is red) → state is
  persisted and re-applied at startup by :meth:`restore`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from nitromaster.core.monitoring.sensors_backend import (
    KB_ALL_ZONES, KB_EFFECT_STATIC, KB_ZONES, AcerWmiBackend, AcerWmiError,
)
from nitromaster.utils.logging_setup import get_logger
from nitromaster.utils.state_store import StateStore

log = get_logger("keyboard")

STATE_KEY = "keyboard_backlight"


@dataclass
class ZoneColor:
    """RGB color of one keyboard zone."""
    r: int = 255
    g: int = 0
    b: int = 0

    def validate(self) -> None:
        """Raise ValueError when any channel is out of range 0..255."""
        for c in (self.r, self.g, self.b):
            if not 0 <= int(c) <= 255:
                raise ValueError(f"channel {c} out of range 0..255")

    def to_dict(self) -> dict:
        """JSON-friendly dict."""
        return {"r": self.r, "g": self.g, "b": self.b}

    @classmethod
    def from_dict(cls, d: dict) -> "ZoneColor":
        """Rebuild from :meth:`to_dict` output."""
        return cls(int(d.get("r", 255)), int(d.get("g", 0)), int(d.get("b", 0)))


@dataclass
class KeyboardState:
    """Persisted lighting state (survives app restarts, not firmware power cycles)."""
    zones: list[ZoneColor] = field(default_factory=lambda: [ZoneColor() for _ in KB_ZONES])
    mode: int = KB_EFFECT_STATIC
    speed: int = 0
    brightness: int = 100
    direction: int = 0
    enabled: bool = True

    def to_dict(self) -> dict:
        """JSON-friendly dict."""
        return {
            "zones": [z.to_dict() for z in self.zones],
            "mode": self.mode, "speed": self.speed,
            "brightness": self.brightness, "direction": self.direction,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KeyboardState":
        """Rebuild from :meth:`to_dict` output."""
        zones = [ZoneColor.from_dict(z) for z in d.get("zones", [])]
        while len(zones) < len(KB_ZONES):
            zones.append(ZoneColor())
        return cls(
            zones=zones[: len(KB_ZONES)],
            mode=int(d.get("mode", KB_EFFECT_STATIC)),
            speed=int(d.get("speed", 0)),
            brightness=int(d.get("brightness", 100)),
            direction=int(d.get("direction", 0)),
            enabled=bool(d.get("enabled", True)),
        )


class KeyboardBacklight:
    """Zone color / effect control with persistence and verified readback."""

    def __init__(self, acer: Optional[AcerWmiBackend] = None,
                 store: Optional[StateStore] = None) -> None:
        self.acer = acer
        self.store = store or StateStore()
        data = self.store.load(STATE_KEY)
        self.state = KeyboardState.from_dict(data) if data else KeyboardState()

    def _save(self) -> None:
        self.store.save(STATE_KEY, self.state.to_dict())

    def set_zone(self, zone_index: int, color: ZoneColor) -> bool:
        """Set one zone's static color (zone_index 0..3). Panel is enabled first."""
        if not 0 <= zone_index < len(KB_ZONES):
            raise ValueError(f"zone_index {zone_index} out of range 0..3")
        color.validate()
        self.state.zones[zone_index] = color
        self._save()
        return self._write_zones()

    def set_all_zones(self, color: ZoneColor) -> bool:
        """Set all four zones to the same color."""
        color.validate()
        self.state.zones = [ZoneColor(color.r, color.g, color.b) for _ in KB_ZONES]
        self._save()
        return self._write_zones()

    def _write_zones(self) -> bool:
        """Write every zone color (enable sequence runs inside set_zone_color)."""
        if self.acer is None:
            return False
        ok = True
        try:
            for zone_mask, color in zip(KB_ZONES, self.state.zones):
                st = self.acer.set_zone_color(zone_mask, color.r, color.g, color.b)
                ok = ok and st == 0
        except AcerWmiError as exc:
            log.warning("zone write failed: %s", exc)
            return False
        return ok

    def set_effect(self, mode: int, speed: int = 0, brightness: int = 100,
                   direction: int = 0, color: Optional[ZoneColor] = None) -> bool:
        """Set the panel effect (modes 0-7). Only Static normalizes speed/direction."""
        c = color or self.state.zones[0]
        c.validate()
        self.state.mode, self.state.speed = mode, speed
        self.state.brightness, self.state.direction = brightness, direction
        self._save()
        if self.acer is None:
            return False
        try:
            st = self.acer.set_kb_effect(mode, speed, brightness, c.r, c.g, c.b, direction)
            return st == 0
        except AcerWmiError as exc:
            log.warning("effect write failed: %s", exc)
            return False

    def set_brightness(self, brightness: int) -> bool:
        """Change panel brightness 0-255 (firmware scale), keeping mode/color."""
        if not 0 <= brightness <= 255:
            raise ValueError("brightness must be 0..255")
        s = self.state
        return self.set_effect(s.mode, s.speed, brightness, s.direction)

    def off(self) -> bool:
        """Turn the backlight panel off (all zones black)."""
        return self.set_all_zones(ZoneColor(0, 0, 0))

    def restore(self) -> bool:
        """Re-apply persisted state (call at startup/resume — firmware resets to red)."""
        if not self.state.enabled:
            return True
        if self.state.mode == KB_EFFECT_STATIC:
            return self._write_zones()
        s = self.state
        return self.set_effect(s.mode, s.speed, s.brightness, s.direction)

    def readback(self) -> Optional[dict]:
        """Read the firmware's own idea of the lighting state (silent-success check)."""
        if self.acer is None:
            return None
        try:
            return self.acer.get_kb_state()
        except AcerWmiError as exc:
            log.debug("readback failed: %s", exc)
            return None
