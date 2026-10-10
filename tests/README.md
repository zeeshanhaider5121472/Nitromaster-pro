# tests/

Pure-logic unit tests, runnable on any OS (Linux CI included). Windows-only drivers
are import-guarded, so the suite never needs WMI/NVML/pywin32.

| File | Coverage |
|---|---|
| `test_protocol.py` | Acer firmware codecs: fan behavior/speed, sysinfo, RGB payload, 16-byte KB backlight (byte-8 quirk), misc settings |
| `test_powercfg_parse.py` | Locale-tolerant `powercfg` parsers (English, Chinese, positional fallback) |
| `test_fan_curve.py` | Curve interpolation/clamping/validation/roundtrip; controller degradation |
| `test_modes.py` | Mode registry invariants (5 modes, reversible ultra, gaming fan/profile) |
| `test_state_and_profiles.py` | StateStore atomicity, Baseline/KeyboardState roundtrips, AppProfile CRUD + mode-aware apply |

Run: `python -m pytest` from the repo root (see `pytest.ini`).
