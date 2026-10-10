"""Unit tests: ambient screen-sync color logic and engine loop (pure + fakes)."""
from __future__ import annotations

import time

import pytest

from nitromaster.core.cooling.ambient_sync import (
    AmbientSyncEngine, chroma, dequantize, dominant_color, lerp_color, lerp_state,
    luminance, quantize, region_samples,
)
from nitromaster.core.cooling.keyboard_backlight import KeyboardBacklight
from nitromaster.core.monitoring.sensors_backend import KB_ZONES


def solid_bgra(width: int, height: int, rgb) -> bytes:
    """Build a BGRA buffer filled with one color."""
    r, g, b = rgb
    pix = bytes((b, g, r, 255))
    return pix * (width * height)


class TestColorMath:
    def test_quantize_roundtrip_center(self):
        q = quantize((200, 100, 50))
        assert quantize(dequantize(q)) == q

    def test_chroma_and_luma(self):
        assert chroma((255, 0, 0)) == 255
        assert chroma((128, 128, 128)) == 0
        assert luminance((0, 0, 0)) == 0
        assert luminance((255, 255, 255)) == pytest.approx(255)

    def test_dominant_prefers_saturated(self):
        # mostly gray background, one strong red area
        samples = [(120, 120, 120)] * 50 + [(230, 20, 20)] * 10
        r, g, b = dominant_color(samples)
        assert r > 150 and g < 80 and b < 80

    def test_dominant_ignores_dark(self):
        samples = [(5, 5, 5)] * 40 + [(0, 200, 60)] * 8
        r, g, b = dominant_color(samples)
        assert g > 150 and r < 80

    def test_dominant_fallback_average_when_all_gray(self):
        samples = [(100, 100, 100)] * 10 + [(110, 110, 110)] * 10
        r, g, b = dominant_color(samples)
        assert abs(r - g) <= 3 and abs(g - b) <= 3   # neutral gray average

    def test_dominant_empty_input(self):
        assert dominant_color([]) == (40, 40, 40)

    def test_lerp_clamping(self):
        assert lerp_color((0, 0, 0), (100, 100, 100), -1) == (0, 0, 0)
        assert lerp_color((0, 0, 0), (100, 100, 100), 2) == (100, 100, 100)
        assert lerp_color((0, 0, 0), (100, 200, 0), 0.5) == (50, 100, 0)

    def test_lerp_state(self):
        out = lerp_state([(0, 0, 0)] * 4, [(100, 0, 0)] * 4, 0.5)
        assert out == [(50, 0, 0)] * 4


class TestRegionSamples:
    def test_four_strips_left_to_right(self):
        width, height = 8, 2
        buf = bytearray()
        for _y in range(height):
            for x in range(width):
                # left half red, right half blue (BGRA order)
                if x < width // 2:
                    buf += bytes((0, 0, 255, 255))
                else:
                    buf += bytes((255, 0, 0, 255))
        strips = region_samples(bytes(buf), width, height, n_regions=4)
        assert len(strips) == 4
        assert dominant_color(strips[0])[0] > 150     # left strips = red
        assert dominant_color(strips[3])[2] > 150     # right strips = blue

    def test_invalid_buffer(self):
        with pytest.raises(ValueError):
            region_samples(b"\x00" * 3, 2, 2, 4)
        with pytest.raises(ValueError):
            region_samples(solid_bgra(2, 2, (1, 2, 3)), 2, 2, 0)


class FakeSampler:
    available = True

    def __init__(self, width=8, height=2, color=(200, 30, 30)):
        self.width, self.height, self.color = width, height, color

    def grab(self):
        return self.width, self.height, solid_bgra(self.width, self.height, self.color)


class FakeAcer:
    """Records zone writes."""

    def __init__(self):
        self.writes = []

    def set_zone_color(self, mask, r, g, b):
        self.writes.append((mask, r, g, b))
        return 0


class TestAmbientEngine:
    def test_tick_applies_smoothed_zone_colors(self, state_dir):
        acer = FakeAcer()
        kb = KeyboardBacklight(acer=None)
        engine = AmbientSyncEngine(kb, acer=acer, fade=1.0, per_zone=True,
                                   sampler=FakeSampler(color=(200, 30, 30)))
        colors = engine.tick()
        assert len(colors) == len(KB_ZONES)
        assert all(c[0] > 150 for c in colors)            # red dominant
        assert len(acer.writes) == len(KB_ZONES)
        assert {w[0] for w in acer.writes} == set(KB_ZONES)

    def test_single_color_mode_merges_strips(self, state_dir):
        acer = FakeAcer()
        kb = KeyboardBacklight(acer=None)
        engine = AmbientSyncEngine(kb, acer=acer, fade=1.0, per_zone=False,
                                   sampler=FakeSampler(color=(10, 200, 10)))
        colors = engine.tick()
        assert len(set(colors)) == 1                      # identical across zones
        assert colors[0][1] > 150                         # green

    def test_fade_smooths_between_states(self, state_dir):
        acer = FakeAcer()
        kb = KeyboardBacklight(acer=None)
        engine = AmbientSyncEngine(kb, acer=acer, fade=0.0, per_zone=True,
                                   sampler=FakeSampler(color=(200, 30, 30)))
        first = engine.tick()          # from black toward red
        assert first[0][0] < 200      # not jumped straight to target
        second = engine.tick()
        assert second[0][0] >= first[0][0]   # converging upward

    def test_stop_persists_state(self, state_dir):
        acer = FakeAcer()
        kb = KeyboardBacklight(acer=None)
        engine = AmbientSyncEngine(kb, acer=acer, fade=1.0,
                                   sampler=FakeSampler(color=(200, 30, 30)))
        engine.tick()
        engine.stop(persist=True)
        reloaded = KeyboardBacklight(acer=None)
        assert reloaded.state.zones[0].r == engine.last_colors[0][0]

    def test_degrades_without_sampler(self, state_dir):
        kb = KeyboardBacklight(acer=None)
        engine = AmbientSyncEngine(kb, acer=None, sampler=type("S", (), {"available": False})())
        engine.start()
        time.sleep(0.05)
        engine.stop(persist=False)
        assert engine.last_colors == [(0, 0, 0)] * len(KB_ZONES)
