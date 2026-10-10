# Review — NitroMaster Pro v1.0.0

Design/code review against the TEAM.md engineering rules and the research docs.

## Rule compliance

| Rule | Status | Notes |
|---|---|---|
| No placeholders / stubs | ✅ | All functions implemented; the two `QThread` stubs in `core/workers.py` exist only for headless import and are clearly documented |
| `py_compile` survival | ✅ | 47/47 files |
| External calls wrapped | ✅ | WMI/NVML/PDH/powercfg/registry/ctypes all guarded with typed degradation |
| Hardware polling off UI thread | ✅ | `HardwarePollWorker` + `ModeApplyWorker` QThreads; fan curve in daemon thread |
| Admin-awareness | ✅ | `utils/admin.py` + Settings page pill + relaunch action |
| Linux dev-container safe | ✅ | `utils/platform.py` guards; pure logic unit-tested |
| OLED theme constants | ✅ | `ui/theme.py`: #000000 bg, #0A0A0A cards, #1E1E1E borders, cyan/green/magenta accents |
| Research fidelity | ✅ | WMI constants, enable sequence `8|(15<<40)`, payload byte-8=0, profile ids, GUIDs, safety caps all taken from docs/research |

## Known risks / deliberate limitations

1. **WMI input parameter name discovery** — `AcerWmiBackend._call` sets the first input
   parameter of the method signature instead of hard-coding "gmInput" (unverified name).
   If firmware signatures ever expose multiple inputs, the first one is used; output
   extraction tolerates `gmOutput`/`gmReturn` name variants.
2. **MSI Afterburner is the only OC path** — mobile VBIOS locks voltage/TGP; NVAPI
   `SetPstates20` intentionally not shipped (fragile across driver versions). Gaming mode
   reports "install Afterburner" instead of failing silently.
3. **Service stop list is heuristic** — `BATTERY_SAVER_SERVICES` targets well-known
   non-essential services; per-user service instances (CDPUserSvc_*) are not touched
   (they need registry-level handling; out of scope per research §2.5).
4. **N-key (NitroSense key) hook not shipped** — the AN515-45 Windows scancode is
   UNVERIFIED per research §4.1; runtime detection would be needed. Left out rather than
   hard-coding a wrong constant.
5. **`% Parking Status` counter unverified** — not used; effective clock uses
   `% Processor Performance` only.
6. **Fan curve rewrites duty every interval** — matches the Linux reference daemons; a
   profile change by NitroSense may briefly fight the loop until the next re-assert.

## Integration notes

- `HardwareContext` (app.py) owns every backend and tears them down together; pages never
  touch WMI directly.
- `ModeEngine` listeners + `AppProfileStore.apply_mode` keep GPU preferences consistent
  with the active mode (gaming → dGPU forced, ultra → iGPU forced for explicit entries).
- Volatile firmware state (fan duty, keyboard colors) is re-applied at startup
  (`HardwareContext.startup_restore`) since the firmware resets to defaults on power cycle.
