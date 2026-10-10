"""Per-application GPU profile database (persisted) and mode-aware application."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from nitromaster.core.graphics.gpu_switcher import (
    GPU_PREF_AUTO, GPU_PREF_DGPU, GPU_PREF_IGPU, GpuSwitcher,
)
from nitromaster.utils.logging_setup import get_logger
from nitromaster.utils.state_store import StateStore

log = get_logger("app_profiles")

PROFILES_KEY = "app_profiles"


@dataclass
class AppProfile:
    """One application's GPU assignment."""
    exe_path: str
    name: str = ""
    preferred_gpu: int = GPU_PREF_AUTO
    notes: str = ""

    def validate(self) -> None:
        """Raise ValueError on an invalid path or preference value."""
        if not self.exe_path.lower().endswith(".exe"):
            raise ValueError("exe_path must end with .exe")
        if self.preferred_gpu not in (GPU_PREF_AUTO, GPU_PREF_IGPU, GPU_PREF_DGPU):
            raise ValueError(f"invalid preferred_gpu {self.preferred_gpu}")

    def to_dict(self) -> dict:
        """JSON-friendly dict."""
        return {"exe_path": self.exe_path, "name": self.name,
                "preferred_gpu": self.preferred_gpu, "notes": self.notes}

    @classmethod
    def from_dict(cls, d: dict) -> "AppProfile":
        """Rebuild from :meth:`to_dict` output."""
        return cls(
            exe_path=str(d.get("exe_path", "")),
            name=str(d.get("name", "")),
            preferred_gpu=int(d.get("preferred_gpu", GPU_PREF_AUTO)),
            notes=str(d.get("notes", "")),
        )


@dataclass
class AppProfileStore:
    """CRUD store for :class:`AppProfile`, backed by :class:`StateStore`."""
    store: StateStore = field(default_factory=StateStore)
    switcher: GpuSwitcher = field(default_factory=GpuSwitcher)

    def _load(self) -> list[AppProfile]:
        data = self.store.load(PROFILES_KEY, default=[])
        return [AppProfile.from_dict(d) for d in data]

    def _save(self, profiles: list[AppProfile]) -> bool:
        return self.store.save(PROFILES_KEY, [p.to_dict() for p in profiles])

    def list(self) -> list[AppProfile]:
        """All stored profiles."""
        return self._load()

    def add(self, profile: AppProfile) -> bool:
        """Add or update a profile (keyed by exe_path) and apply its registry preference."""
        profile.validate()
        profiles = [p for p in self._load() if p.exe_path.lower() != profile.exe_path.lower()]
        profiles.append(profile)
        ok = self._save(profiles)
        if ok and profile.preferred_gpu != GPU_PREF_AUTO:
            self.switcher.set_preference(profile.exe_path, profile.preferred_gpu)
        return ok

    def remove(self, exe_path: str) -> bool:
        """Remove a profile and clear its registry preference."""
        profiles = [p for p in self._load() if p.exe_path.lower() != exe_path.lower()]
        ok = self._save(profiles)
        self.switcher.clear_preference(exe_path)
        return ok

    def apply_all(self) -> int:
        """Re-apply every stored profile to the registry (e.g. after a mode switch)."""
        n = 0
        for p in self._load():
            if self.switcher.set_preference(p.exe_path, p.preferred_gpu):
                n += 1
        return n

    def apply_mode(self, mode_key: str) -> int:
        """Mode-aware application: gaming/performance force dGPU, ultra forces iGPU.

        Returns the number of entries written. AUTO-profiles are left untouched.
        """
        forced: Optional[int] = None
        if mode_key in ("gaming", "performance"):
            forced = GPU_PREF_DGPU
        elif mode_key == "ultra_battery_saver":
            forced = GPU_PREF_IGPU
        n = 0
        for p in self._load():
            pref = forced if (forced is not None and p.preferred_gpu != GPU_PREF_AUTO) else p.preferred_gpu
            if self.switcher.set_preference(p.exe_path, pref):
                n += 1
        return n

    @staticmethod
    def detect_name(exe_path: str) -> str:
        """Derive a friendly display name from an exe path (handles Windows paths on any OS)."""
        import ntpath
        stem = ntpath.splitext(ntpath.basename(exe_path))[0]
        return stem.replace("_", " ").replace("-", " ").strip() or exe_path
