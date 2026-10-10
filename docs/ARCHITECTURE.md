# Architecture — NitroMaster Pro

Waterfall design for the Acer Nitro AN515-45. Layering is strict: `ui` → `core` → drivers.

```
nitromaster/
├── main.py                  entry point (elevation notice, run_gui)
├── app.py                   HardwareContext (backend assembly) + Qt bootstrap
├── core/
│   ├── workers.py           QThread: HardwarePollWorker, ModeApplyWorker
│   ├── monitoring/          telemetry
│   │   ├── sensors_backend.py   Acer firmware protocol codecs + AcerWmiBackend + LhmBridge
│   │   ├── cpu_monitor.py       psutil usage + PDH effective clocks + temp fallback chain
│   │   ├── ram_monitor.py       psutil memory
│   │   ├── nvidia_backend.py    pynvml → nvidia-smi fallback (unit conversion)
│   │   ├── amd_backend.py       LHM GpuAmd + WMI static
│   │   └── gpu_monitor.py       combined GpuSample
│   ├── power/               control
│   │   ├── powercfg.py        typed powercfg wrapper + locale-tolerant parsers
│   │   ├── baseline.py        first-run snapshot / Normal Mode restore + brightness
│   │   ├── power_modes.py     ModeSpec registry + ModeEngine
│   │   ├── process_manager.py EcoQoS/suspend + service snapshot-restore
│   │   └── focus_mode.py      single-app focus (Ultra Battery Saver)
│   ├── cooling/
│   │   ├── fan_controller.py  Auto/Max/Custom + userspace FanCurve engine
│   │   └── keyboard_backlight.py  4-zone RGB with enable sequence + persistence
│   └── graphics/
│       ├── gpu_switcher.py    UserGpuPreferences registry (0/1/2)
│       └── app_profiles.py    persisted per-app GPU assignments
├── ui/                      PyQt6 OLED theme + widgets + 5 pages + main window
└── utils/                   platform guards, admin/elevation, StateStore, logging
```

## Threading model

- **UI thread**: Qt widgets only. Never calls WMI/NVML/powercfg.
- **HardwarePollWorker** (QThread): 2 s telemetry loop → `sample_ready` signal.
- **ModeApplyWorker** (QThread): mode application → `finished(mode, results)` signal.
- **Fan curve loop** (daemon thread): temp probe → firmware duty write, re-asserting
  CUSTOM first (firmware resets custom duty on profile changes).

## Degradation contract

Every external dependency (WMI firmware, NVML, LHM, powercfg, Afterburner, registry)
is optional at runtime. Missing pieces are surfaced in the UI as disabled controls /
status text — never a crash. Non-Windows hosts run the pure-logic layers and tests.

## Safety invariants

1. Baseline captured on first load; Normal Mode restores it exactly.
2. Firmware writes are read back and verified (silent-success hazard).
3. Service changes are stop-only + snapshot/restore; start types untouched.
4. Process suspension is limited to non-critical processes; EcoQoS is the default lever.
5. OC is opt-in (Afterburner profile), reversible, and never touches voltage/TGP.
