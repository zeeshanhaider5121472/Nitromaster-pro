"""Typed wrapper around ``powercfg`` with locale-tolerant output parsing.

Verified GUIDs come from the SDK ``winnt.h`` constants (see docs/research/04).
``SCHEME_MAX`` = Power saver and ``SCHEME_MIN`` = High performance — always use GUIDs.
"""
from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass
from typing import Optional

from nitromaster.utils.logging_setup import get_logger
from nitromaster.utils.platform import IS_WINDOWS

log = get_logger("powercfg")

# --- Verified GUIDs -----------------------------------------------------------------

SCHEME_POWER_SAVER = "a1841308-3541-4fab-bc81-f71556f20b4a"
SCHEME_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
SCHEME_HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
SCHEME_ULTIMATE_PERFORMANCE = "e9a42b02-d5df-448d-aa00-03f14749eb61"

SUB_PROCESSOR = "54533251-82be-4824-96c1-47b60b740d00"
SUB_VIDEO = "7516b95f-f776-4464-8c53-06167f40cc99"
SUB_SLEEP = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
SUB_PCIEXPRESS = "501a4d13-42af-4429-9fd1-a8218c268e20"
SUB_DISK = "0012ee47-9041-4b5d-9b77-535fba8b1442"
SUB_WIRELESS = "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1"

SET_PERFBOOSTMODE = "be337238-0d82-4146-a960-4f3749d470c7"   # 0 off, 1 enabled, 2 aggressive
SET_PERFBOOSTPOL = "45bcc044-d885-43e2-8605-ee0ec6e96b59"    # 0-100 %
SET_PROCTHROTTLEMAX = "bc5038f7-23e0-4960-96da-33abaf5935ec"  # 0-100 %
SET_PROCTHROTTLEMIN = "893dee8e-2bef-41e0-89c6-b55d0929964c"  # 0-100 %
SET_COOLING_POLICY = "94d3a615-a899-4ac5-ae2b-e4d8f634367f"   # 0 active, 1 passive
SET_VIDEO_POWERDOWN = "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"  # seconds
SET_VIDEO_BRIGHTNESS = "aded5e82-b909-4619-9949-f5d71dac0bcb"  # 0-100 %
SET_STANDBY_TIMEOUT = "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"  # seconds
SET_HIBERNATE_TIMEOUT = "9d7815a6-7ee4-497e-8888-515a05f02364"  # seconds
SET_HYBRID_SLEEP = "94ac6d29-73ce-41a6-809f-6363ba21b47e"     # 0/1
SET_ASPM = "ee12f906-d277-404b-b6da-e5fa1a576df5"            # 0 none, 1 moderate, 2 max

# --- Locale-tolerant parsing (pure) -------------------------------------------------

_GUID_RE = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")
_IDX_RE = re.compile(r"0x[0-9a-fA-F]+")
_SCHEME_NAME_RE = re.compile(r"\(([^()]*)\)\s*\*?\s*$")
_AC_KEYS = ("ac ", "交流", "ac:", "ac电源", "mains")
_DC_KEYS = ("dc ", "直流", "dc:", "dc电池", "battery")


@dataclass
class SchemeInfo:
    """One power scheme as listed by ``powercfg /list``."""
    guid: str
    name: str
    active: bool = False


@dataclass
class SettingValue:
    """AC/DC value indices of one power setting."""
    setting_guid: str
    ac: Optional[int] = None
    dc: Optional[int] = None
    alias: str = ""


def parse_scheme_list(text: str) -> list[SchemeInfo]:
    """Parse ``powercfg /list`` output in any locale -> scheme list."""
    out: list[SchemeInfo] = []
    for line in text.splitlines():
        m = _GUID_RE.search(line)
        if not m:
            continue
        guid = m.group(0).lower()
        active = "*" in line
        name_m = _SCHEME_NAME_RE.search(line)
        name = name_m.group(1).strip() if name_m else line.replace("*", "").strip()
        out.append(SchemeInfo(guid=guid, name=name, active=active))
    return out


def parse_active_scheme(text: str) -> Optional[str]:
    """Parse ``powercfg /getactivescheme`` output -> active scheme GUID (lowercase)."""
    m = _GUID_RE.search(text)
    return m.group(0).lower() if m else None


def parse_query(text: str) -> dict[str, SettingValue]:
    """Parse ``powercfg /query`` output -> {setting_guid: SettingValue}.

    Setting-header detection: locale keywords (English/Chinese) first, then the
    structural fallback (powercfg indents power-setting headers one level deeper
    than subgroup headers). AC/DC detection likewise falls back to positional
    order (powercfg always prints the AC index line before the DC line).
    """
    out: dict[str, SettingValue] = {}
    current: Optional[SettingValue] = None
    for raw in text.splitlines():
        line = raw.strip()
        g = _GUID_RE.search(line)
        low = line.lower()
        idx = _IDX_RE.search(line)
        indent = len(raw) - len(raw.lstrip())
        if g and not idx and ("setting" in low or "设置" in line or indent >= 4):
            current = SettingValue(setting_guid=g.group(0).lower())
            out[current.setting_guid] = current
            continue
        if current is None or not idx:
            continue
        value = int(idx.group(0), 16)
        is_ac = any(k in low for k in _AC_KEYS)
        is_dc = any(k in low for k in _DC_KEYS)
        if is_ac and not is_dc:
            current.ac = value
        elif is_dc and not is_ac:
            current.dc = value
        else:  # positional fallback: first index line = AC, second = DC
            if current.ac is None:
                current.ac = value
            elif current.dc is None:
                current.dc = value
    return out


class PowerCfg:
    """Runs ``powercfg`` and exposes typed operations. Writes require elevation."""

    def __init__(self, powercfg_exe: str = "powercfg") -> None:
        self.exe = powercfg_exe

    def _run(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
        cmd = [self.exe, *args]
        try:
            return subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("powercfg %s failed: %s", " ".join(args), exc)
            return subprocess.CompletedProcess(cmd, 1, "", str(exc))

    def get_active_scheme(self) -> Optional[str]:
        """Return the active scheme GUID, or None on failure."""
        r = self._run("/getactivescheme")
        return parse_active_scheme(r.stdout) if r.returncode == 0 else None

    def list_schemes(self) -> list[SchemeInfo]:
        """Return all schemes; the active one is marked."""
        r = self._run("/list")
        return parse_scheme_list(r.stdout) if r.returncode == 0 else []

    def set_active(self, scheme_guid: str) -> bool:
        """Activate a scheme."""
        return self._run("/setactive", scheme_guid).returncode == 0

    def set_values(self, scheme_guid: str, sub_guid: str, setting_guid: str,
                   ac_index: Optional[int], dc_index: Optional[int]) -> bool:
        """Set AC and/or DC value indices for one setting. Returns True when both writes succeeded."""
        ok = True
        if ac_index is not None:
            ok &= self._run("/setacvalueindex", scheme_guid, sub_guid, setting_guid, str(ac_index)).returncode == 0
        if dc_index is not None:
            ok &= self._run("/setdcvalueindex", scheme_guid, sub_guid, setting_guid, str(dc_index)).returncode == 0
        return ok

    def query(self, scheme_guid: Optional[str] = None,
              sub_guid: Optional[str] = None) -> dict[str, SettingValue]:
        """Query (hidden included is not possible here) settings of a scheme/subgroup."""
        args = ["/query"]
        if scheme_guid:
            args.append(scheme_guid)
        if sub_guid:
            args.append(sub_guid)
        r = self._run(*args)
        return parse_query(r.stdout) if r.returncode == 0 else {}

    def export_scheme(self, scheme_guid: str, path: str) -> bool:
        """Export a scheme to a .pow file (binary baseline snapshot)."""
        return self._run("/export", path, scheme_guid).returncode == 0

    def import_scheme(self, path: str, scheme_guid: Optional[str] = None) -> bool:
        """Import a .pow file, optionally pinned to a fixed GUID."""
        args = ["/import", path]
        if scheme_guid:
            args.append(scheme_guid)
        return self._run(*args).returncode == 0

    def duplicate_scheme(self, source_guid: str, dest_guid: Optional[str] = None) -> Optional[str]:
        """Duplicate a scheme; returns the new scheme GUID (dest_guid may be supplied for idempotency)."""
        dest = dest_guid or str(uuid.uuid4())
        r = self._run("/duplicatescheme", source_guid, dest)
        if r.returncode != 0:
            return None
        found = parse_active_scheme(r.stdout)  # duplicatescheme prints the resulting GUID
        return found or dest.lower()

    def delete_scheme(self, scheme_guid: str) -> bool:
        """Delete a custom scheme (built-ins refuse; caller should not care)."""
        return self._run("/delete", scheme_guid).returncode == 0

    def rename_scheme(self, scheme_guid: str, name: str) -> bool:
        """Rename a scheme."""
        return self._run("/changename", scheme_guid, name).returncode == 0
