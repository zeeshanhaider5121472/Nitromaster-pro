"""Hardware monitoring dashboard page."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from nitromaster.ui.theme import ACCENT_CYAN, ACCENT_GREEN, ACCENT_MAGENTA
from nitromaster.ui.widgets.cards import SectionHeader, StatCard, ValueBar
from nitromaster.ui.widgets.gauge import CircularGauge


class DashboardPage(QWidget):
    """Live CPU / GPU / RAM telemetry with gauges and stat tiles."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.addWidget(SectionHeader("Hardware Dashboard",
                                      "Acer Nitro AN515-45 · Ryzen 5 5600H · GTX 1650 · 16 GB"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(18)

        gauges = QHBoxLayout()
        gauges.setSpacing(18)
        self.cpu_temp = CircularGauge("CPU TEMP", "°C", 105, ACCENT_CYAN)
        self.cpu_temp.set_thresholds(0.81, 0.90)   # 85 °C warn, 95 °C danger (Tjmax 105)
        self.cpu_usage = CircularGauge("CPU USAGE", "%", 100, ACCENT_GREEN)
        self.gpu_temp = CircularGauge("GPU TEMP", "°C", 100, ACCENT_MAGENTA)
        self.gpu_temp.set_thresholds(0.80, 0.90)
        self.gpu_usage = CircularGauge("GPU USAGE", "%", 100, ACCENT_CYAN)
        for g in (self.cpu_temp, self.cpu_usage, self.gpu_temp, self.gpu_usage):
            gauges.addWidget(g)
        lay.addLayout(gauges)

        tiles = QGridLayout()
        tiles.setSpacing(14)
        self.cpu_clock = StatCard("CPU effective clock", ACCENT_CYAN)
        self.cpu_fan = StatCard("CPU fan", ACCENT_GREEN)
        self.gpu_fan = StatCard("GPU fan", ACCENT_MAGENTA)
        self.gpu_power = StatCard("GPU power (TGP)", ACCENT_CYAN)
        self.vram = StatCard("VRAM used", ACCENT_MAGENTA)
        self.mode_tile = StatCard("Active mode", ACCENT_GREEN)
        for i, w in enumerate((self.cpu_clock, self.cpu_fan, self.gpu_fan,
                               self.gpu_power, self.vram, self.mode_tile)):
            tiles.addWidget(w, i // 3, i % 3)
        lay.addLayout(tiles)

        bars = QVBoxLayout()
        self.ram_bar = ValueBar("MEMORY · 16 GB", ACCENT_GREEN)
        self.vram_bar = ValueBar("VIDEO MEMORY · GTX 1650", ACCENT_MAGENTA)
        self.gpu_load_bar = ValueBar("GPU LOAD · GTX 1650", ACCENT_CYAN)
        for b in (self.ram_bar, self.vram_bar, self.gpu_load_bar):
            bars.addWidget(b)
        lay.addLayout(bars)
        lay.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)

    def update_sample(self, sample: dict) -> None:
        """Render one telemetry sample emitted by the poll worker."""
        cpu = sample.get("cpu")
        ram = sample.get("ram")
        gpu = sample.get("gpu")
        if cpu is not None:
            self.cpu_temp.set_value(cpu.temp_c)
            self.cpu_usage.set_value(cpu.usage_total)
            clock = f"{cpu.effective_mhz:.0f} MHz" if cpu.effective_mhz else f"~{cpu.nominal_mhz} MHz"
            self.cpu_clock.set_value(clock, sub=f"{cpu.thread_count} threads · boost up to 4.2 GHz")
        if ram is not None:
            self.ram_bar.set_value(ram.percent, f"{ram.used_gb:.1f} / {ram.total_gb:.1f} GB")
        if gpu is not None:
            nv = gpu.nvidia
            if nv is not None and not nv.error:
                self.gpu_temp.set_value(gpu.gpu_temp_c if gpu.gpu_temp_c is not None else nv.temp_c)
                self.gpu_usage.set_value(nv.util_gpu)
                self.gpu_load_bar.set_value(nv.util_gpu or 0.0,
                                            f"{nv.util_gpu or 0:.0f}% · {nv.core_mhz or 0:.0f} MHz")
                if nv.mem_total:
                    pct = 100.0 * (nv.mem_used or 0) / nv.mem_total
                    self.vram_bar.set_value(pct, f"{(nv.mem_used or 0) / 2**20:.0f} / {nv.mem_total / 2**20:.0f} MB")
                    self.vram.set_value(f"{(nv.mem_used or 0) / 2**20:.0f} MB",
                                        bar_value=pct, sub=nv.name or "GTX 1650")
                self.gpu_power.set_value(f"{nv.power_w:.1f} W" if nv.power_w is not None else "--",
                                         sub=f"limit {nv.power_limit_w:.0f} W" if nv.power_limit_w else "")
            elif nv is not None and nv.error:
                self.gpu_usage.set_value(None)
                self.gpu_power.set_value("--", sub=nv.error)
            if gpu.gpu_temp_c is not None:
                self.gpu_temp.set_value(gpu.gpu_temp_c)
            if gpu.gpu_fan_rpm is not None:
                self.gpu_fan.set_value(f"{gpu.gpu_fan_rpm} RPM", sub="firmware sensor")
        self._update_fans(sample)

    def _update_fans(self, sample: dict) -> None:
        """Fan RPM values ride along in the gpu sample (firmware sensors)."""
        gpu = sample.get("gpu")
        if gpu is None:
            return
        if gpu.cpu_fan_rpm is not None:
            self.cpu_fan.set_value(f"{gpu.cpu_fan_rpm} RPM", sub="firmware sensor")
        else:
            self.cpu_fan.set_value("--", sub="run Fan page calibration")
        if gpu.gpu_fan_rpm is not None:
            self.gpu_fan.set_value(f"{gpu.gpu_fan_rpm} RPM", sub="firmware sensor")

    def set_active_mode(self, mode_title: str) -> None:
        """Show the current system mode in the dashboard tile."""
        self.mode_tile.set_value(mode_title)
