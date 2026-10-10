"""Unit tests: fan curve interpolation and persistence."""
from __future__ import annotations

import pytest

from nitromaster.core.cooling.fan_controller import CurvePoint, FanCurve, FanController


def make_curve() -> FanCurve:
    return FanCurve(points=[CurvePoint(40, 20), CurvePoint(60, 60), CurvePoint(80, 100)])


class TestFanCurve:
    def test_clamping(self):
        c = make_curve()
        assert c.duty_for(10) == 20
        assert c.duty_for(99) == 100

    def test_exact_points(self):
        c = make_curve()
        assert c.duty_for(40) == 20
        assert c.duty_for(60) == 60
        assert c.duty_for(80) == 100

    def test_interpolation(self):
        c = make_curve()
        assert c.duty_for(50) == 40    # midpoint 20..60
        assert c.duty_for(70) == 80    # midpoint 60..100

    def test_unsorted_points_normalized(self):
        c = FanCurve(points=[CurvePoint(80, 100), CurvePoint(40, 20), CurvePoint(60, 60)])
        assert [p.temp_c for p in c.normalized()] == [40, 60, 80]
        assert c.duty_for(50) == 40

    def test_empty_curve_raises(self):
        with pytest.raises(ValueError):
            FanCurve().duty_for(50)

    def test_point_validation(self):
        with pytest.raises(ValueError):
            CurvePoint(50, 150)
        with pytest.raises(ValueError):
            CurvePoint(500, 50)

    def test_dict_roundtrip(self):
        c = make_curve()
        restored = FanCurve.from_dict(c.to_dict())
        assert [p.temp_c for p in restored.normalized()] == [40, 60, 80]
        assert restored.duty_for(50) == 40

    def test_default_curve_sane(self):
        d = FanCurve.default_cool()
        pts = d.normalized()
        assert pts == sorted(pts, key=lambda p: p.temp_c)
        duties = [p.duty for p in pts]
        assert duties == sorted(duties)          # monotonic
        assert d.duty_for(200) == 100            # always capped at 100


class TestFanController:
    def test_without_acer_degrades(self):
        fc = FanController(acer=None)
        assert fc.set_profile("auto") is False
        assert fc.start_curve(lambda: 50.0) is False
        assert fc.curve_running is False

    def test_unknown_profile_rejected(self):
        fc = FanController(acer=None)
        with pytest.raises(ValueError):
            fc.set_profile("warp-speed")
