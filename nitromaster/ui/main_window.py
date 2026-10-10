"""Main window: sidebar navigation + stacked pages + background workers."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QCloseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QStatusBar, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from nitromaster import APP_NAME
from nitromaster.core.cooling.fan_controller import (
    FanController, PROFILE_AUTO, PROFILE_CURVE, PROFILE_CUSTOM, PROFILE_MAX,
)
from nitromaster.core.cooling.keyboard_backlight import KeyboardBacklight
from nitromaster.core.graphics.app_profiles import AppProfileStore
from nitromaster.core.monitoring.cpu_monitor import CpuMonitor
from nitromaster.core.monitoring.gpu_monitor import GpuMonitor
from nitromaster.core.monitoring.ram_monitor import RamMonitor
from nitromaster.core.power.baseline import BaselineManager
from nitromaster.core.power.power_modes import ModeEngine
from nitromaster.core.workers import HardwarePollWorker, ModeApplyWorker, PYQT_AVAILABLE
from nitromaster.ui.pages.dashboard import DashboardPage
from nitromaster.ui.pages.fan_page import FanPage
from nitromaster.ui.pages.graphics import GraphicsPage
from nitromaster.ui.pages.lighting import LightingPage
from nitromaster.ui.pages.modes import ModesPage
from nitromaster.ui.pages.settings import SettingsPage
from nitromaster.ui.theme import ACCENT_CYAN, BORDER, CARD
from nitromaster.utils.admin import relaunch_as_admin
from nitromaster.utils.logging_setup import get_logger

log = get_logger("main_window")

_NAV = [
    ("Dashboard", "▦"),
    ("Power Modes", "◑"),
    ("Cooling", "❄"),
    ("Lighting", "✦"),
    ("Graphics", "◈"),
    ("Settings", "⚙"),
]


class MainWindow(QMainWindow):
    """Application shell: navigation, pages, workers and cross-page wiring."""

    def __init__(self, mode_engine: ModeEngine, cpu: CpuMonitor, ram: RamMonitor,
                 gpu: GpuMonitor, fans: FanController, keyboard: KeyboardBacklight,
                 apps: AppProfileStore, baselines: BaselineManager,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 780)
        self.engine = mode_engine
        self.fans = fans
        self.keyboard = keyboard
        self.apps = apps
        self.baselines = baselines

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- sidebar -------------------------------------------------------------
        sidebar = QWidget()
        sidebar.setObjectName("card")
        sidebar.setFixedWidth(220)
        side_lay = QVBoxLayout(sidebar)
        side_lay.setContentsMargins(14, 22, 14, 18)
        side_lay.setSpacing(6)
        brand = QLabel("NitroMaster")
        brand.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {ACCENT_CYAN};")
        brand_sub = QLabel("AN515-45 Control Center")
        brand_sub.setObjectName("subtitle")
        side_lay.addWidget(brand)
        side_lay.addWidget(brand_sub)
        side_lay.addSpacing(18)
        self._nav_buttons: list[QPushButton] = []
        for label, icon in _NAV:
            btn = QPushButton(f"{icon}  {label}")
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _c, i=len(self._nav_buttons): self._goto(i))
            self._nav_buttons.append(btn)
            side_lay.addWidget(btn)
        side_lay.addStretch(1)
        self.mode_pill = QLabel("Mode: Normal")
        self.mode_pill.setObjectName("subtitle")
        side_lay.addWidget(self.mode_pill)
        root_layout.addWidget(sidebar)

        # --- pages ---------------------------------------------------------------
        self.stack = QStackedWidget()
        self.dashboard = DashboardPage()
        self.modes_page = ModesPage(self.engine)
        self.fan_page = FanPage(self.fans)
        self.lighting_page = LightingPage(self.keyboard)
        self.graphics_page = GraphicsPage(self.apps)
        self.settings_page = SettingsPage()
        for page in (self.dashboard, self.modes_page, self.fan_page,
                     self.lighting_page, self.graphics_page, self.settings_page):
            self.stack.addWidget(page)
        root_layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        status = QStatusBar()
        self.setStatusBar(status)
        self.status_label = QLabel("Starting…")
        status.addWidget(self.status_label)

        self._goto(0)
        self._wire()

        # --- background workers --------------------------------------------------
        self.poll_worker = HardwarePollWorker(cpu, ram, gpu, interval_s=2.0)
        self.poll_worker.sample_ready.connect(self._on_sample)
        self.poll_worker.error.connect(lambda e: self.status_label.setText(f"telemetry error: {e}"))
        self.poll_worker.start()
        self._mode_worker: Optional[ModeApplyWorker] = None

        self._tray: Optional[QSystemTrayIcon] = None
        self._setup_tray()

    # --- wiring -----------------------------------------------------------------

    def _wire(self) -> None:
        self.modes_page.mode_selected.connect(self._request_mode)
        self.fan_page.profile_apply.connect(self._apply_fan_profile)
        self.fan_page.curve_toggled.connect(self._toggle_curve)
        self.settings_page.relaunch_admin_requested.connect(self._relaunch_admin)
        self.settings_page.restore_baseline_requested.connect(
            lambda: self._request_mode("normal"))

    def _goto(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)

    # --- telemetry ----------------------------------------------------------------

    def _on_sample(self, sample: dict) -> None:
        """Route a telemetry sample to the dashboard (UI thread)."""
        self.dashboard.update_sample(sample)
        self.status_label.setText("Telemetry live · 2 s refresh")

    # --- mode application -----------------------------------------------------------

    def _request_mode(self, mode_key: str) -> None:
        """Ask for confirmation, then apply the mode in a worker thread."""
        if self.settings_page.confirm_modes.isChecked():
            spec = ModeEngine.specs().get(mode_key)
            title = spec.title if spec else mode_key
            answer = QMessageBox.question(
                self, "Apply mode", f"Apply {title}?\n\n"
                "Normal Mode restores the exact state captured on first launch.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.modes_page.set_applying(True)
        self._mode_worker = ModeApplyWorker(self.engine, mode_key)
        self._mode_worker.finished.connect(self._mode_done)
        self._mode_worker.failed.connect(self._mode_failed)
        self._mode_worker.start()

    def _mode_done(self, mode_key: str, results: list) -> None:
        """Handle a finished mode apply (also refreshes side pill + dashboard)."""
        self.modes_page.set_applying(False)
        self.modes_page.show_results(mode_key, results)
        spec = ModeEngine.specs().get(mode_key)
        title = spec.title if spec else mode_key
        self.mode_pill.setText(f"Mode: {title}")
        self.dashboard.set_active_mode(title)
        self.apps.apply_mode(mode_key)
        self.status_label.setText(f"{title} applied")

    def _mode_failed(self, mode_key: str, message: str) -> None:
        """Handle a failed mode apply."""
        self.modes_page.set_applying(False)
        self.modes_page.show_error(mode_key, message)

    # --- fans -------------------------------------------------------------------------

    def _apply_fan_profile(self, profile: str, cpu_duty: int, gpu_duty: int) -> None:
        """Apply a fan profile requested by the fan page."""
        if profile == PROFILE_CURVE:
            self._toggle_curve(True)
            self.fan_page.set_status("Curve engine running")
            return
        ok = self.fans.set_profile(profile, cpu_duty, gpu_duty)
        name = {PROFILE_AUTO: "Auto", PROFILE_MAX: "Max", PROFILE_CUSTOM: "Custom"}.get(profile, profile)
        self.fan_page.set_status(f"{name}: {'applied' if ok else 'FAILED (admin rights?)'}")
        self.fan_page.refresh_state()

    def _toggle_curve(self, start: bool) -> None:
        """Start/stop the userspace fan curve engine."""
        if start:
            self.fans.curve.points = self.fans.curve.normalized()
            self.fans.start_curve(self._cpu_temp_probe, interval_s=self.fan_page.interval.value())
            self.fan_page.set_status("Curve engine running")
        else:
            self.fans.stop_curve()
            self.fan_page.set_status("Curve stopped (fans back to Auto)")

    def _cpu_temp_probe(self) -> Optional[float]:
        """Temperature source for the fan curve (Acer firmware sensor preferred)."""
        if self.engine.acer is not None:
            try:
                t = self.engine.acer.read_sensors().cpu_temp_c
                if t is not None:
                    return t
            except Exception:
                pass
        return None

    # --- system ----------------------------------------------------------------------

    def _relaunch_admin(self) -> None:
        """Relaunch the app elevated and quit this instance."""
        if relaunch_as_admin():
            self.close()
        else:
            QMessageBox.warning(self, APP_NAME, "Elevation was cancelled or failed.")

    def _setup_tray(self) -> None:
        """System tray icon with restore/quit actions (optional)."""
        try:
            from PyQt6.QtWidgets import QMenu
            self._tray = QSystemTrayIcon(self.windowIcon(), self)
            self._tray.setToolTip(APP_NAME)
            menu = QMenu()
            show_action = QAction("Open dashboard", menu)
            show_action.triggered.connect(self.showNormal)
            quit_action = QAction("Quit", menu)
            quit_action.triggered.connect(self.close)
            menu.addAction(show_action)
            menu.addSeparator()
            menu.addAction(quit_action)
            self._tray.setContextMenu(menu)
            self._tray.activated.connect(
                lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self._tray.show()
        except Exception as exc:
            log.debug("tray unavailable: %s", exc)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt naming)
        """Stop workers cleanly and hand fans back to firmware on exit."""
        try:
            self.poll_worker.stop()
            self.poll_worker.wait(3000)
        except Exception:
            pass
        try:
            self.fans.stop_curve()
        except Exception:
            pass
        try:
            self.lighting_page.shutdown()
        except Exception:
            pass
        event.accept()
