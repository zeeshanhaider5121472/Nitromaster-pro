"""Unit tests: state store, baseline serialization, keyboard state, app profiles."""
from __future__ import annotations

import pytest

from nitromaster.core.cooling.keyboard_backlight import KeyboardState, ZoneColor
from nitromaster.core.graphics.app_profiles import AppProfile, AppProfileStore
from nitromaster.core.graphics.gpu_switcher import GPU_PREF_DGPU, GPU_PREF_IGPU
from nitromaster.core.power.baseline import Baseline
from nitromaster.utils.state_store import StateStore


class TestStateStore:
    def test_save_load_roundtrip(self, state_dir):
        store = StateStore()
        assert store.save("cfg", {"a": 1, "b": [1, 2]}) is True
        assert store.load("cfg") == {"a": 1, "b": [1, 2]}

    def test_missing_returns_default(self, state_dir):
        store = StateStore()
        assert store.load("nope") is None
        assert store.load("nope", default={}) == {}

    def test_corrupt_returns_default(self, state_dir):
        store = StateStore()
        store.path("bad").write_text("{not json", encoding="utf-8")
        assert store.load("bad", default="fallback") == "fallback"

    def test_delete(self, state_dir):
        store = StateStore()
        store.save("gone", 1)
        store.delete("gone")
        assert store.load("gone") is None
        store.delete("gone")  # idempotent


class TestBaseline:
    def test_dict_roundtrip(self):
        b = Baseline(
            created_at=123.0, power_scheme_guid="381b4222-f694-41f0-9685-ff5bb260df2e",
            power_scheme_name="Balanced",
            power_settings={"abc": {"ac": 2, "dc": 1, "sub": "sub-guid"}},
            fan_cpu_mode=3, fan_gpu_mode=1, fan_cpu_duty=55, fan_gpu_duty=None,
            thermal_profile=1, kb_state={"mode": 0, "brightness": 80}, brightness=50,
        )
        restored = Baseline.from_dict(b.to_dict())
        assert restored.power_scheme_guid == b.power_scheme_guid
        assert restored.power_settings["abc"]["ac"] == 2
        assert restored.fan_cpu_duty == 55
        assert restored.kb_state["brightness"] == 80


class TestKeyboardState:
    def test_roundtrip(self):
        s = KeyboardState(
            zones=[ZoneColor(1, 2, 3), ZoneColor(4, 5, 6), ZoneColor(7, 8, 9), ZoneColor(10, 11, 12)],
            mode=3, speed=2, brightness=90, direction=1, enabled=True,
        )
        restored = KeyboardState.from_dict(s.to_dict())
        assert restored.mode == 3
        assert restored.zones[2].r == 7
        assert restored.direction == 1

    def test_zone_padded_to_four(self):
        s = KeyboardState.from_dict({"zones": [{"r": 9, "g": 9, "b": 9}]})
        assert len(s.zones) == 4
        assert s.zones[3].r == 255   # default red padding

    def test_zone_validation(self):
        with pytest.raises(ValueError):
            ZoneColor(300, 0, 0).validate()


class TestAppProfiles:
    def test_validate(self):
        with pytest.raises(ValueError):
            AppProfile("C:/no/extension").validate()
        with pytest.raises(ValueError):
            AppProfile("C:/x.exe", preferred_gpu=7).validate()

    def test_detect_name(self):
        assert AppProfileStore.detect_name(r"C:\Games\My_Game\game.exe") == "game"
        assert AppProfileStore.detect_name(r"C:\Tools\My_Game.exe") == "My Game"

    def _store(self, state_dir):
        ps = AppProfileStore()
        ps.switcher = FakeSwitcher()   # no registry on Linux
        return ps

    def test_crud(self, state_dir):
        ps = self._store(state_dir)
        p = AppProfile(r"C:\Games\game.exe", "game", preferred_gpu=GPU_PREF_DGPU)
        assert ps.add(p) is True
        assert len(ps.list()) == 1
        p2 = AppProfile(r"C:\Games\game.exe", "game", preferred_gpu=GPU_PREF_IGPU)
        ps.add(p2)                          # upsert by path
        assert len(ps.list()) == 1
        assert ps.list()[0].preferred_gpu == GPU_PREF_IGPU
        ps.remove(r"C:\Games\game.exe")
        assert ps.list() == []

    def test_apply_mode_forces_only_explicit_entries(self, state_dir):
        ps = self._store(state_dir)
        ps.add(AppProfile(r"C:\Games\game.exe", "game", preferred_gpu=GPU_PREF_DGPU))
        ps.add(AppProfile(r"C:\Tools\tool.exe", "tool", preferred_gpu=0))
        assert ps.apply_mode("gaming") == 2
        assert ps.switcher.written[r"C:\Games\game.exe"] == GPU_PREF_DGPU   # forced
        assert ps.switcher.written[r"C:\Tools\tool.exe"] == 0               # auto stays auto
        assert ps.apply_mode("normal") == 2


class FakeSwitcher:
    """In-memory GpuSwitcher stand-in for tests."""

    def __init__(self):
        self.written = {}

    def set_preference(self, exe_path, pref):
        self.written[exe_path] = pref
        return True

    def clear_preference(self, exe_path):
        self.written.pop(exe_path, None)
        return True
