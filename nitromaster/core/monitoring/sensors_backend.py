"""Acer Nitro AN515-45 firmware protocol (WMI class ``AcerGamingFunction``) + sensor bridges.

Protocol constants and encode/decode functions are pure Python and unit-tested on any OS.
The :class:`AcerWmiBackend` driver class is instantiated only on Windows.

Protocol facts are taken from mainline ``acer-wmi.c`` and verified AN515-45 implementations
(see docs/research/01-platform-an515-45.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from nitromaster.utils.platform import require_windows
from nitromaster.utils.logging_setup import get_logger

log = get_logger("sensors")

# --- Protocol constants (verified) -------------------------------------------------

ACER_WMI_NAMESPACE = "root\\wmi"
ACER_WMI_CLASS = "AcerGamingFunction"

# Fan selectors (bits 7:0 of SetGamingFanSpeed / GetGamingFanSpeed)
FAN_CPU = 0x01
FAN_GPU = 0x04
# Fan bitmap (bits 15:0 of SetGamingFanBehavior): BIT(0)=CPU fan, BIT(3)=GPU fan
FAN_BITMAP_CPU = 0x01
FAN_BITMAP_GPU = 0x08
FAN_BITMAP_BOTH = 0x09
FAN_BOTH = FAN_BITMAP_BOTH

# Fan behavior mode values (bits 17:16 CPU / 23:22 GPU on set)
FAN_MODE_AUTO = 0x1
FAN_MODE_MAX = 0x2   # firmware "TURBO", NitroSense "Max"
FAN_MODE_CUSTOM = 0x3

# Verified known-good whole-payload constants for both fans
FAN_BEHAVIOR_AUTO = 0x00410009
FAN_BEHAVIOR_MAX = 0x00820009
FAN_BEHAVIOR_CUSTOM = 0x00C30009

# GetGamingSysInfo selectors
SYS_CPU_TEMP = 0x0101
SYS_GPU_TEMP = 0x0A01
SYS_CPU_FAN_RPM = 0x0201
SYS_GPU_FAN_RPM = 0x0601
SYS_SENSOR_BITMAP = 0x0000

# Thermal profiles (SetGamingMiscSetting index 0x0B)
MISC_THERMAL_PROFILE = 0x0B
MISC_SUPPORTED_PROFILES = 0x0A
PROFILE_QUIET = 0
PROFILE_BALANCED = 1
PROFILE_PERFORMANCE = 4
PROFILE_TURBO = 5
PROFILE_ECO = 6
PROFILE_NAMES = {
    PROFILE_QUIET: "Quiet",
    PROFILE_BALANCED: "Balanced",
    PROFILE_PERFORMANCE: "Performance",
    PROFILE_TURBO: "Turbo",
    PROFILE_ECO: "Eco",
}

# Keyboard backlight zones are a bitmask, not ids
KB_ZONES = (0x01, 0x02, 0x04, 0x08)
KB_ALL_ZONES = 0x0F

KB_EFFECT_STATIC = 0
KB_EFFECT_BREATHING = 1
KB_EFFECT_NEON = 2
KB_EFFECT_WAVE = 3
KB_EFFECT_SHIFTING = 4
KB_EFFECT_ZOOM = 5
KB_EFFECT_METEOR = 6
KB_EFFECT_TWINKLING = 7
KB_EFFECT_NAMES = {
    KB_EFFECT_STATIC: "Static", KB_EFFECT_BREATHING: "Breathing",
    KB_EFFECT_NEON: "Neon", KB_EFFECT_WAVE: "Wave", KB_EFFECT_SHIFTING: "Shifting",
    KB_EFFECT_ZOOM: "Zoom", KB_EFFECT_METEOR: "Meteor", KB_EFFECT_TWINKLING: "Twinkling",
}

STATUS_OK = 0


# --- Pure encode/decode ------------------------------------------------------------

def encode_fan_behavior(cpu_mode: int, gpu_mode: int, fan_bitmap: int = FAN_BITMAP_BOTH) -> int:
    """Encode SetGamingFanBehavior payload: bitmap | cpu_mode<<16 | gpu_mode<<22."""
    if cpu_mode not in (FAN_MODE_AUTO, FAN_MODE_MAX, FAN_MODE_CUSTOM):
        raise ValueError(f"invalid CPU fan mode {cpu_mode}")
    if gpu_mode not in (FAN_MODE_AUTO, FAN_MODE_MAX, FAN_MODE_CUSTOM):
        raise ValueError(f"invalid GPU fan mode {gpu_mode}")
    return (fan_bitmap & 0xFFFF) | ((cpu_mode & 0x3) << 16) | ((gpu_mode & 0x3) << 22)


def decode_fan_behavior_reply(value: int) -> tuple[int, int, int]:
    """Decode GetGamingFanBehavior reply -> (cpu_mode, gpu_mode, status)."""
    status = value & 0xFF
    cpu_mode = (value >> 8) & 0x3
    gpu_mode = (value >> 14) & 0x3
    return cpu_mode, gpu_mode, status


def encode_fan_speed(selector: int, percent: int) -> int:
    """Encode SetGamingFanSpeed payload: selector | percent<<8 (percent 0..100)."""
    if selector not in (FAN_CPU, FAN_GPU):
        raise ValueError(f"invalid fan selector {selector:#x}")
    if not 0 <= percent <= 100:
        raise ValueError(f"fan duty {percent} out of range 0..100")
    return selector | (percent << 8)


def decode_fan_speed_reply(value: int) -> tuple[int, int]:
    """Decode GetGamingFanSpeed reply -> (status, duty_percent)."""
    status = value & 0xFF
    percent = (value >> 8) & 0xFF
    return status, percent


def decode_sysinfo_reply(value: int, mask: int = 0xFFFF) -> Optional[int]:
    """Decode GetGamingSysInfo reply; returns the reading or None when the sensor is unavailable."""
    status = value & 0xFF
    if status != STATUS_OK:
        return None
    return (value >> 8) & mask


def encode_rgb_kb(zone_mask: int, r: int, g: int, b: int) -> int:
    """Encode SetGamingRgbKb u32: zone | R<<8 | G<<16 | B<<24."""
    if zone_mask & ~KB_ALL_ZONES or zone_mask == 0:
        raise ValueError(f"invalid zone mask {zone_mask:#x}")
    for c in (r, g, b):
        if not 0 <= c <= 255:
            raise ValueError(f"color channel {c} out of range 0..255")
    return (zone_mask & 0xFF) | (r << 8) | (g << 16) | (b << 24)


def encode_kb_backlight(mode: int, speed: int, brightness: int,
                        r: int, g: int, b: int, direction: int = 0) -> bytes:
    """Encode the 16-byte SetGamingKBBacklight payload (byte 8 MUST be 0 on AN515-45)."""
    if mode not in KB_EFFECT_NAMES:
        raise ValueError(f"invalid KB effect mode {mode}")
    for c in (speed, brightness, direction, r, g, b):
        if not 0 <= int(c) <= 255:
            raise ValueError(f"payload byte {c} out of range 0..255")
    wave_flag = 8 if mode == KB_EFFECT_WAVE else 0
    buf = bytearray(16)
    buf[0] = mode
    buf[1] = speed
    buf[2] = brightness
    buf[3] = wave_flag
    buf[4] = direction
    buf[5] = r
    buf[6] = g
    buf[7] = b
    buf[8] = 0        # verified: 3 = accepted-but-dead on AN515-45 firmware
    buf[9] = 1
    return bytes(buf)


def decode_kb_backlight_reply(data: Any) -> Optional[dict]:
    """Decode GetGamingKBBacklight byte payload -> dict(mode, speed, brightness, r, g, b)."""
    if not data:
        return None
    b = bytes(data)
    if len(b) < 8:
        return None
    return {
        "mode": b[0], "speed": b[1], "brightness": b[2], "direction": b[4],
        "r": b[5], "g": b[6], "b": b[7],
    }


def encode_misc_setting(index: int, value: int) -> int:
    """Encode SetGamingMiscSetting payload: index | value<<8."""
    if not 0 <= index <= 0xFF:
        raise ValueError(f"misc index {index} out of range")
    if not 0 <= value <= 0xFF:
        raise ValueError(f"misc value {value} out of range")
    return index | (value << 8)


def decode_misc_setting_reply(value: int) -> tuple[int, int]:
    """Decode GetGamingMiscSetting reply -> (status, value)."""
    return value & 0xFF, (value >> 8) & 0xFF


# --- Sensor snapshot types ---------------------------------------------------------

@dataclass
class AcerSensorReading:
    """One firmware sensor reading; ``value`` is None when unavailable."""
    cpu_temp_c: Optional[float] = None
    gpu_temp_c: Optional[float] = None
    cpu_fan_rpm: Optional[int] = None
    gpu_fan_rpm: Optional[int] = None
    sensor_bitmap: Optional[int] = None


# --- Windows driver -----------------------------------------------------------------

class AcerWmiBackend:
    """Driver for ``root\\wmi:AcerGamingFunction`` (single instance, one-parameter methods).

    Instantiation on non-Windows platforms raises RuntimeError. All method calls raise
    :class:`AcerWmiError` on transport failure and return firmware status bytes on protocol
    refusal (silent-success hazard: always read back after writes).
    """

    def __init__(self) -> None:
        require_windows("AcerGamingFunction access")
        self._obj = None
        self._connect()

    def _connect(self) -> None:
        import win32com.client  # Windows-only import
        svc = win32com.client.GetObject(r"winmgmts:\\.\root\wmi")
        insts = svc.InstancesOf(ACER_WMI_CLASS)
        if not insts:
            raise AcerWmiError("AcerGamingFunction WMI class not present on this machine")
        self._obj = insts[0]

    def _call(self, method: str, value: Any) -> dict:
        """Invoke a one-input firmware method; returns the output property dict."""
        if self._obj is None:
            self._connect()
        try:
            mdesc = self._obj.Methods_(method)
            ip = mdesc.InParameters_.SpawnInstance_()
            props = list(ip.Properties_)
            if not props:
                raise AcerWmiError(f"{method}: no input parameter in WMI signature")
            props[0].Value = value
            out = self._obj.ExecMethod_(method, ip)
            return {p.Name: p.Value for p in out.Properties_}
        except AcerWmiError:
            raise
        except Exception as exc:  # COM/transport failures
            self._obj = None
            raise AcerWmiError(f"{method} failed: {exc}") from exc

    @staticmethod
    def _outputs(result: dict) -> tuple[int, Any]:
        """Extract (status, value) from a method result dict, tolerating name variants."""
        status = result.get("gmReturn")
        if status is None:
            for k, v in result.items():
                if "return" in k.lower() or "status" in k.lower():
                    status = v
                    break
        value = result.get("gmOutput")
        if value is None:
            for k, v in result.items():
                if "output" in k.lower():
                    value = v
                    break
        return (int(status) if status is not None else STATUS_OK), value

    # --- fans ----------------------------------------------------------------------

    def set_fan_behavior(self, cpu_mode: int, gpu_mode: int) -> int:
        """Set both fans' behavior mode; returns firmware status byte."""
        status, _ = self._outputs(self._call("SetGamingFanBehavior", encode_fan_behavior(cpu_mode, gpu_mode)))
        return status

    def get_fan_behavior(self) -> tuple[int, int, int]:
        """Return (cpu_mode, gpu_mode, status)."""
        _, value = self._outputs(self._call("GetGamingFanBehavior", FAN_BOTH))
        return decode_fan_behavior_reply(int(value or 0))

    def set_fan_speed(self, selector: int, percent: int) -> int:
        """Set custom duty for one fan (FAN_CPU/FAN_GPU); returns firmware status byte."""
        status, _ = self._outputs(self._call("SetGamingFanSpeed", encode_fan_speed(selector, percent)))
        return status

    def get_fan_speed(self, selector: int) -> tuple[int, int]:
        """Return (status, duty_percent) for one fan."""
        _, value = self._outputs(self._call("GetGamingFanSpeed", selector))
        return decode_fan_speed_reply(int(value or 0))

    def apply_custom_duty(self, cpu_percent: int, gpu_percent: int) -> list[int]:
        """Set CUSTOM behavior then both duties (verified order of operations); returns statuses."""
        statuses = [self.set_fan_behavior(FAN_MODE_CUSTOM, FAN_MODE_CUSTOM)]
        statuses.append(self.set_fan_speed(FAN_CPU, cpu_percent))
        statuses.append(self.set_fan_speed(FAN_GPU, gpu_percent))
        return statuses

    # --- sensors -------------------------------------------------------------------

    def read_sysinfo(self, selector: int, mask: int = 0xFFFF) -> Optional[int]:
        """Read one GetGamingSysInfo sensor; None when unavailable."""
        try:
            _, value = self._outputs(self._call("GetGamingSysInfo", selector))
        except AcerWmiError:
            return None
        return decode_sysinfo_reply(int(value or 0), mask)

    def read_sensors(self) -> AcerSensorReading:
        """Read all four verified sensors plus the support bitmap."""
        r = AcerSensorReading()
        t = self.read_sysinfo(SYS_CPU_TEMP, 0xFF)
        if t is not None:
            r.cpu_temp_c = float(t)
        g = self.read_sysinfo(SYS_GPU_TEMP, 0xFF)
        if g is not None:
            r.gpu_temp_c = float(g)
        cf = self.read_sysinfo(SYS_CPU_FAN_RPM)
        if cf is not None:
            r.cpu_fan_rpm = int(cf)
        gf = self.read_sysinfo(SYS_GPU_FAN_RPM)
        if gf is not None:
            r.gpu_fan_rpm = int(gf)
        r.sensor_bitmap = self.read_sysinfo(SYS_SENSOR_BITMAP)
        return r

    # --- thermal profile -----------------------------------------------------------

    def set_thermal_profile(self, profile_id: int) -> int:
        """Set the firmware thermal profile (0/1/4/5/6); returns firmware status byte."""
        if profile_id not in PROFILE_NAMES:
            raise ValueError(f"unknown thermal profile {profile_id}")
        status, _ = self._outputs(self._call("SetGamingMiscSetting", encode_misc_setting(MISC_THERMAL_PROFILE, profile_id)))
        return status

    def get_thermal_profile(self) -> tuple[int, int]:
        """Return (status, profile_id)."""
        _, value = self._outputs(self._call("GetGamingMiscSetting", MISC_THERMAL_PROFILE))
        return decode_misc_setting_reply(int(value or 0))

    def get_supported_profiles(self) -> tuple[int, int]:
        """Return (status, bitmask) of supported thermal profiles (bit position = profile id)."""
        _, value = self._outputs(self._call("GetGamingMiscSetting", MISC_SUPPORTED_PROFILES))
        return decode_misc_setting_reply(int(value or 0))

    # --- keyboard backlight --------------------------------------------------------

    def enable_keyboard_panel(self) -> None:
        """Run the verified enable sequence: GetGamingSysInfo(0) then LED behavior 8|(15<<40)."""
        self._call("GetGamingSysInfo", 0)
        self._call("SetGamingLEDBehavior", 8 | (KB_ALL_ZONES << 40))

    def set_zone_color(self, zone_mask: int, r: int, g: int, b: int) -> int:
        """Enable the panel, then write one zone's static color. Returns firmware status."""
        self.enable_keyboard_panel()
        status, _ = self._outputs(self._call("SetGamingRgbKb", encode_rgb_kb(zone_mask, r, g, b)))
        return status

    def set_kb_effect(self, mode: int, speed: int, brightness: int,
                      r: int, g: int, b: int, direction: int = 0) -> int:
        """Enable the panel, then write the 16-byte effect payload. Returns firmware status."""
        self.enable_keyboard_panel()
        payload = encode_kb_backlight(mode, speed, brightness, r, g, b, direction)
        status, _ = self._outputs(self._call("SetGamingKBBacklight", list(payload)))
        return status

    def get_kb_state(self) -> Optional[dict]:
        """Read back the keyboard effect state (verified decode: byte 0 mode, byte 2 brightness)."""
        try:
            status, value = self._outputs(self._call("GetGamingKBBacklight", 1))
        except AcerWmiError:
            return None
        if status != STATUS_OK or value is None:
            return None
        try:
            data = bytes(int(x) for x in value)
        except (TypeError, ValueError):
            return None
        return decode_kb_backlight_reply(data)


class AcerWmiError(RuntimeError):
    """Transport-level failure talking to the Acer firmware WMI interface."""


# --- LibreHardwareMonitor bridge (sensor fallback) ---------------------------------

class LhmBridge:
    """Optional LibreHardwareMonitor access via pythonnet (bundled LibreHardwareMonitorLib.dll).

    Degrades to ``available = False`` when pythonnet/the DLL is missing (e.g. on Linux CI).
    """

    def __init__(self, dll_dir: Optional[str] = None) -> None:
        self.available = False
        self._computer = None
        try:
            import clr  # type: ignore  # noqa: PLC0415  (pythonnet, Windows)
            from pathlib import Path  # noqa: PLC0415
            if dll_dir:
                clr.AddReference(str(Path(dll_dir) / "LibreHardwareMonitorLib"))
            else:
                clr.AddReference("LibreHardwareMonitorLib")
            from LibreHardwareMonitor.Hardware import Computer  # type: ignore
            c = Computer()
            c.IsCpuEnabled = True
            c.IsGpuEnabled = True
            c.IsMemoryEnabled = True
            c.Open()
            self._computer = c
            self.available = True
        except Exception as exc:  # pythonnet or DLL unavailable
            log.info("LibreHardwareMonitor unavailable: %s", exc)
            self._computer = None

    def read(self) -> dict:
        """Return {('cpu'|'gpu'|'mem', sensor_name): value} for all current sensors."""
        out: dict = {}
        if not self._computer:
            return out
        try:
            from LibreHardwareMonitor.Hardware import HardwareType  # type: ignore
            kind_map = {HardwareType.Cpu: "cpu", HardwareType.GpuAmd: "gpu",
                        HardwareType.GpuNvidia: "gpu", HardwareType.Memory: "mem"}
            for hw in self._computer.Hardware:
                key = kind_map.get(hw.HardwareType)
                if key is None:
                    continue
                hw.Update()
                for s in hw.Sensors:
                    if s.Value is not None:
                        out[(key, str(s.Name))] = float(s.Value)
                for sub in hw.SubHardware:
                    sub.Update()
                    for s in sub.Sensors:
                        if s.Value is not None:
                            out[(key, str(s.Name))] = float(s.Value)
        except Exception as exc:
            log.warning("LHM read failed: %s", exc)
        return out

    def close(self) -> None:
        """Close the LHM computer handle (never raises)."""
        try:
            if self._computer:
                self._computer.Close()
        except Exception:
            pass
