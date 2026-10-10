"""Administrator (elevation) detection and self-elevation relaunch."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys

from .platform import IS_WINDOWS


def is_admin() -> bool:
    """Return True when the current process token is elevated (Windows) or euid==0 (Linux)."""
    if IS_WINDOWS:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        return False


def relaunch_as_admin(argv: list[str] | None = None) -> bool:
    """Relaunch the current script elevated via ShellExecuteW 'runas'. Returns True if launch was requested."""
    if not IS_WINDOWS:
        return False
    args = argv if argv is not None else sys.argv
    script = os.path.abspath(args[0])
    params = " ".join(f'"{a}"' for a in args[1:])
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params}'.strip(), None, 1
        )
        return int(rc) > 32
    except Exception:
        return False


def run_elevated(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a console command hidden and capture output; use only for commands that self-elevate via UAC prompt."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
    )
