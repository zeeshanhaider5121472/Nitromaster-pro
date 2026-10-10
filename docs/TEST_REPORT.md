# Test Report — NitroMaster Pro v1.1.0

Date: 2026-10-10 · Host: Linux dev container (Python 3.12.3) · Target: Windows 11 x64

## Results

| Check | Result |
|---|---|
| `python -m compileall nitromaster tests` (47 Python files) | ✅ PASS — 0 errors |
| `python -m pytest` | ✅ PASS — 58/58 tests |
| Import smoke test (core, workers, utils) | ✅ PASS |
| CPU monitor live sample on dev host | ✅ PASS (psutil path) |

## Coverage by area

| Suite | Tests | Verifies |
|---|---|---|
| `test_protocol.py` | 17 | Fan behavior constants (`0x00410009`/`0x00820009`/`0x00C30009`), fan-speed selector/pct encoding, sysinfo status/reading decode, RGB u32 packing, 16-byte KB payload (byte-8=0 quirk, Wave flag=8), misc-setting status byte handling |
| `test_powercfg_parse.py` | 6 | Scheme list parsing (EN/ZH), active scheme, query parsing (EN/ZH + positional fallback) |
| `test_fan_curve.py` | 11 | Interpolation, end clamping, unsorted points, empty curve, value validation, dict roundtrip, default curve monotonicity, controller degradation without firmware |
| `test_modes.py` | 6 | All 5 modes registered; Normal = pure baseline restore; Ultra reversible + Eco profile + ≤30% brightness; Gaming = Max fan + Turbo profile + OC hook; invalid mode/spec rejection |
| `test_state_and_profiles.py` | 18 | StateStore atomic save/load/corruption tolerance, Baseline roundtrip, KeyboardState padding/validation, AppProfile CRUD + upsert + mode-aware registry application |

## Defects found by tests and fixed before release

1. **Fan bitmap vs selector conflation** (severity: high) — `FAN_GPU` was used as both the
   `SetGamingFanSpeed` selector (`0x04`) and the fan-behavior bitmap bit (actually `BIT(3)` =
   `0x08`). Firmware would have rejected/misrouted custom duty. Fixed with separate
   `FAN_BITMAP_*` constants; verified against `0x00410009`/`0x00820009`/`0x00C30009`.
2. **Scheme-name parsing** (medium) — `parse_scheme_list` split on every `)` and returned empty
   names. Fixed with a trailing-parenthesis regex.
3. **Fan profile validation order** (low) — unknown profile names returned `False` instead of
   raising `ValueError`. Validation now runs before the firmware check.
4. **Cross-platform path handling** (low) — `AppProfileStore.detect_name` used `pathlib` (POSIX
   semantics on Linux); switched to `ntpath` so Windows paths parse on every OS.

## Not testable on this host (requires Windows 11 + AN515-45 hardware)

- `AcerWmiBackend` live WMI calls (root\wmi:AcerGamingFunction) — covered by protocol codec tests.
- NVML/nvidia-smi sampling on Optimus power-down transitions.
- PDH `% Processor Performance` counters and EcoQoS `SetProcessInformation`.
- powercfg write path + baseline restore against real firmware.
- PyQt6 GUI rendering (compile-verified only; GitHub Actions builds the exe on windows-latest).

## Recommended on-target acceptance checklist

1. Launch elevated → baseline captured (check `%LOCALAPPDATA%\NitroMasterPro\baseline-scheme.pow`).
2. Fan page: Custom 30/30 → readback shows 30/30; Max → both fans spin up.
3. Keyboard: each zone a different color; reboot → app re-applies state at startup.
4. Modes: cycle all five → step report all-green; Normal restores baseline values.
5. Gaming mode with MSI Afterburner installed → profile 1 applies.
6. Ultra Battery Saver → focus app stays responsive, background apps throttled, services
   restored on Normal Mode / exit.
7. Graphics page: assign a game to GTX 1650 → Settings → Display → Graphics shows "High performance".
