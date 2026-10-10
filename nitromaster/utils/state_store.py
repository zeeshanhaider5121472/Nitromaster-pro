"""JSON state persistence under %LOCALAPPDATA%/NitroMasterPro (or XDG state dir on Linux)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .platform import IS_WINDOWS


def state_dir() -> Path:
    """Return (and create) the writable application state directory."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        p = Path(base) / "NitroMasterPro"
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        p = Path(base) / "nitromaster-pro"
    p.mkdir(parents=True, exist_ok=True)
    return p


class StateStore:
    """Small atomic JSON document store (one file per key)."""

    def __init__(self, subdir: str = "") -> None:
        self.root = state_dir() / subdir if subdir else state_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def load(self, key: str, default: Any = None) -> Any:
        """Load a JSON document; returns *default* when missing or corrupt."""
        p = self.path(key)
        try:
            with p.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return default

    def save(self, key: str, data: Any) -> bool:
        """Atomically write a JSON document. Returns True on success."""
        p = self.path(key)
        try:
            fd, tmp = tempfile.mkstemp(dir=str(self.root), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
            os.replace(tmp, p)
            return True
        except OSError:
            return False

    def delete(self, key: str) -> None:
        """Remove a stored document if present (never raises)."""
        try:
            self.path(key).unlink()
        except OSError:
            pass
