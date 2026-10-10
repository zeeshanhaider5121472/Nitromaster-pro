"""Application assembly: backends, engine, UI and startup restore."""
from __future__ import annotations

import sys
from typing import Optional

from nitromaster.core.cooling.fan_controller import FanController
from nitromaster.core.cooling.keyboard_backlight import KeyboardBacklight
from nitromaster.core.graphics.app_profiles import AppProfileStore
from nitromaster.core.monitoring.cpu_monitor import CpuMonitor
from nitromaster.core.monitoring.gpu_monitor import GpuMonitor
from nitromaster.core.monitoring.ram_monitor import RamMonitor
from nitromaster.core.monitoring.sensors_backend import AcerWmiBackend, AcerWmiError, LhmBridge
from nitromaster.core.power.baseline import BaselineManager
from nitromaster.core.power.focus_mode import FocusMode
from nitromaster.core.power.power_modes import ModeEngine
from nitromaster.utils.logging_setup import get_logger, setup_logging
from nitromaster.utils.platform import IS_WINDOWS

log = get_logger("app")


class HardwareContext:
    """Owns all hardware backends/monitors and tears them down together."""

    def __init__(self) -> None:
        self.lhm = LhmBridge()
        self.acer: Optional[AcerWmiBackend] = None
        self.acer_error = ""
        if IS_WINDOWS:
            try:
                self.acer = AcerWmiBackend()
            except (AcerWmiError, RuntimeError) as exc:
                self.acer_error = str(exc)
                log.warning("Acer firmware interface unavailable: %s", exc)
        else:
            self.acer_error = "non-Windows host (dev/test mode)"
        self.cpu = CpuMonitor(self.acer, self.lhm)
        self.ram = RamMonitor()
        self.gpu = GpuMonitor(self.acer, self.lhm)
        self.fans = FanController(self.acer)
        self.keyboard = KeyboardBacklight(self.acer)
        self.apps = AppProfileStore()
        self.baselines = BaselineManager(acer=self.acer)
        self.focus = FocusMode()
        self.engine = ModeEngine(acer=self.acer, baselines=self.baselines, focus=self.focus)

    def startup_restore(self) -> None:
        """Capture the first-run baseline and re-apply volatile firmware state."""
        self.baselines.ensure_captured()
        try:
            self.keyboard.restore()
        except Exception as exc:
            log.warning("keyboard restore failed: %s", exc)

    def shutdown(self) -> None:
        """Release all hardware handles."""
        for closer in (self.cpu.close, self.gpu.close, self.lhm.close):
            try:
                closer()
            except Exception:
                pass
        try:
            self.fans.stop_curve()
        except Exception:
            pass
        try:
            self.focus.stop()
        except Exception:
            pass


def run_gui(argv: Optional[list[str]] = None) -> int:
    """Bootstrap the Qt application and run the main loop. Returns the exit code."""
    setup_logging()
    log.info("starting NitroMaster Pro")
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from nitromaster.ui.main_window import MainWindow
        from nitromaster.ui.theme import apply_theme
    except ImportError as exc:
        log.error("PyQt6 is required for the GUI: %s", exc)
        print("PyQt6 is required. Install dependencies with: pip install -r requirements.txt", file=sys.stderr)
        return 2

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("NitroMasterPro")
    apply_theme(app)

    ctx = HardwareContext()
    if ctx.acer_error:
        QMessageBox.information(
            None, "NitroMaster Pro",
            "Firmware control interface unavailable:\n"
            f"{ctx.acer_error}\n\nMonitoring features remain available; "
            "fan/profile/lighting controls will be disabled until it is present.")

    window = MainWindow(ctx.engine, ctx.cpu, ctx.ram, ctx.gpu, ctx.fans,
                        ctx.keyboard, ctx.apps, ctx.baselines)
    window.show()
    ctx.startup_restore()
    try:
        code = app.exec()
    finally:
        ctx.shutdown()
    return int(code)
