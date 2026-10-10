"""Lighting page: 4-zone RGB keyboard, effects and ambient screen-color sync."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from nitromaster.core.cooling.ambient_sync import AmbientSyncEngine
from nitromaster.core.cooling.keyboard_backlight import KeyboardBacklight, ZoneColor
from nitromaster.core.monitoring.sensors_backend import KB_EFFECT_NAMES
from nitromaster.ui.theme import ACCENT_CYAN, ACCENT_MAGENTA, CARD, BORDER
from nitromaster.ui.widgets.cards import SectionHeader, StatusPill


class LightingPage(QWidget):
    """Keyboard backlight control: per-zone colors, effects and screen-ambience mode."""

    ambient_toggled = pyqtSignal(bool)

    def __init__(self, keyboard: KeyboardBacklight,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.keyboard = keyboard
        self.ambient: Optional[AmbientSyncEngine] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.addWidget(SectionHeader(
            "Keyboard Lighting",
            "4-zone RGB · colors re-applied at startup (firmware resets to red on power cycle)"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(16)

        # --- per-zone colors -------------------------------------------------------
        zones = QGroupBox("Zone Colors")
        zl = QGridLayout(zones)
        self.zone_btns: list[QPushButton] = []
        for i in range(4):
            btn = QPushButton(f"Zone {i + 1}")
            btn.setFixedHeight(56)
            btn.clicked.connect(lambda _c, idx=i: self._pick_zone(idx))
            self.zone_btns.append(btn)
            zl.addWidget(btn, i // 2, i % 2)
        row = QHBoxLayout()
        self.all_btn = QPushButton("Set all zones…")
        self.all_btn.setObjectName("accent")
        self.all_btn.clicked.connect(self._pick_all)
        self.off_btn = QPushButton("Lights off")
        self.off_btn.setObjectName("danger")
        self.off_btn.clicked.connect(self._off)
        row.addWidget(self.all_btn)
        row.addWidget(self.off_btn)
        row.addStretch(1)
        zl.addLayout(row, 2, 0, 1, 2)
        lay.addWidget(zones)

        # --- effects ---------------------------------------------------------------
        effects = QGroupBox("Effect")
        el = QGridLayout(effects)
        el.addWidget(QLabel("Effect"), 0, 0)
        self.effect_box = QComboBox()
        for mode_id in sorted(KB_EFFECT_NAMES):
            self.effect_box.addItem(KB_EFFECT_NAMES[mode_id], mode_id)
        el.addWidget(self.effect_box, 0, 1)
        el.addWidget(QLabel("Speed"), 1, 0)
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(0, 255)
        el.addWidget(self.speed, 1, 1)
        el.addWidget(QLabel("Brightness"), 2, 0)
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(0, 255)
        self.brightness.setValue(200)
        el.addWidget(self.brightness, 2, 1)
        self.apply_effect_btn = QPushButton("Apply effect")
        self.apply_effect_btn.setObjectName("accent")
        self.apply_effect_btn.clicked.connect(self._apply_effect)
        el.addWidget(self.apply_effect_btn, 3, 0, 1, 2)
        lay.addWidget(effects)

        # --- ambient screen sync ---------------------------------------------------
        ambient = QGroupBox("Ambient Screen Sync  ·  keyboard follows the screen's colors")
        al = QGridLayout(ambient)
        self.ambient_check = QCheckBox("Enable ambient sync (sample screen → keyboard zones)")
        self.ambient_check.setStyleSheet(f"font-weight: 700; color: {ACCENT_MAGENTA};")
        self.ambient_check.toggled.connect(self._toggle_ambient)
        al.addWidget(self.ambient_check, 0, 0, 1, 3)
        al.addWidget(QLabel("Refresh interval (s)"), 1, 0)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.5, 30.0)
        self.interval.setValue(2.0)
        al.addWidget(self.interval, 1, 1)
        al.addWidget(QLabel("Fade smoothing"), 2, 0)
        self.fade = QSlider(Qt.Orientation.Horizontal)
        self.fade.setRange(0, 100)
        self.fade.setValue(50)
        al.addWidget(self.fade, 2, 1)
        self.per_zone = QCheckBox("Per-zone (4 screen strips)")
        self.per_zone.setChecked(True)
        al.addWidget(self.per_zone, 3, 0, 1, 2)
        self.ambient_status = StatusPill("Ambient sync idle", ACCENT_CYAN)
        al.addWidget(self.ambient_status, 4, 0, 1, 3)
        hint = QLabel("One zone per vertical screen strip · the dominant saturated color of "
                      "each strip is used (dark/gray pixels ignored) · smoothed for comfort.")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        al.addWidget(hint, 5, 0, 1, 3)
        lay.addWidget(ambient)

        self.refresh_btn = QPushButton("Read current firmware state")
        self.refresh_btn.clicked.connect(self._readback)
        lay.addWidget(self.refresh_btn)
        lay.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self._render_zones()

    # --- zone colors -----------------------------------------------------------------

    def _zone_color(self, idx: int) -> QColor:
        z = self.keyboard.state.zones[idx]
        return QColor(z.r, z.g, z.b)

    def _render_zones(self) -> None:
        """Repaint zone buttons with their current colors."""
        for i, btn in enumerate(self.zone_btns):
            c = self._zone_color(i)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {c.name()}; color: #000;"
                f" border: 1px solid {BORDER}; border-radius: 12px; font-weight: 700; }}")

    def _pick_zone(self, idx: int) -> None:
        """Open a color dialog and write one zone."""
        c = QColorDialog.getColor(self._zone_color(idx), self, f"Zone {idx + 1} color")
        if c.isValid():
            self.keyboard.set_zone(idx, ZoneColor(c.red(), c.green(), c.blue()))
            self._render_zones()

    def _pick_all(self) -> None:
        """Open a color dialog and write all zones."""
        c = QColorDialog.getColor(self._zone_color(0), self, "All zones")
        if c.isValid():
            self.keyboard.set_all_zones(ZoneColor(c.red(), c.green(), c.blue()))
            self._render_zones()

    def _off(self) -> None:
        """Turn the panel off."""
        self.keyboard.off()
        self._render_zones()

    # --- effects ----------------------------------------------------------------------

    def _apply_effect(self) -> None:
        """Write the selected effect with current speed/brightness sliders."""
        mode = int(self.effect_box.currentData())
        self.keyboard.set_effect(mode, self.speed.value(), self.brightness.value())

    # --- ambient -----------------------------------------------------------------------

    def _toggle_ambient(self, enabled: bool) -> None:
        """Start/stop the screen-color sync engine."""
        if enabled:
            self.ambient = AmbientSyncEngine(
                self.keyboard,
                interval_s=self.interval.value(),
                fade=self.fade.value() / 100.0,
                per_zone=self.per_zone.isChecked(),
            )
            self.ambient.start()
            self.ambient_status.set_status("Ambient sync running", "#39FF14")
        else:
            if self.ambient is not None:
                self.ambient.stop(persist=True)
                self.ambient = None
            self.ambient_status.set_status("Ambient sync idle", ACCENT_CYAN)
            self._render_zones()
        self.ambient_toggled.emit(enabled)

    def _readback(self) -> None:
        """Show firmware's own idea of the lighting state (silent-success check)."""
        state = self.keyboard.readback()
        if state:
            self.ambient_status.set_status(
                f"firmware: mode {state.get('mode')} brightness {state.get('brightness')}", ACCENT_CYAN)
            self._render_zones()
        else:
            self.ambient_status.set_status("firmware readback unavailable", "#FFB300")

    def shutdown(self) -> None:
        """Stop ambient sync cleanly (called from the main window close handler)."""
        if self.ambient is not None:
            self.ambient.stop(persist=True)
            self.ambient = None
