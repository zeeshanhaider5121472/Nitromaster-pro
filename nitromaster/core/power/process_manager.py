"""Background process throttling/suspension and service snapshot/stop/restore.

Ultra Battery Saver lever stack (safe -> aggressive):
EcoQoS + IGNORE_TIMER_RESOLUTION + IDLE_PRIORITY_CLASS + affinity, then optional
``NtSuspendProcess`` only for explicitly selected user apps. Services are always
snapshotted before any change and restored afterwards.
"""
from __future__ import annotations

import ctypes
import subprocess
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

import psutil

from nitromaster.utils.logging_setup import get_logger
from nitromaster.utils.platform import IS_WINDOWS

log = get_logger("process_manager")

PROCESS_SET_INFORMATION = 0x0200
PROCESS_SUSPEND_RESUME = 0x0800
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4

# Non-essential services commonly stopped for battery saving (opt-in only!).
BATTERY_SAVER_SERVICES = [
    "SysMain", "DiagTrack", "WSearch", "MapsBroker", "lfsvc",
    "WerSvc", "wisvc", "RetailDemo", "TabletInputService", "Fax",
]

# Never touch these host processes when suspending (SCM watchdog / lock holders).
SUSPEND_EXCLUDE = {
    "svchost.exe", "csrss.exe", "smss.exe", "wininit.exe", "services.exe",
    "lsass.exe", "System", "Registry", "dwm.exe", "explorer.exe",
    "NitroMasterPro.exe", "python.exe", "pythonw.exe",
}


class _PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    """Win32 PROCESS_POWER_THROTTLING_STATE (ProcessPowerThrottling)."""
    _fields_ = [
        ("Version", ctypes.c_ulong),
        ("ControlMask", ctypes.c_ulong),
        ("StateMask", ctypes.c_ulong),
    ]


def enable_debug_privilege() -> bool:
    """Enable SeDebugPrivilege on the current process token (needs elevation)."""
    if not IS_WINDOWS:
        return False
    try:
        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32
        TOKEN_ADJUST_PRIVILEGES = 0x20
        TOKEN_QUERY = 0x8
        SE_PRIVILEGE_ENABLED = 0x2

        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long)]

        class LUID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Luid", LUID), ("Attributes", ctypes.c_ulong)]

        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", ctypes.c_ulong),
                        ("Privileges", LUID_AND_ATTRIBUTES * 1)]

        h = ctypes.c_void_p()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(h)):
            return False
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
            return False
        tp = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED),))
        ok = bool(advapi32.AdjustTokenPrivileges(h, False, ctypes.byref(tp), 0, None, None))
        return ok
    except Exception as exc:
        log.debug("enable_debug_privilege failed: %s", exc)
        return False


class ProcessPolicy:
    """Applies reversible power policy changes to processes (no kills, no permanent state)."""

    def __init__(self) -> None:
        self._applied: dict[int, dict] = {}   # pid -> previous state
        self._suspended: set[int] = set()

    # --- EcoQoS (Task Manager "Efficiency mode" equivalent) -------------------------

    def set_ecoqos(self, pid: int, enabled: bool) -> bool:
        """Enable/disable EcoQoS + ignore-timer-resolution for one process."""
        if not IS_WINDOWS:
            return False
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            state = _PROCESS_POWER_THROTTLING_STATE(
                PROCESS_POWER_THROTTLING_CURRENT_VERSION,
                PROCESS_POWER_THROTTLING_EXECUTION_SPEED | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION,
                (PROCESS_POWER_THROTTLING_EXECUTION_SPEED | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION) if enabled else 0,
            )
            ProcessPowerThrottling = 3  # PROCESS_INFORMATION_CLASS value (Win10 1709+)
            ok = bool(kernel32.SetProcessInformation(
                handle, ProcessPowerThrottling, ctypes.byref(state), ctypes.sizeof(state)
            ))
            return ok
        except Exception as exc:
            log.debug("set_ecoqos(%d) failed: %s", pid, exc)
            return False
        finally:
            kernel32.CloseHandle(handle)

    # --- Priority / affinity (psutil) ----------------------------------------------

    def throttle(self, pid: int) -> bool:
        """Set IDLE priority + EcoQoS for one pid; remembers prior state for :meth:`restore`."""
        try:
            p = psutil.Process(pid)
            if pid not in self._applied:
                self._applied[pid] = {"nice": p.nice()}
            p.nice(psutil.IDLE_PRIORITY_CLASS)
            self.set_ecoqos(pid, True)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            log.debug("throttle(%d): %s", pid, exc)
            return False

    def restore(self, pid: int) -> bool:
        """Restore one process to its pre-throttle priority and disable EcoQoS."""
        try:
            p = psutil.Process(pid)
            prev = self._applied.pop(pid, {})
            p.nice(prev.get("nice", psutil.NORMAL_PRIORITY_CLASS))
            self.set_ecoqos(pid, False)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def restore_all(self) -> int:
        """Restore every throttled process; returns count restored."""
        n = 0
        for pid in list(self._applied):
            if self.restore(pid):
                n += 1
        self.resume_all()
        return n

    # --- Suspend / resume (user-picked allowlist only) -----------------------------

    def suspend(self, pid: int) -> bool:
        """Suspend one process via psutil (NtSuspendProcess). Never for critical hosts."""
        try:
            p = psutil.Process(pid)
            if p.name().lower() in SUSPEND_EXCLUDE:
                log.warning("refusing to suspend %s (pid %d)", p.name(), pid)
                return False
            p.suspend()
            self._suspended.add(pid)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            log.debug("suspend(%d): %s", pid, exc)
            return False

    def resume(self, pid: int) -> bool:
        """Resume one suspended process."""
        try:
            psutil.Process(pid).resume()
            self._suspended.discard(pid)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def resume_all(self) -> int:
        """Resume every process suspended by this instance."""
        n = 0
        for pid in list(self._suspended):
            if self.resume(pid):
                n += 1
        return n

    def throttle_all_except(self, keep_pids: Iterable[int], min_age_s: float = 30.0) -> int:
        """Throttle every non-critical process except *keep_pids* (used by Ultra Battery Saver)."""
        keep = set(keep_pids)
        n = 0
        for p in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                info = p.info
                if info["pid"] in keep or (info["name"] or "").lower() in SUSPEND_EXCLUDE:
                    continue
                if info.get("create_time") and (time.time() - info["create_time"]) < min_age_s:
                    continue
                if self.throttle(info["pid"]):
                    n += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return n


@dataclass
class ServiceSnapshot:
    """Original state of one Windows service (for exact restore)."""
    name: str
    start_type: Optional[int] = None   # win32service SERVICE_*_START constant
    was_running: bool = False


@dataclass
class ServiceManager:
    """Snapshot/stop/restore Windows services via the SCM (pywin32). Stop-only is the default."""
    snapshots: list[ServiceSnapshot] = field(default_factory=list)

    def snapshot(self, names: Iterable[str]) -> list[ServiceSnapshot]:
        """Record start type + running state for the given services."""
        self.snapshots = []
        if not IS_WINDOWS:
            return self.snapshots
        try:
            import win32service  # Windows-only
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            try:
                for name in names:
                    try:
                        hs = win32service.OpenService(scm, name, win32service.SERVICE_QUERY_CONFIG | win32service.SERVICE_QUERY_STATUS)
                    except Exception:
                        continue
                    try:
                        cfg = win32service.QueryServiceConfig(hs)
                        start_type = cfg[1]  # (type, startType, errorControl, ...)
                        status = win32service.QueryServiceStatus(hs)
                        was_running = status[1] == win32service.SERVICE_RUNNING
                        self.snapshots.append(ServiceSnapshot(name, start_type, was_running))
                    finally:
                        win32service.CloseServiceHandle(hs)
            finally:
                win32service.CloseServiceHandle(scm)
        except Exception as exc:
            log.warning("service snapshot failed: %s", exc)
        return self.snapshots

    def stop(self, names: Iterable[str]) -> list[str]:
        """Stop services (start type untouched — fully reversible). Returns failures."""
        failures: list[str] = []
        if not IS_WINDOWS:
            return list(names)
        for name in names:
            r = subprocess.run(["sc", "stop", name], capture_output=True, text=True, timeout=30,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode != 0:
                failures.append(name)
        return failures

    def restore(self) -> list[str]:
        """Restart services that were running at snapshot time; returns failures."""
        failures: list[str] = []
        if not IS_WINDOWS:
            return failures
        for snap in self.snapshots:
            if snap.was_running:
                r = subprocess.run(["sc", "start", snap.name], capture_output=True, text=True, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode != 0:
                    failures.append(snap.name)
        self.snapshots = []
        return failures
