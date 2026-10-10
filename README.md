# NitroMaster Pro Control Center

Production-ready Windows 11 x64 desktop application, tailor-made for the
**Acer Nitro AN515-45** (AMD Ryzen 5 5600H + NVIDIA GTX 1650 + Radeon Vega iGPU, 16 GB RAM).

Pitch-black OLED UI (`#000000`) with neon accents, inspired by Xiaomi's Ultra Battery Saver.

## Features

| Area | What it does |
|---|---|
| **Hardware Dashboard** | Live CPU temp/usage/effective clock, GPU temp/usage/VRAM/power, RAM, fan RPM — all in background `QThread` workers |
| **Core Power Modes** | Normal (exact first-run baseline restore) · Battery Saver · Ultra Battery Saver (single-app focus + background freeze) · Performance · Gaming/Jailbreak (fan Max + Turbo profile + Afterburner OC profile) |
| **NitroSense features** | Auto / Max / Custom fan duty + userspace fan-curve engine; 4-zone RGB keyboard with effects (verified enable sequence for AN515-45) |
| **Ambient screen sync** | Keyboard zones dynamically mirror the dominant colors of the 4 screen strips (dark/gray pixels ignored, smoothed fade transitions) |
| **Graphics switcher** | Per-app GPU preference (GTX 1650 vs Radeon Vega) via `HKCU\...\DirectX\UserGpuPreferences` |
| **Safety** | First-run baseline snapshot (power plan + fan + profile + keyboard + brightness), readback verification of firmware writes, opt-in service stop with exact restore, admin detection + relaunch |

## Build (Windows x64)

> The `.exe` must be built **on Windows** (PyInstaller cannot emit a Windows PE from
> Linux). Two one-click options:
>
> **A) Locally** — on any Windows 11 machine with Python 3.11+ x64:
> ```bat
> build.bat
> ```
> → `dist\NitroMasterPro.exe` (single file, windowed). Optional installer:
> `iscc installer\nitromaster.iss` → `installer\Output\NitroMasterPro-Setup-1.0.0.exe`.
>
> **B) Cloud (no local Python)** — push the project to a GitHub repo; the included
> workflow `.github/workflows/build.yml` tests on Ubuntu and builds the exe on
> `windows-latest`. Download it from the Actions run artifact **NitroMasterPro-exe**.

Requirements: Python 3.11+ x64, `pip install -r requirements.txt`.

## Run

```
python -m nitromaster.main
```

Run **as Administrator** for fan control, thermal profiles and power-plan writes.
Monitoring and per-app GPU preferences work without elevation.

## Tests

```
python -m pytest
```

Pure-logic test suite (protocol codecs, powercfg parsers, fan curves, state stores,
mode registry) runs on any OS; Windows-only drivers are import-guarded.

## Hardware notes (why it's built this way)

- All firmware control goes through `root\wmi:AcerGamingFunction` — no kernel drivers,
  no EC port I/O. Requires elevation.
- Firmware silently accepts ignored writes (RGB to a dark panel etc.) → the app
  re-runs the keyboard enable sequence before every write and reads state back.
- Fan duty/keyboard colors are volatile across power cycles → state is persisted in
  `%LOCALAPPDATA%\NitroMasterPro` and re-applied at startup.
- No MUX switch: dGPU renders via Optimus copy-forward to the internal panel.
- Mobile GTX 1650: voltage/TGP locked; OC = core/memory offsets via MSI Afterburner
  profile 1 (opt-in, reversible).

See `docs/ARCHITECTURE.md` and `docs/CONTRACTS.md` for structure and module APIs,
`docs/research/` for the full hardware research.
"# Nitromaster-pro" 
