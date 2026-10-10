"""Windows 11 per-app GPU preference (Settings → Display → Graphics).

Registry: ``HKCU\\SOFTWARE\\Microsoft\\DirectX\\UserGpuPreferences``.
Value name = absolute exe path, value data = ``GpuPreference=N;``:
0 = let Windows decide, 1 = power-saving GPU (Radeon iGPU), 2 = high-performance (GTX 1650).

Note (AN515-45 limitation): the panel is wired through the iGPU (no MUX switch),
so "high performance" means render-on-dGPU + Optimus copy-forward.
Preferences are read at process launch — the target app must be restarted.
"""
from __future__ import annotations

import re
from typing import Optional

from nitromaster.utils.logging_setup import get_logger
from nitromaster.utils.platform import IS_WINDOWS

log = get_logger("gpu_switcher")

GPUPREF_KEY = r"SOFTWARE\Microsoft\DirectX\UserGpuPreferences"
GPU_PREF_AUTO = 0
GPU_PREF_IGPU = 1   # power-saving GPU = Radeon Vega iGPU
GPU_PREF_DGPU = 2   # high-performance GPU = GTX 1650
GPU_PREF_NAMES = {GPU_PREF_AUTO: "Let Windows decide", GPU_PREF_IGPU: "Power saving (iGPU)",
                  GPU_PREF_DGPU: "High performance (GTX 1650)"}

_PREF_RE = re.compile(r"GpuPreference\s*=\s*(\d+)\s*;?")


def format_gpu_pref(pref: int) -> str:
    """Format the registry data string for a preference value."""
    if pref not in GPU_PREF_NAMES:
        raise ValueError(f"invalid GpuPreference {pref}")
    return f"GpuPreference={pref};"


def parse_gpu_pref(data: Optional[str]) -> int:
    """Parse registry data -> preference int; defaults to GPU_PREF_AUTO when absent/garbage."""
    if not data:
        return GPU_PREF_AUTO
    m = _PREF_RE.search(data)
    if not m:
        return GPU_PREF_AUTO
    value = int(m.group(1))
    return value if value in GPU_PREF_NAMES else GPU_PREF_AUTO


class GpuSwitcher:
    """Reads/writes per-app GPU preference values under HKCU (no elevation needed)."""

    def __init__(self) -> None:
        self.available = IS_WINDOWS

    def _open(self, write: bool = False):
        import winreg  # Windows-only
        access = winreg.KEY_SET_VALUE if write else winreg.KEY_READ
        if write:
            return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, GPUPREF_KEY, 0, access)
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, GPUPREF_KEY, 0, access)

    def set_preference(self, exe_path: str, pref: int) -> bool:
        """Set the GPU preference for one executable path. Restarts of the app required."""
        if not self.available:
            return False
        if not exe_path.lower().endswith(".exe"):
            raise ValueError("exe_path must point at a .exe file")
        try:
            import winreg
            with self._open(write=True) as key:
                winreg.SetValueEx(key, exe_path, 0, winreg.REG_SZ, format_gpu_pref(pref))
            return True
        except OSError as exc:
            log.warning("set_preference failed: %s", exc)
            return False

    def get_preference(self, exe_path: str) -> int:
        """Return the preference for one executable (GPU_PREF_AUTO when unset)."""
        if not self.available:
            return GPU_PREF_AUTO
        try:
            import winreg
            with self._open() as key:
                data, _ = winreg.QueryValueEx(key, exe_path)
            return parse_gpu_pref(data)
        except OSError:
            return GPU_PREF_AUTO

    def clear_preference(self, exe_path: str) -> bool:
        """Remove the entry (back to 'Let Windows decide')."""
        if not self.available:
            return False
        try:
            import winreg
            with self._open(write=True) as key:
                winreg.DeleteValue(key, exe_path)
            return True
        except OSError:
            return False

    def list_preferences(self) -> dict[str, int]:
        """Enumerate all configured executables -> preference int."""
        out: dict[str, int] = {}
        if not self.available:
            return out
        try:
            import winreg
            with self._open() as key:
                i = 0
                while True:
                    try:
                        name, data, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    out[name] = parse_gpu_pref(data if isinstance(data, str) else "")
                    i += 1
        except OSError as exc:
            log.debug("list_preferences: %s", exc)
        return out

    def export_backup(self) -> dict[str, str]:
        """Raw registry backup of the whole key (for profile migration)."""
        out: dict[str, str] = {}
        if not self.available:
            return out
        try:
            import winreg
            with self._open() as key:
                i = 0
                while True:
                    try:
                        name, data, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    out[name] = data if isinstance(data, str) else ""
                    i += 1
        except OSError:
            pass
        return out

    def restore_backup(self, backup: dict[str, str]) -> int:
        """Restore a backup produced by :meth:`export_backup`; returns entries written."""
        if not self.available or not backup:
            return 0
        n = 0
        for exe, data in backup.items():
            try:
                import winreg
                with self._open(write=True) as key:
                    winreg.SetValueEx(key, exe, 0, winreg.REG_SZ, data)
                n += 1
            except OSError:
                continue
        return n
