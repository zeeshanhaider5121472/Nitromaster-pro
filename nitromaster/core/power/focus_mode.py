"""Single-app-focus state for Ultra Battery Saver (Xiaomi-style minimalism).

Everything is reversible: the manager remembers which processes it throttled or
suspended and restores them when focus mode ends.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import psutil

from nitromaster.core.power.process_manager import ProcessPolicy
from nitromaster.utils.logging_setup import get_logger

log = get_logger("focus_mode")


@dataclass
class FocusMode:
    """Throttles/suspends everything except the focused application."""
    policy: ProcessPolicy = field(default_factory=ProcessPolicy)
    suspend_background: bool = False   # opt-in: actually suspend (not just throttle)
    focused_pid: Optional[int] = None
    active: bool = False

    def start(self, focused_pid: Optional[int] = None) -> int:
        """Enter focus mode; returns the number of processes affected."""
        if focused_pid is None:
            focused_pid = self.foreground_pid()
        self.focused_pid = focused_pid
        self.active = True
        affected = self.policy.throttle_all_except(self._keep_set())
        if self.suspend_background:
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    pid = p.info["pid"]
                    if pid in self._keep_set():
                        continue
                    self.policy.suspend(pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        log.info("focus mode started: pid=%s affected=%d", self.focused_pid, affected)
        return affected

    def stop(self) -> int:
        """Leave focus mode; restores throttled and suspended processes."""
        self.active = False
        n = self.policy.restore_all()
        self.focused_pid = None
        log.info("focus mode stopped: restored=%d", n)
        return n

    def set_focus(self, pid: int) -> None:
        """Move focus to another application while focus mode is active."""
        if not self.active:
            self.focused_pid = pid
            return
        old = self.focused_pid
        self.focused_pid = pid
        if old is not None and old != pid:
            self.policy.throttle(old)   # previous focus becomes background again
        self.policy.restore(pid)        # new focus gets full power

    def _keep_set(self) -> set[int]:
        """PIDs that must never be throttled: focused app, this process, its parent."""
        keep = {psutil.Process().pid}
        try:
            keep.add(psutil.Process().ppid())
        except psutil.Error:
            pass
        if self.focused_pid:
            keep.add(self.focused_pid)
        return keep

    @staticmethod
    def foreground_pid() -> Optional[int]:
        """Return the foreground window's PID via user32 (None when unavailable)."""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return int(pid.value) or None
        except Exception as exc:
            log.debug("foreground_pid failed: %s", exc)
            return None
