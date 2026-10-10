"""QThread workers: all hardware polling and mode application runs off the UI thread."""
from __future__ import annotations

import time
import traceback
from typing import Optional

from nitromaster.utils.logging_setup import get_logger

log = get_logger("workers")

try:
    from PyQt6.QtCore import QThread, pyqtSignal
    PYQT_AVAILABLE = True
except Exception:  # headless/Linux test environments
    PYQT_AVAILABLE = False

    class QThread:  # type: ignore[no-redef]
        """Minimal stub so module import succeeds without PyQt (tests/CI)."""
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def quit(self):
            pass

        def wait(self, *a):
            return True

        def isRunning(self):
            return False

    def pyqtSignal(*a, **k):  # type: ignore[no-redef]
        return None


class HardwarePollWorker(QThread):
    """Polls CPU/RAM/GPU telemetry at a fixed interval and emits one combined sample."""

    sample_ready = pyqtSignal(dict) if PYQT_AVAILABLE else None
    error = pyqtSignal(str) if PYQT_AVAILABLE else None

    def __init__(self, cpu_monitor, ram_monitor, gpu_monitor,
                 interval_s: float = 2.0, parent=None) -> None:
        super().__init__(parent)
        self.cpu = cpu_monitor
        self.ram = ram_monitor
        self.gpu = gpu_monitor
        self.interval_s = max(0.5, float(interval_s))
        self._running = True

    def run(self) -> None:
        """Polling loop; emits sample dicts until stopped."""
        while self._running:
            try:
                sample = {
                    "ts": time.time(),
                    "cpu": self.cpu.sample(),
                    "ram": self.ram.sample(),
                    "gpu": self.gpu.sample(),
                }
                if PYQT_AVAILABLE and self.sample_ready is not None:
                    self.sample_ready.emit(sample)
            except Exception as exc:
                log.error("hardware poll failed: %s\n%s", exc, traceback.format_exc())
                if PYQT_AVAILABLE and self.error is not None:
                    self.error.emit(str(exc))
            time.sleep(self.interval_s)

    def stop(self) -> None:
        """Ask the loop to exit (thread-safe)."""
        self._running = False


class ModeApplyWorker(QThread):
    """Applies a system mode off the UI thread and reports per-step results."""

    finished = pyqtSignal(str, list) if PYQT_AVAILABLE else None
    failed = pyqtSignal(str, str) if PYQT_AVAILABLE else None

    def __init__(self, mode_engine, mode_key: str, parent=None) -> None:
        super().__init__(parent)
        self.engine = mode_engine
        self.mode_key = mode_key

    def run(self) -> None:
        """Run ModeEngine.apply() and emit the report."""
        try:
            results = self.engine.apply(self.mode_key)
            if PYQT_AVAILABLE and self.finished is not None:
                self.finished.emit(self.mode_key, results)
        except Exception as exc:
            log.error("mode apply failed: %s\n%s", exc, traceback.format_exc())
            if PYQT_AVAILABLE and self.failed is not None:
                self.failed.emit(self.mode_key, str(exc))
