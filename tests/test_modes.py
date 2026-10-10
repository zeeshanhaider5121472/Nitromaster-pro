"""Unit tests: GPU preference formatting/parsing and mode registry."""
from __future__ import annotations

import pytest

from nitromaster.core.graphics.gpu_switcher import (
    GPU_PREF_AUTO, GPU_PREF_DGPU, GPU_PREF_IGPU, format_gpu_pref, parse_gpu_pref,
)
from nitromaster.core.power.power_modes import (
    MODE_BATTERY_SAVER, MODE_GAMING, MODE_NORMAL, MODE_PERFORMANCE, MODE_ULTRA,
    FAN_MODE_MAX, PROFILE_ECO, PROFILE_TURBO, ModeEngine, ModeSpec,
)


class TestGpuPreference:
    def test_format(self):
        assert format_gpu_pref(GPU_PREF_AUTO) == "GpuPreference=0;"
        assert format_gpu_pref(GPU_PREF_IGPU) == "GpuPreference=1;"
        assert format_gpu_pref(GPU_PREF_DGPU) == "GpuPreference=2;"

    def test_format_invalid(self):
        with pytest.raises(ValueError):
            format_gpu_pref(5)

    def test_parse_roundtrip(self):
        for pref in (GPU_PREF_AUTO, GPU_PREF_IGPU, GPU_PREF_DGPU):
            assert parse_gpu_pref(format_gpu_pref(pref)) == pref

    def test_parse_garbage_defaults_to_auto(self):
        assert parse_gpu_pref(None) == GPU_PREF_AUTO
        assert parse_gpu_pref("") == GPU_PREF_AUTO
        assert parse_gpu_pref("nonsense") == GPU_PREF_AUTO
        assert parse_gpu_pref("GpuPreference=9;") == GPU_PREF_AUTO

    def test_parse_tolerates_whitespace(self):
        assert parse_gpu_pref("GpuPreference = 2 ;") == GPU_PREF_DGPU


class TestModeRegistry:
    def test_all_five_modes_present(self):
        specs = ModeEngine.specs()
        assert set(specs) == {MODE_NORMAL, MODE_BATTERY_SAVER, MODE_ULTRA,
                              MODE_PERFORMANCE, MODE_GAMING}

    def test_normal_restores_baseline(self):
        spec = ModeEngine.specs()[MODE_NORMAL]
        assert spec.scheme_guid is None
        assert spec.power_settings == []     # restore path, not a settings write

    def test_ultra_is_aggressive_but_reversible(self):
        spec = ModeEngine.specs()[MODE_ULTRA]
        assert spec.process_policy == "ultra"
        assert spec.brightness is not None and spec.brightness <= 30
        assert spec.thermal_profile == PROFILE_ECO
        assert spec.stop_services is True

    def test_gaming_uses_turbo_and_max_fan(self):
        spec = ModeEngine.specs()[MODE_GAMING]
        assert spec.fan_mode == FAN_MODE_MAX
        assert spec.thermal_profile == PROFILE_TURBO
        assert spec.oc_afterburner_profile is not None

    def test_mode_specs_validated(self):
        with pytest.raises(ValueError):
            ModeSpec("bad", "Bad", "Bad", fan_mode=99)   # dataclass itself does not validate
        # engine-level guard:
        with pytest.raises(ValueError):
            ModeEngine().apply("does-not-exist")
