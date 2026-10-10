"""Unit tests: Acer firmware protocol codecs (pure logic, runs on any OS)."""
from __future__ import annotations

import pytest

from nitromaster.core.monitoring.sensors_backend import (
    FAN_BEHAVIOR_AUTO, FAN_BEHAVIOR_CUSTOM, FAN_BEHAVIOR_MAX,
    FAN_CPU, FAN_GPU, FAN_MODE_AUTO, FAN_MODE_CUSTOM, FAN_MODE_MAX,
    KB_EFFECT_STATIC, KB_EFFECT_WAVE, KB_ZONES,
    decode_fan_behavior_reply, decode_fan_speed_reply, decode_kb_backlight_reply,
    decode_misc_setting_reply, decode_sysinfo_reply,
    encode_fan_behavior, encode_fan_speed, encode_kb_backlight,
    encode_misc_setting, encode_rgb_kb,
)


class TestFanBehavior:
    def test_known_good_constants(self):
        assert encode_fan_behavior(FAN_MODE_AUTO, FAN_MODE_AUTO) == FAN_BEHAVIOR_AUTO
        assert encode_fan_behavior(FAN_MODE_MAX, FAN_MODE_MAX) == FAN_BEHAVIOR_MAX
        assert encode_fan_behavior(FAN_MODE_CUSTOM, FAN_MODE_CUSTOM) == FAN_BEHAVIOR_CUSTOM

    def test_mixed_modes(self):
        val = encode_fan_behavior(FAN_MODE_CUSTOM, FAN_MODE_AUTO)
        assert (val >> 16) & 0x3 == FAN_MODE_CUSTOM
        assert (val >> 22) & 0x3 == FAN_MODE_AUTO
        assert val & 0xFFFF == 0x0009  # both fans bitmap

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError):
            encode_fan_behavior(0, FAN_MODE_AUTO)
        with pytest.raises(ValueError):
            encode_fan_behavior(FAN_MODE_AUTO, 7)

    def test_reply_decode(self):
        # status byte 0, CPU mode at bits 9:8, GPU mode at bits 15:14
        val = 0x0000 | (FAN_MODE_MAX << 8) | (FAN_MODE_CUSTOM << 14)
        cpu, gpu, status = decode_fan_behavior_reply(val)
        assert (cpu, gpu, status) == (FAN_MODE_MAX, FAN_MODE_CUSTOM, 0)


class TestFanSpeed:
    def test_encode(self):
        assert encode_fan_speed(FAN_CPU, 0) == 0x01
        assert encode_fan_speed(FAN_GPU, 100) == 0x04 | (100 << 8)
        assert encode_fan_speed(FAN_CPU, 55) == 0x01 | (55 << 8)

    def test_percent_bounds(self):
        with pytest.raises(ValueError):
            encode_fan_speed(FAN_CPU, 101)
        with pytest.raises(ValueError):
            encode_fan_speed(FAN_CPU, -1)

    def test_selector_validation(self):
        with pytest.raises(ValueError):
            encode_fan_speed(0x02, 50)

    def test_reply_decode(self):
        status, percent = decode_fan_speed_reply(0x0002 | (0 | (70 << 8)))
        # low byte is status (2 = invalid param), value bits 15:8
        assert status == 0x02
        assert percent == 70


class TestSysInfo:
    def test_ok_reading(self):
        # status byte 0, reading in bits 23:8
        val = (57 << 8) | 0x00
        assert decode_sysinfo_reply(val, 0xFF) == 57

    def test_unavailable(self):
        assert decode_sysinfo_reply(0x01 | (57 << 8), 0xFF) is None

    def test_rpm_mask(self):
        val = (2200 << 8) | 0x00
        assert decode_sysinfo_reply(val, 0xFFFF) == 2200


class TestRgbKeyboard:
    def test_zone_mask_validation(self):
        with pytest.raises(ValueError):
            encode_rgb_kb(0x10, 255, 0, 0)
        with pytest.raises(ValueError):
            encode_rgb_kb(0, 255, 0, 0)

    def test_color_bounds(self):
        with pytest.raises(ValueError):
            encode_rgb_kb(KB_ZONES[0], 256, 0, 0)

    def test_encode(self):
        val = encode_rgb_kb(0x02, 10, 20, 30)
        assert val & 0xFF == 0x02
        assert (val >> 8) & 0xFF == 10
        assert (val >> 16) & 0xFF == 20
        assert (val >> 24) & 0xFF == 30

    def test_backlight_payload_layout(self):
        p = encode_kb_backlight(KB_EFFECT_STATIC, 0, 100, 255, 0, 0)
        assert len(p) == 16
        assert p[0] == KB_EFFECT_STATIC
        assert p[2] == 100
        assert p[3] == 0            # wave flag only for mode 3
        assert p[8] == 0            # byte 8 MUST be 0 (verified AN515-45 quirk)
        assert p[9] == 1
        assert p[5:8] == bytes([255, 0, 0])

    def test_wave_flag(self):
        p = encode_kb_backlight(KB_EFFECT_WAVE, 3, 80, 0, 255, 0, direction=1)
        assert p[3] == 8
        assert p[4] == 1

    def test_backlight_reply_decode(self):
        data = bytes([3, 5, 77, 0, 1, 9, 8, 7, 0, 1, 0, 0, 0, 0, 0, 0])
        state = decode_kb_backlight_reply(data)
        assert state["mode"] == 3
        assert state["brightness"] == 77
        assert (state["r"], state["g"], state["b"]) == (9, 8, 7)
        assert decode_kb_backlight_reply(b"\x01") is None


class TestMiscSetting:
    def test_roundtrip(self):
        assert encode_misc_setting(0x0B, 5) == 0x0B | (5 << 8)
        status, value = decode_misc_setting_reply(0x00 | (5 << 8))
        assert (status, value) == (0, 5)

    def test_refusal_surfaces_in_status(self):
        status, value = decode_misc_setting_reply(0x02 | (5 << 8))
        assert status == 2  # firmware refusal must be checked on get AND set

    def test_bounds(self):
        with pytest.raises(ValueError):
            encode_misc_setting(0x100, 1)
        with pytest.raises(ValueError):
            encode_misc_setting(0x0B, 300)
