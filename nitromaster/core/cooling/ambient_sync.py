"""Screen-ambience keyboard lighting: the keyboard follows the primary colors on screen.

The engine samples the screen at a fixed interval, computes the dominant *colorful*
(near-black/near-gray pixels are ignored) color per vertical screen strip, smooths the
transition, and writes one keyboard zone per strip. Sampling uses plain GDI via ctypes
(BitBlt into a small 32bpp DIB) — no extra dependencies.

Color logic (:func:`dominant_color`, :func:`region_samples`, :func:`lerp_color`, …) is
pure Python and unit-tested on any OS; :class:`ScreenSampler` only works on Windows.
"""
from __future__ import annotations

import threading
from typing import Optional, Sequence

from nitromaster.core.cooling.keyboard_backlight import KeyboardBacklight, ZoneColor
from nitromaster.core.monitoring.sensors_backend import KB_ZONES, AcerWmiBackend, AcerWmiError
from nitromaster.utils.logging_setup import get_logger
from nitromaster.utils.platform import IS_WINDOWS

log = get_logger("ambient")

Color = tuple[int, int, int]


# --- pure color logic ---------------------------------------------------------------

def quantize(c: Color, bits: int = 4) -> Color:
    """Bucket one color to *bits* per channel (default 16 levels) for histogramming."""
    shift = 8 - bits
    mask = (1 << bits) - 1
    r, g, b = c
    return ((r >> shift) & mask, (g >> shift) & mask, (b >> shift) & mask)


def dequantize(q: Color, bits: int = 4) -> Color:
    """Expand a quantized bucket back to the middle of its 0..255 range."""
    shift = 8 - bits
    add = 1 << (shift - 1)
    return tuple((ch << shift) + add for ch in q)  # type: ignore[return-value]


def chroma(c: Color) -> int:
    """Colorfulness = max channel - min channel (0 = gray)."""
    return max(c) - min(c)


def luminance(c: Color) -> float:
    """Rec. 601 luma."""
    r, g, b = c
    return 0.299 * r + 0.587 * g + 0.114 * b


def dominant_color(samples: Sequence[Color], min_chroma: int = 30,
                   dark_cutoff: int = 25) -> Color:
    """Return the dominant *saturated* color of a pixel sample set.

    Strategy: ignore near-black and near-gray pixels, histogram the rest (quantized)
    weighted by chroma, and take the brightest member of the winning bucket.
    Falls back to the average color of all samples (or dark gray for empty input).
    """
    if not samples:
        return (40, 40, 40)
    hist: dict[Color, tuple[int, float]] = {}
    total = (0, 0, 0)
    for c in samples:
        total = (total[0] + c[0], total[1] + c[1], total[2] + c[2])
        if luminance(c) < dark_cutoff or chroma(c) < min_chroma:
            continue
        key = quantize(c)
        count, score = hist.get(key, (0, 0.0))
        hist[key] = (count + 1, score + chroma(c))
    if not hist:
        n = len(samples)
        return (total[0] // n, total[1] // n, total[2] // n)
    best_key, (count, score) = max(hist.items(), key=lambda kv: kv[1][1])
    # brightest member of the winning bucket keeps colors vivid
    members = [c for c in samples if quantize(c) == best_key]
    best = max(members, key=luminance)
    return best if chroma(best) >= min_chroma else dequantize(best_key)


def region_samples(bgra: bytes, width: int, height: int,
                   n_regions: int = 4) -> list[list[Color]]:
    """Split a BGRA pixel buffer into *n_regions* vertical strips of RGB samples.

    Pixels are taken with an adaptive stride so each strip yields a bounded sample set.
    """
    if width <= 0 or height <= 0 or len(bgra) < width * height * 4:
        raise ValueError("invalid pixel buffer")
    if n_regions <= 0:
        raise ValueError("n_regions must be positive")
    strips: list[list[Color]] = [[] for _ in range(n_regions)]
    stride = max(1, (width * height) // (n_regions * 512))
    index = 0
    for y in range(height):
        for x in range(width):
            if index % stride == 0:
                off = (y * width + x) * 4
                b, g, r = bgra[off], bgra[off + 1], bgra[off + 2]
                strips[min(n_regions - 1, x * n_regions // width)].append((r, g, b))
            index += 1
    return strips


def lerp_color(a: Color, b: Color, t: float) -> Color:
    """Linear interpolation between two colors (t clamped to 0..1)."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def lerp_state(prev: Sequence[Color], target: Sequence[Color], t: float) -> list[Color]:
    """Smooth a whole zone-color state toward *target* (used for fade transitions)."""
    return [lerp_color(p, g, t) for p, g in zip(prev, target)]


# --- screen sampler (Windows GDI via ctypes) ----------------------------------------

class ScreenSampler:
    """Downscaled virtual-screen capture (BitBlt into a small 32bpp DIB)."""

    def __init__(self, sample_width: int = 64, sample_height: int = 36) -> None:
        self.available = False
        self.width = sample_width
        self.height = sample_height
        self._buf = None
        self._init_gdi()

    def _init_gdi(self) -> None:
        if not IS_WINDOWS:
            return
        try:
            import ctypes
            from ctypes import wintypes
            self._ctypes = ctypes
            self._wintypes = wintypes
            self._user32 = ctypes.windll.user32
            self._gdi32 = ctypes.windll.gdi32

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                            ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                            ("biClrImportant", wintypes.DWORD)]

            class BITMAPINFO(ctypes.Structure):
                _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                            ("bmiColors", wintypes.DWORD * 3)]

            self._BITMAPINFO = BITMAPINFO
            self._buf = ctypes.create_string_buffer(self.width * self.height * 4)
            self.available = True
        except Exception as exc:
            log.info("GDI screen sampler unavailable: %s", exc)
            self.available = False

    def grab(self) -> tuple[int, int, bytes]:
        """Capture the virtual screen scaled to (width, height); returns BGRA bytes."""
        if not self.available:
            raise RuntimeError("screen sampling requires Windows")
        ctypes = self._ctypes
        wintypes = self._wintypes
        user32, gdi32 = self._user32, self._gdi32
        SRCCOPY = 0x00CC0020
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
        SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
        src = user32.GetDC(0)
        mem = gdi32.CreateCompatibleDC(src)
        bmi = self._BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(self._BITMAPINFO)
        bmi.bmiHeader.biWidth = self.width
        bmi.bmiHeader.biHeight = -self.height   # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        bmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not bmp:
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(0, src)
            raise RuntimeError("CreateDIBSection failed")
        old = gdi32.SelectObject(mem, bmp)
        try:
            x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or self.width
            h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or self.height
            gdi32.StretchBlt(mem, 0, 0, self.width, self.height,
                             src, x, y, w, h, SRCCOPY)
            ctypes.memmove(self._buf, bits, self.width * self.height * 4)
            return self.width, self.height, self._buf.raw
        finally:
            gdi32.SelectObject(mem, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(0, src)


# --- ambient engine -----------------------------------------------------------------

class AmbientSyncEngine(threading.Thread):
    """Continuously maps screen colors to keyboard zones (one zone per screen strip)."""

    def __init__(self, keyboard: KeyboardBacklight,
                 acer: Optional[AcerWmiBackend] = None,
                 interval_s: float = 2.0,
                 fade: float = 0.5,
                 per_zone: bool = True,
                 sampler: Optional[ScreenSampler] = None) -> None:
        super().__init__(name="ambient-sync", daemon=True)
        self.keyboard = keyboard
        self.acer = acer if acer is not None else keyboard.acer
        self.interval_s = max(0.25, float(interval_s))
        self.fade = 0.0 if fade <= 0 else 1.0 if fade > 1 else float(fade)
        self.per_zone = per_zone
        self.sampler = sampler if sampler is not None else ScreenSampler()
        self._stop_event = threading.Event()
        self._last: list[Color] = [(0, 0, 0) for _ in KB_ZONES]
        self.last_colors: list[Color] = list(self._last)

    def run(self) -> None:
        """Sampling loop: screen -> dominant colors -> smoothed zone writes."""
        if not self.sampler.available:
            log.info("ambient sync disabled (screen sampling unavailable)")
            return
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:
                log.debug("ambient tick failed: %s", exc)
            self._stop_event.wait(self.interval_s)

    def tick(self) -> list[Color]:
        """One sample-and-apply cycle; returns the colors applied."""
        width, height, data = self.sampler.grab()
        strips = region_samples(data, width, height, n_regions=len(KB_ZONES))
        targets = [dominant_color(s) for s in strips]
        if not self.per_zone:
            merged = dominant_color([c for s in strips for c in s])
            targets = [merged for _ in KB_ZONES]
        if self.fade >= 1.0:
            self._last = targets
        else:
            self._last = lerp_state(self._last, targets, max(0.15, self.fade))
        self._apply(self._last)
        self.last_colors = list(self._last)
        return self.last_colors

    def _apply(self, colors: Sequence[Color]) -> None:
        """Write zone colors to firmware (panel enable happens inside)."""
        if self.acer is None:
            return
        for mask, (r, g, b) in zip(KB_ZONES, colors):
            try:
                self.acer.set_zone_color(mask, r, g, b)
            except AcerWmiError as exc:
                log.debug("ambient zone write failed: %s", exc)

    def stop(self, persist: bool = True) -> None:
        """Stop the loop; optionally persist the last ambient state to disk."""
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=self.interval_s + 1.0)
        if persist:
            self.keyboard.state.zones = [ZoneColor(r, g, b) for r, g, b in self.last_colors]
            self.keyboard.state.enabled = True
            self.keyboard._save()

    @property
    def running(self) -> bool:
        """True while the sampling loop is alive."""
        return self.is_alive() and not self._stop_event.is_set()
