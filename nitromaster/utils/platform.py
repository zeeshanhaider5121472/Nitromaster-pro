"""Platform detection helpers. All Windows-only code is import-guarded through this module."""
from __future__ import annotations

import sys

IS_WINDOWS: bool = sys.platform == "win32"
IS_LINUX: bool = sys.platform.startswith("linux")


def require_windows(feature: str) -> None:
    """Raise RuntimeError with a clear message when a Windows-only feature is used elsewhere."""
    if not IS_WINDOWS:
        raise RuntimeError(f"{feature} is only available on Windows")
