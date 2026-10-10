"""Fan control page: Auto / Max / Custom duty + userspace fan curve editor."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from nitromaster.core.cooling.fan_controller import (
    FanController, FanCurve, PROFILE_AUTO, PROFILE_CUSTOM, PROFILE_CURVE, PROFILE_MAX,
)
from nitromaster.ui.theme import ACCENT_CYAN, ACCENT_GREEN, ACCENT_MAGENTA
from nitromaster.ui.widgets.cards import SectionHeader, StatCard

_CURVE_PRESETS = {
    "Cool & Quiet": [(45, 15), (60, 30), (70, 50), (80, 75), (90, 100)],
    "Balanced": [(40, 20), (55, 35), (65, 50), (75, 70), (85, 90), (90, 100)],
    "Max Cooling": [(35, 40), (50, 60), (60, 80), (70, 100)],
}


class FanPage(QWidget):
    """Fan profile control with custom duty sliders and a curve engine."""

    profile_apply = pyqtSignal(str, int, int)          # profile, cpu_duty, gpu_duty
    curve_toggled = pyqtSignal(bool)

    def __init__(self, controller: FanController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.controller = controller
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.addWidget(SectionHeader(
            "Fan Control",
            "Acer firmware contract: Auto / Max / Custom duty — curves run in userspace"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(16)

        # --- static profiles -------------------------------------------------------
        profiles = QGroupBox("Fan Profile")
        pl = QHBoxLayout(profiles)
        self.profile_box = QComboBox()
        self.profile_box.addItems(["Auto", "Max (CoolBoost)", "Custom", "Curve"])
        pl.addWidget(self.profile_box)
        self.apply_profile_btn = QPushButton("Apply")
        self.apply_profile_btn.setObjectName("accent")
        self.apply_profile_btn.clicked.connect(self._apply_profile)
        pl.addWidget(self.apply_profile_btn)
        pl.addStretch(1)
        self.profile_status = QLabel("Firmware: --")
        self.profile_status.setObjectName("subtitle")
        pl.addWidget(self.profile_status)
        lay.addWidget(profiles)

        # --- custom duty -----------------------------------------------------------
        duty_box = QGroupBox("Custom Duty (%)")
        dl = QGridLayout(duty_box)
        self.cpu_slider = QSlider(Qt.Orientation.Horizontal)
        self.gpu_slider = QSlider(Qt.Orientation.Horizontal)
        self.cpu_slider.setRange(0, 100)
        self.gpu_slider.setRange(0, 100)
        self.cpu_slider.setValue(60)
        self.gpu_slider.setValue(60)
        self.cpu_duty_lbl = QLabel("60%")
        self.gpu_duty_lbl = QLabel("60%")
        self.cpu_slider.valueChanged.connect(lambda v: self.cpu_duty_lbl.setText(f"{v}%"))
        self.gpu_slider.valueChanged.connect(lambda v: self.gpu_duty_lbl.setText(f"{v}%"))
        dl.addWidget(QLabel("CPU fan"), 0, 0)
        dl.addWidget(self.cpu_slider, 0, 1)
        dl.addWidget(self.cpu_duty_lbl, 0, 2)
        dl.addWidget(QLabel("GPU fan"), 1, 0)
        dl.addWidget(self.gpu_slider, 1, 1)
        dl.addWidget(self.gpu_duty_lbl, 1, 2)
        lay.addWidget(duty_box)

        # --- curve editor ----------------------------------------------------------
        curve_box = QGroupBox("Fan Curve (userspace engine)")
        cl = QGridLayout(curve_box)
        cl.addWidget(QLabel("Preset"), 0, 0)
        self.preset_box = QComboBox()
        self.preset_box.addItems(list(_CURVE_PRESETS.keys()))
        cl.addWidget(self.preset_box, 0, 1)
        self.load_preset_btn = QPushButton("Load preset")
        self.load_preset_btn.clicked.connect(self._load_preset)
        cl.addWidget(self.load_preset_btn, 0, 2)
        self.points_label = QLabel("")
        self.points_label.setObjectName("subtitle")
        self.points_label.setWordWrap(True)
        cl.addWidget(self.points_label, 1, 0, 1, 3)
        self.curve_btn = QPushButton("Start curve engine")
        self.curve_btn.setObjectName("accent")
        self.curve_btn.clicked.connect(self._toggle_curve)
        cl.addWidget(self.curve_btn, 2, 0, 1, 2)
        cl.addWidget(QLabel("Interval (s)"), 2, 2)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(1.0, 60.0)
        self.interval.setValue(5.0)
        cl.addWidget(self.interval, 2, 3)
        lay.addWidget(curve_box)

        # --- live state ------------------------------------------------------------
        tiles = QGridLayout()
        self.cpu_rpm = StatCard("CPU fan", ACCENT_GREEN)
        self.gpu_rpm = StatCard("GPU fan", ACCENT_MAGENTA)
        self.cpu_duty = StatCard("CPU duty", ACCENT_CYAN)
        self.gpu_duty = StatCard("GPU duty", ACCENT_CYAN)
        for i, w in enumerate((self.cpu_rpm, self.gpu_rpm, self.cpu_duty, self.gpu_duty)):
            tiles.addWidget(w, i // 2, i % 2)
        lay.addLayout(tiles)
        self.refresh_btn = QPushButton("Refresh fan state (readback)")
        self.refresh_btn.clicked.connect(self.refresh_state)
        lay.addWidget(self.refresh_btn)
        lay.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)
        self._render_curve()

    # --- actions -------------------------------------------------------------------

    def _apply_profile(self) -> None:
        """Map the combo box to a profile apply request."""
        mapping = {"Auto": PROFILE_AUTO, "Max (CoolBoost)": PROFILE_MAX,
                   "Custom": PROFILE_CUSTOM, "Curve": PROFILE_CURVE}
        profile = mapping[self.profile_box.currentText()]
        self.profile_apply.emit(profile, self.cpu_slider.value(), self.gpu_slider.value())

    def _load_preset(self) -> None:
        """Load a named curve preset into the controller and refresh the label."""
        pts = _CURVE_PRESETS[self.preset_box.currentText()]
        self.controller.curve = FanCurve.from_dict(
            {"points": [{"temp_c": t, "duty": d} for t, d in pts]})
        self._render_curve()

    def _toggle_curve(self) -> None:
        """Start/stop the userspace curve engine (via the main window)."""
        start = not self.controller.curve_running
        self.curve_toggled.emit(start)
        self.curve_btn.setText("Stop curve engine" if start else "Start curve engine")

    def _render_curve(self) -> None:
        """Show the current curve points as text."""
        pts = self.controller.curve.normalized()
        self.points_label.setText(" → ".join(f"{p.temp_c:.0f}°C:{p.duty}%" for p in pts))

    # --- state updates ----------------------------------------------------------------

    def refresh_state(self) -> None:
        """Read fan state back from firmware and update tiles."""
        st = self.controller.refresh_state()
        self.cpu_rpm.set_value(f"{st.cpu_rpm} RPM" if st.cpu_rpm is not None else "--")
        self.gpu_rpm.set_value(f"{st.gpu_rpm} RPM" if st.gpu_rpm is not None else "--")
        self.cpu_duty.set_value(f"{st.cpu_duty}%" if st.cpu_duty is not None else "--")
        self.gpu_duty.set_value(f"{st.gpu_duty}%" if st.gpu_duty is not None else "--")

    def set_status(self, text: str) -> None:
        """Update the profile status line."""
        self.profile_status.setText(text)
