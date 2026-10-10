# GPU Research — NVIDIA GTX 1650 (Optimus dGPU) + AMD Radeon Vega iGPU

**Target platform:** Acer Nitro AN515-45 (Ryzen 5 5600H "Cezanne" + Radeon Vega 7 iGPU + NVIDIA GeForce GTX 1650 laptop dGPU), Windows 11 x64.
**Scope:** dual-GPU telemetry, control, overclocking, power/clock limits, per-app GPU switching and "active render GPU" detection on Windows.

> Legend: **pip** = installable Python package · **ctypes** = hand-bound C API via `ctypes`/`clr` · **cli** = external executable · **UNVERIFIED** = could not confirm from a primary source in this pass.

---

## Executive Summary

- **NVIDIA telemetry** is best done with **`nvidia-ml-py` (pynvml, pip)**, which wraps NVML: temperature (°C), fan (%, not RPM), core/mem clock (MHz), VRAM (bytes), power (milliwatts), utilisation (%), PCIe gen/width, persistence mode, driver version. Every call can throw `NVMLError_GpuIsLost` / `NVMLError_NotSupported` on Optimus sleep-resume — wrap all of them and re-init.
- **`nvidia-smi`** is the reliable fallback (same data, `--query-gpu`, powers in **W**).
- **Overclocking** the mobile GTX 1650 cannot be done through NVML. The real paths are **NVAPI via ctypes (`NvAPI_GPU_SetPstates20`, fragile/undocumented)** or, far more robustly, **driving MSI Afterburner** (`-profile1..5`). Laptop VBIOS **locks voltage & power sliders**; only core/memory clock offsets are open.
- **`nvidia-smi -pl` (power limit) is NOT supported on laptop GeForce** — confirmed by NVIDIA forum threads. Mobile TGP is firmware-fixed.
- **AMD Vega iGPU has no NVML equivalent.** Use **LibreHardwareMonitor via pythonnet** (`HardwareType.GpuAmd`) as primary, **ADLX SDK** (C/C++, Python binding wrapper) as advanced, `Win32_VideoController` as static-only last resort.
- **iGPU clock/power on Cezanne is real via `RyzenAdj`** (`--min-gfxclk/--max-gfxclk`, `--stapm-limit/--fast-limit/--slow-limit`) — **not** `--gfx-clk`. Needs admin.
- **Per-app GPU choice** is the Windows **Graphics Performance Preference** registry: `HKCU\SOFTWARE\Microsoft\DirectX\UserGpuPreferences`, value = exe path, data `GpuPreference=0/1/2` (0 auto, 1 power-saving=iGPU, 2 high-perf=dGPU). Applies at next app launch.
- **The AN515-45 has NO MUX switch** — Optimus is always on and the laptop panel is wired through the Vega iGPU, so the dGPU can never directly drive the built-in display.

---

## A1. NVIDIA GTX 1650 — Telemetry via NVML / pynvml

### A1.1 Library & init

- Package: **`nvidia-ml-py`** on PyPI, imported as **`pynvml`** (pip). It loads `nvml.dll` (Windows) which ships with the driver under `C:\Windows\System32\nvml.dll` (legacy path `%ProgramW6432%\NVIDIA Corporation\NVSMI\`).
- NVML is officially **Windows x64** supported and is the same library `nvidia-smi` uses. Ref: NVML API Reference (Sources #1).

### A1.2 Exact pynvml calls and **units** (critical)

| Quantity | pynvml call | Unit returned | Notes |
|---|---|---|---|
| GPU temp (core) | `nvmlDeviceGetTemperature(h, NVML_TEMPERATURE_GPU)` | **°C** | `NVML_TEMPERATURE_GPU = 0` |
| Fan speed | `nvmlDeviceGetFanSpeed(h)` | **% (0–100)** | percent, **not RPM** |
| Fan speed (per-fan) | `nvmlDeviceGetFanSpeed_v2(h, fanIndex)` | **%** | multi-fan laptops |
| Fan RPM | *(no stable NVML call on GeForce)* | — | **UNVERIFIED / not exposed**; read via Afterburner/ADL if required |
| Core clock | `nvmlDeviceGetClockInfo(h, NVML_CLOCK_GRAPHICS)` | **MHz** | |
| SM clock | `nvmlDeviceGetClockInfo(h, NVML_CLOCK_SM)` | **MHz** | |
| Memory clock | `nvmlDeviceGetClockInfo(h, NVML_CLOCK_MEM)` | **MHz** | (effective/2 for GDDR6 double-rate) |
| Max clock | `nvmlDeviceGetMaxClockInfo(h, NVML_CLOCK_GRAPHICS)` | **MHz** | |
| VRAM | `nvmlDeviceGetMemoryInfo(h)` → `.total/.free/.used` | **bytes** | `nvmlMemory_t`; divide by 2^20 for MiB |
| Power draw | `nvmlDeviceGetPowerUsage(h)` | **milliwatts (mW)** | divide by 1000 → W |
| Enforced power limit | `nvmlDeviceGetEnforcedPowerLimit(h)` | **mW** | current TGP cap |
| Power limit (default) | `nvmlDeviceGetPowerManagementLimit(h)` | **mW** | |
| Utilisation | `nvmlDeviceGetUtilizationRates(h)` → `.gpu`, `.memory` | **% (0–100)** | sample window 1/6–1 s |
| PCIe link gen | `nvmlDeviceGetCurrPcieLinkGeneration(h)` | int (e.g. 3) | `GetPcieLinkGeneration` = max capable |
| PCIe link width | `nvmlDeviceGetCurrPcieLinkWidth(h)` | lanes (e.g. 8) | `GetPcieLinkWidth` = max capable |
| Persistence mode | `nvmlDeviceGetPersistenceMode(h)` | `NVML_FEATURE_ENABLED/_DISABLED` | |
| Driver version | `nvmlSystemGetDriverVersion()` | bytes/str | or `nvmlDeviceGetDriverVersion(h, 96)` |
| Temp threshold | `nvmlDeviceGetTemperatureThreshold(h, NVML_TEMPERATURE_THRESHOLD_SHUTDOWN)` | °C | slow/thermal targets too |

Structs (verified in nvml.h, Sources #2):
- `nvmlUtilization_t { unsigned int gpu; unsigned int memory; }` — percents.
- `nvmlMemory_t { unsigned long long total, free, used; }` — **bytes**.
- `NVML_VALUE_NOT_AVAILABLE == (-1)` — check `usedGpuMemory` and some fields under WDDM.

**Hotspot / memory-junction temp:** NVML exposes only the single **GPU core temp** on GeForce. Memory-junction temperature is reachable only through field-value queries (`nvmlDeviceGetFieldValues` with `NVML_FI_DEV_MEMORY_TEMP`) on supported (GDDR6X/high-end) parts — **not** reliably on a GTX 1650. There is **no AMD-style "hotspot/junction" sensor** in NVML for GeForce. Do not promise a hotspot metric.

### A1.3 Error handling (Optimus / sleep-resume)

NVML return codes relevant here (nvml.h enum, Sources #2/#3):
- `NVML_ERROR_NOT_SUPPORTED = 2` → pynvml raises **`NVMLError_NotSupported`**.
- `NVML_ERROR_GPU_IS_LOST = 14` → pynvml raises **`NVMLError_GpuIsLost`** ("GPU has fallen off the bus"; NVML change log confirms all device APIs can return it, Sources #3).
- `NVML_ERROR_UNINITIALIZED = 0`, `NVML_ERROR_DRIVER_NOT_LOADED = 8`, `NVML_ERROR_RESET_REQUIRED = 15`, `NVML_ERROR_NOT_READY = 26`.

On an Optimus laptop, when the dGPU is powered down (DDR "off"), many queries return `NotSupported`, and after **sleep/resume** the handle can be invalid → `GpuIsLost`. Required pattern: initialise lazily, catch per-call, and on `GpuIsLost` call `nvmlShutdown()` + `nvmlInit()` + re-acquire the device handle before retrying.

### A1.4 Code (pip = `nvidia-ml-py`)

```python
# pip: nvidia-ml-py  ->  import pynvml
import pynvml

def read_nvidia():
    pynvml.nvmlInit()                       # or pynvml.nvmlInit_v2()
    try:
        idx = 0                             # pick the GTX 1650 by name/PCI bus
        h = pynvml.nvmlDeviceGetHandleByIndex(idx)
        out = {
            "name":        pynvml.nvmlDeviceGetName(h).decode() if isinstance(pynvml.nvmlDeviceGetName(h), bytes) else pynvml.nvmlDeviceGetName(h),
            "temp_c":      pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU),
            "fan_pct":     pynvml.nvmlDeviceGetFanSpeed(h),
            "gfx_mhz":     pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_GRAPHICS),
            "mem_mhz":     pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM),
            "mem_free_B":  pynvml.nvmlDeviceGetMemoryInfo(h).free,
            "mem_used_B":  pynvml.nvmlDeviceGetMemoryInfo(h).used,
            "mem_tot_B":   pynvml.nvmlDeviceGetMemoryInfo(h).total,
            "power_mW":    pynvml.nvmlDeviceGetPowerUsage(h),
            "power_lim_mW":pynvml.nvmlDeviceGetEnforcedPowerLimit(h),
            "util_gpu_pct":pynvml.nvmlDeviceGetUtilizationRates(h).gpu,
            "pcie_gen":    pynvml.nvmlDeviceGetCurrPcieLinkGeneration(h),
            "pcie_width":  pynvml.nvmlDeviceGetCurrPcieLinkWidth(h),
            "persist":     pynvml.nvmlDeviceGetPersistenceMode(h),
            "driver":      pynvml.nvmlSystemGetDriverVersion().decode(),
        }
        return out
    except pynvml.NVMLError_GpuIsLost:
        pynvml.nvmlShutdown(); pynvml.nvmlInit()   # sleep-resume recovery
        return {"error": "GPU_IS_LOST"}
    except pynvml.NVMLError_NotSupported:
        return {"error": "NOT_SUPPORTED (dGPU likely powered down)"}
    finally:
        try: pynvml.nvmlShutdown()
        except Exception: pass
```

> Use `nvmlDeviceGetHandleByPciBusId` to unambiguously pick the dGPU on a hybrid system (e.g. `00000000:01:00.0`).

### A1.5 Fallback: `nvidia-smi` (cli)

```powershell
nvidia-smi --query-gpu=name,temperature.gpu,fan.speed,clocks.gr,clocks.mem,`
utilization.gpu,utilization.memory,memory.used,memory.free,memory.total,`
power.draw,power.limit,pcie.link.gen,pcie.link.width,persistence_mode,driver_version`
 --format=csv,noheader,nounits
```
Note `power.draw` / `power.limit` are reported in **W** by nvidia-smi (not mW) — convert if unifying with NVML. This is the most portable fallback and works even if the Python NVML binding hiccups.

---

## A2. NVIDIA GTX 1650 — Overclocking on Windows

### A2.1 What is actually adjustable

On a **laptop** GTX 1650 the VBIOS locks most controls. Realistically open: **core clock offset** and **memory clock offset**. **Voltage and power-limit sliders are locked** on mobile Turing (A2.3). Fan curve may be controllable but is usually OEM-managed.

### A2.2 Path 1 — NVAPI via **ctypes** (`nvapi64.dll`)  → *pure Python possible but fragile*

There is **no official Python NVAPI binding**. **NvAPIWrapper is a C#/.NET library** (SoroushFalahati/NvAPIWrapper), not Python (Sources #5). So Python must bind `nvapi64.dll` with `ctypes`:

Relevant NVAPI entry points (undocumented/driver-private for OC):
- `NvAPI_Initialize`
- `NvAPI_GPU_GetAllClockFrequencies` — read clock domains (core/mem) per P-state.
- `NvAPI_GPU_SetPstates20` / `NvAPI_GPU_SetPstates20_v2` — set **clock frequency / voltage deltas** for P-state 0 (this is the OC hook).
- `NvAPI_GPU_ClientPowerPoliciesGetInfo` / `NvAPI_GPU_ClientPowerPoliciesSetStatus` — power-limit policy (A3).
- `NvAPI_GPU_SetCoolerLevels` — fan level (legacy).

**Assessment:** implementable in pure Python via ctypes, but (a) the OC functions are not in the stable public NVAPI docs, (b) signatures change across driver versions, and (c) mobile VBIOS rejects most `SetPstates20` writes. Treat as experimental. **Not recommended as the primary control path.**

### A2.3 Path 2 — Drive **MSI Afterburner** (cli / profile)  → *recommended*

MSI Afterburner accepts **profile command-line arguments** that apply a saved OC profile (Sources #6):
- `MSIAfterburner.exe -profile1` … `-profile5` → apply the corresponding saved profile.
- `/s` → start minimised/silent (for autostart).
- Profiles are stored under the install `Profiles` folder and settings in `MSIAfterburner.cfg`.
- Keyboard `1`–`5` also load profiles in the GUI.

Robust integration: (1) write/choose a profile in the GUI first, (2) from NitroMaster launch `MSIAfterburner.exe -profileN`, or (3) edit the profile file then re-apply. The exact on-disk **profile-file schema** and Afterburner's **shared-memory (MACM/MAHM) structs** used by RTSS are **UNVERIFIED** here and should be treated as third-party/undocumented. Requiring Afterburner to be installed is the pragmatic choice for safe, reversible OC.

**Fan / OSD:** RTSS (RivaTuner) rides alongside Afterburner for on-screen display; not needed for clock control.

### A2.4 Safe voltage/clock offset envelope (TU117 laptop)

See the consolidated **Safe Overclocking Envelope** table below. Mobile TU117 has **no voltage headroom** (slider locked), so higher offsets just hit the power/thermal wall.

---

## A3. NVIDIA — Power & Clock Limits (`nvidia-smi -pl`)

**`nvidia-smi -pl <watts>` is NOT supported on laptop GeForce.** Confirmed by NVIDIA forum reports: *"Changing power management limit is not supported for GPU: 00000000:01:00.0"* on a mobile RTX 3080 (Sources #4), and mobile RTX 4060 users likewise unable to raise TGP via `-pl` (Sources #4). The same limitation applies to the GTX 1650 laptop: **TGP is firmware (VBIOS/OEM) fixed**.

- `NvAPI_GPU_ClientPowerPoliciesGetInfo/SetStatus` are the NVAPI equivalent but are likewise **locked/ignored on mobile** (OEM power tables). → **UNVERIFIED as a working mobile control**; do not promise TGP editing.
- Read-only, still useful: `nvmlDeviceGetEnforcedPowerLimit()` (mW) shows the current TGP cap; `nvidia-smi -q -d POWER` shows min/default/max limits.

**Conclusion for NitroMaster:** expose power limit as **read-only telemetry** on the AN515-45; do not ship a TGP slider as a supported feature.

---

## B1. AMD Radeon Vega iGPU (Cezanne) — Telemetry on Windows

There is **no NVML-equivalent** AMD library. Realistic options, best-first:

1. **LibreHardwareMonitor (LHM)** via **pythonnet** — **primary recommendation**. For the Cezanne Vega iGPU LHM reports `HardwareType.GpuAmd` (enum verified: `Motherboard, SuperIO, Cpu, Memory, GpuNvidia, GpuAmd, GpuIntel, Storage, Network, ...`, Sources #8). Sensors: GPU temperature (edge, °C), core clock (MHz), memory clock, load (%), fan. LHM's AMD GPU reader is built on AMD's **ADL2** (`atiadlxx.dll`).
2. **AMD ADLX SDK** — modern AMD library ("Performance Monitoring", "GPU Tuning", Sources #10). Native **C/C++**; GPUOpen states a **binding wrapper** is used for C#/Java/**Python** (Sources #10). ADLX 2.0 (Sep 2026) explicitly targets agentic/Python access. Use if you need fine-grained tuning; heavier integration than LHM.
3. **Legacy ADL (`atiadlxx.dll` / `ADL2_*`)** — lower-level; ctypes-able; deprecated in favour of ADLX.
4. **`Win32_VideoController` (WMI)** — **static only** (name, driver version, adapter RAM, status). No live temp/clock.
5. **Radeon Software overlay** — human-readable but **not scriptable**; not a data source.

**Fallback chain (telemetry):** LHM/pythonnet → ADLX (ctypes/binding) → ADL2 ctypes → WMI static.

### B1.1 Code (LHM via pythonnet)

```python
# pip: pythonnet  ->  import clr   (loads LibreHardwareMonitorLib.dll)
import clr
clr.AddReference(r"C:\path\LibreHardwareMonitor\LibreHardwareMonitorLib")
from LibreHardwareMonitor.Hardware import Computer, HardwareType

c = Computer()
c.IsGpuEnabled = True           # also IsCpuEnabled, IsMotherboardEnabled ...
c.Open()
for hw in c.Hardware:
    if hw.HardwareType == HardwareType.GpuAmd:      # Cezanne Vega iGPU
        hw.Update()
        for s in hw.Sensors:
            # s.SensorType in {Temperature, Clock, Load, Fan, ...}
            print(s.Name, s.Value)   # Temperature -> °C, Clock -> MHz, Load -> %
c.Close()
```
(Sources #9 confirm the `clr` + `Computer` pattern.)

---

## B2. AMD iGPU — Clock & Power Limits (Cezanne)

**`RyzenAdj` is the real, working tool** (needs Administrator). Its CLI is identical on Windows/Linux. Verified options (Sources #11):

- iGPU (GFX) clock: **`--max-gfxclk=<u32>`** (max GFX clock, **MHz**) and **`--min-gfxclk=<u32>`** (min GFX clock, **MHz**). → *Not* `--gfx-clk` (that flag does not exist).
- Power limits (APU-wide, **mW**): `--stapm-limit` (sustained), `--fast-limit` (PPT fast), `--slow-limit` (PPT slow).
- Thermal: `--tctl-temp` (°C), `--apu-skin-temp`.
- Currents (mA): `--vrm-current`, `--vrmsoc-current`, `--vrmmax-current`, `--vrmsocmax-current`.
- Misc clocks (MHz): `--max/min-socclk-frequency`, `--max/min-fclk-frequency`, `--max/min-vcn`, `--max/min-lclk`.

**Cezanne support is confirmed** — RyzenAdj v0.8.2 changelog: *"Fix Slow Time and STAPM Time output for Cezanne"* (Sources #11). It works by poking the SMU (`ryzen_nb_smu`), so values may be re-set after AC/plug events.

```powershell
# examples (Administrator required)
ryzenadj.exe --min-gfxclk=400 --max-gfxclk=1800        # clamp iGPU GFX clock (MHz)
ryzenadj.exe --stapm-limit=35000 --fast-limit=42000 --slow-limit=38000 --tctl-temp=85
```

**Radeon Software:** manual tuning only (Performance → Tuning), not scriptable. **`powercfg`** governs CPU/SoC power *plans*, not the iGPU GFX clock directly — use RyzenAdj for GFX clock. Ship the iGPU clock/power feature as **"apply RyzenAdj profile"** (bundled `ryzenadj.exe`, run elevated).

---

## C1. Windows 11 Per-App GPU Preference (Graphics Performance Preference)

**Registry:** `HKEY_CURRENT_USER\SOFTWARE\Microsoft\DirectX\UserGpuPreferences` (Sources #12).
- **Value name** = full path to the executable (e.g. `C:\Games\foo\foo.exe`).
- **Value type** = `REG_SZ`.
- **Value data** = `GpuPreference=N;` where **N**:
  - `0` = **Let Windows decide** (auto/Optimus default)
  - `1` = **Power-saving GPU** (the Radeon Vega **iGPU**)
  - `2` = **High-performance GPU** (the GTX 1650 **dGPU**)

This is the exact mechanism behind **Settings → System → Display → Graphics → (app) → Options** (the "Power saving" / "High performance" / "Let Windows decide" dialog). Programmatically set it with `winreg`:

```python
# ctypes/std-lib (winreg) — no third-party deps
import winreg
KEY = r"SOFTWARE\Microsoft\DirectX\UserGpuPreferences"
def set_gpu_pref(exe_path, pref):           # pref: 0 auto, 1 iGPU, 2 dGPU
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, exe_path, 0, winreg.REG_SZ, f"GpuPreference={pref};")
```

**Restart required:** the preference is read at **process launch**; an already-running app keeps its current GPU. Changing it does not migrate a live process. (`preferred-gpu-changer` also writes this value then relaunches the app, Sources #12.)

---

## C2. NVIDIA Optimus Profile Control + MUX Limitation

### C2.1 NVIDIA profile (per-.exe) control

The NVIDIA "Manage 3D Settings → Preferred graphics processor" per-profile override is stored in the **DRS (Driver Profile Settings)** system, manipulated by **`NvAPI_DRS_*`**:
- `NvAPI_DRS_CreateSession`, `NvAPI_DRS_LoadSettings`, `NvAPI_DRS_FindProfileByName`, `NvAPI_DRS_GetProfileSetting` / `NvAPI_DRS_SetProfileSetting`, `NvAPI_DRS_SaveSettings`.
- The Optimus-specific knobs are the **`SHIM_RENDERING_MODE` / `SHIM_MCS...`** profile settings (force dGPU vs integrated). These are **undocumented private settings**; IDs must be pulled from the driver/NvAPI headers.

**Python path:** possible via **ctypes `nvapi64.dll`** (same caveats as A2.2) — feasible but brittle. **Practical alternative:** ship/delegate to **`nvidia-profile-inspector`** (Orbmu2k) which edits the same DRS profiles and supports **`.nip` profile import** (Sources #13). Programmatic force-onto-dGPU is thus: import a `.nip` profile or write DRS via ctypes.

### C2.2 `CUDA_VISIBLE_DEVICES` — scope warning

`CUDA_VISIBLE_DEVICES` only controls **CUDA compute** device visibility; it does **not** move a graphics (Direct3D/OpenGL) app to the iGPU. For "force iGPU" on a *graphics* app, use **C1** (UserGpuPreferences) or the DRS profile, not the CUDA env var. (For CUDA workloads, `CUDA_VISIBLE_DEVICES=1` can hide the dGPU from a compute process.)

### C2.3 MUX / MSHybrid on the AN515-45 — hard limitation

The **Acer Nitro 5 AN515-45 has no MUX switch** and no Advanced Optimus; the **internal display is wired through the Vega iGPU**, with the GTX 1650 always rendering via Optimus copy-forward (Sources #14, direct quote from an AN515-45 review: *"There's no MUX switch here, and the display is hooked up through the Vega iGPU."*).

Consequences for NitroMaster:
- **Cannot** give the dGPU a direct path to the built-in panel → no full dGPU-only mode, no meaningful G-Sync on the internal screen.
- The best achievable is **render-on-dGPU, present-via-iGPU** (Optimus). Latency/overhead from the copy cannot be removed in software.
- Some external ports are **directly wired to the dGPU** on certain Nitro models (HDMI/USB-C→DP), which effectively bypasses Optimus for that display — **port wiring on the AN515-45 is UNVERIFIED**; verify before advertising "external monitor = dGPU-direct".

---

## C3. Which GPU Is Currently Rendering an App ("active render GPU")

Three complementary techniques:

1. **DXGI adapter enumeration** — `CreateDXGIFactory1` → `IDXGIFactory::EnumAdapters1` lists each GPU as a `DXGI_ADAPTER_DESC` with a **`LUID`** (locally unique ID). This is the authoritative GPU↔LUID map (iGPU + dGPU). `EnumDisplayDevices` gives display/monitor names and which adapter drives which display. (Sources #15 confirm the "DXGI adapter list" pairing.)
2. **Per-process GPU Engine perf counters** — Windows exposes `\GPU Engine(<instance>)\Utilization Percentage` (also `EngUtilization`, `Context Priority Time`, etc.), where the instance encodes `pid`, adapter **LUID**, physical adapter index and engine type (3D/Copy/VideoEncode/...). Reading these via **PDH** (`PdhOpenQuery`/`PdhAddCounter`) or PowerShell `Get-Counter` reveals, per PID, the utilisation **split across both adapters** — i.e. which GPU a process is actually using. Confirmed behaviour (Sources #15, a bug report): *"`\GPU Engine(*)\Utilization Percentage` still showed the GPU process split across both adapters."*
3. **Map LUID → adapter** — match the perf-counter instance LUID to the DXGI adapter LUID from (1) to label each usage sample as "iGPU" or "dGPU".

**Windows 11 Task Manager** does exactly this internally (per-process GPU + which engine). The **rigstats** project (Sources #15) dumps raw `\GPU Engine(*)` instances together with the DXGI adapter list — a good reference for the instance-name grammar.

```python
# Conceptual (PowerShell/ctypes PDH). Instance name looks like:
#   pid_1234_luid_0x00000000_0x0000A5D3_phys_0_eng_3D_engtype_3D
# Parse the LUID and compare to DXGI adapters to decide iGPU vs dGPU.
import subprocess
out = subprocess.run(["powershell", "-Command",
    "(Get-Counter '\\GPU Engine(*)\\Utilization Percentage').CounterSamples | "
    "Select InstanceName, CookedValue | Format-Table -AutoSize"],
    capture_output=True, text=True).stdout
```

> Note: `\GPU Engine` counters can lag and briefly report stale instances after a process exits; filter `CookedValue > 0` and match live PIDs.

---

## Python Integration Recipe (exact libs + call patterns)

| Capability | Method | Library | Type |
|---|---|---|---|
| NVIDIA telemetry | NVML | `nvidia-ml-py` (`import pynvml`) | **pip** |
| NVIDIA telemetry (fallback) | `nvidia-smi --query-gpu` | `subprocess` | std-lib |
| NVIDIA OC (experimental) | `nvapi64.dll` `NvAPI_GPU_SetPstates20` | `ctypes` | **ctypes** |
| NVIDIA OC (recommended) | MSI Afterburner `-profileN` | `subprocess` + Afterburner install | **cli** |
| AMD iGPU telemetry | LibreHardwareMonitor | `pythonnet` (`import clr`) | **pip** + DLL |
| AMD iGPU telemetry (advanced) | ADLX SDK | `ctypes`/binding wrapper | **ctypes** |
| AMD iGPU clock/power | RyzenAdj | `subprocess` (`ryzenadj.exe`, admin) | **cli** |
| Per-app GPU preference | UserGpuPreferences | `winreg` | std-lib |
| Optimus profile force | DRS / profile-inspector | `ctypes nvapi64.dll` **or** `nvidia-profile-inspector` `.nip` | **ctypes / cli** |
| Active render GPU | `\GPU Engine` PDH + DXGI LUID | `subprocess`/`ctypes pdh` | std-lib |

**Minimal combined telemetry loop (pip: `nvidia-ml-py`, `pythonnet`):**

```python
import pynvml
# ... read NVIDIA per A1.4 (mW, MHz, bytes, °C) ...

import clr
clr.AddReference(r"C:\path\LibreHardwareMonitorLib")
from LibreHardwareMonitor.Hardware import Computer, HardwareType
comp = Computer(); comp.IsGpuEnabled = True; comp.Open()
for hw in comp.Hardware:
    if hw.HardwareType == HardwareType.GpuAmd:
        hw.Update()
        amd = {s.Name: s.Value for s in hw.Sensors}   # °C / MHz / %
comp.Close()
```

**Control helpers:**
```python
# set an app to dGPU (2) / iGPU (1)
import winreg
with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
        r"SOFTWARE\Microsoft\DirectX\UserGpuPreferences", 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, r"C:\Games\foo\foo.exe", 0, winreg.REG_SZ, "GpuPreference=2;")

# apply an Afterburner OC profile, and clamp iGPU clock (admin)
import subprocess
subprocess.Popen([r"C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe", "-profile1"])
subprocess.run(["ryzenadj.exe", "--min-gfxclk=400", "--max-gfxclk=1800"])   # admin
```

---

## Safe Overclocking Envelope Table (TU117 / GTX 1650 laptop)

These are **community-typical** ranges; exact stable values are chip/laptop/cooling specific. Validate with a stress test + artifact check.

| Control | Typical safe range | Hard limit / wall | Mobile (AN515-45) status |
|---|---|---|---|
| **Core clock offset** | **+100 … +200 MHz** | Power/thermal throttle (TGP ~50–60 W); no voltage headroom | ✅ adjustable (Afterburner / `SetPstates20`) |
| **Memory clock offset** | **+500 … +1000 MHz** (GDDR6) | Memory errors → artifacts; some GDDR6 tops out ~+700 | ✅ adjustable |
| **GPU voltage (core)** | **not adjustable** | VBIOS **locked** on laptop Turing | ❌ locked |
| **Power limit (TGP)** | **not adjustable** | `nvidia-smi -pl` unsupported; OEM firmware fixed | ❌ locked |
| **Fan curve** | OEM default recommended | Overriding can hurt cooling | ⚠️ partial (Afterburner) |
| **VRAM total / clocks base** | GTX 1650 mobile: 4 GB GDDR6, boost ≈ 1395–1560 MHz (TGP-dependent) | fixed by VBIOS | read-only |

**What breaks it:** excess core offset without voltage → TDR/driver reset (screen flash), throttling; excess memory offset → visual artifacts, ECC-less corruption, crashes. The **lack of voltage/power control** on mobile means "higher offset" mostly just moves you into the throttle wall — gains are modest (single-digit %). **ALWAYS make OC opt-in, with a revert-to-default button and a thermal cap.**

---

## Fallback Chains (summary)

- **NVIDIA telemetry:** `pynvml` → `nvidia-smi --query-gpu` → NVAPI ctypes (last resort).
- **NVIDIA OC:** MSI Afterburner `-profileN` → NVAPI `SetPstates20` (ctypes, experimental) → *no reliable pure-code path on mobile*.
- **NVIDIA power limit:** read-only telemetry (no write path on laptop).
- **AMD iGPU telemetry:** LHM/pythonnet → ADLX → ADL2 ctypes → WMI static.
- **AMD iGPU clock/power:** RyzenAdj (elevated) → Radeon Software (manual).
- **Per-app GPU switch:** `UserGpuPreferences` (winreg) → NVIDIA DRS/profile-inspector → `CUDA_VISIBLE_DEVICES` (CUDA only).

---

## Unsupported / Risky — do NOT promise these

- **`nvidia-smi -pl` / TGP slider** on the laptop GTX 1650 — **not supported** (Sources #4). Expose as read-only.
- **GPU voltage control** on mobile TU117 — **locked by VBIOS**.
- **Fan RPM via NVML** — NVML gives fan **%**, not RPM; no stable GeForce RPM call (**UNVERIFIED**).
- **Separate GPU "hotspot/junction" temp on GeForce** — not exposed by NVML (that's an AMD ADL concept); only core (and, on high-end parts, memory-junction) temp.
- **MUX / Advanced Optimus / dGPU-direct to the internal panel** — **impossible on the AN515-45** (no MUX, panel wired to Vega iGPU, Sources #14). Any "disable Optimus" feature is infeasible.
- **Moving a live-running app between GPUs** — preferences apply only at next launch.
- **`CUDA_VISIBLE_DEVICES` to force a *graphics* app onto the iGPU** — does not affect D3D/OpenGL; use the Windows preference instead.
- **Pure-Python NVAPI overclocking as a shipped default** — fragile across driver versions and often rejected by the laptop VBIOS; keep it behind an "experimental" flag or delegate to Afterburner.
- **Exact Afterburner profile-file schema / MACM shared-memory structs** and **ADLX Python binding specifics** — **UNVERIFIED**; treat as third-party/undocumented and confirm before coding against them.

---

## Sources

1. NVML API Reference Guide (NVIDIA) — https://docs.nvidia.com/deploy/nvml-api/index.html · PDF: https://docs.nvidia.com/deploy/pdf/NVML_API_Reference_Guide.pdf
2. `nvml.h` (structs `nvmlUtilization_t`, `nvmlMemory_t`, `NVML_VALUE_NOT_AVAILABLE`, error enum) — https://github.com/NVIDIA/gpu-monitoring-tools/blob/master/bindings/go/nvml/nvml.h
3. NVML Change Log / `NVML_ERROR_GPU_IS_LOST` ("GPU has fallen off the bus") — https://docs.nvidia.com/deploy/nvml-api/change-log.html
4. `nvidia-smi -pl` unsupported on mobile — NVIDIA forums "Power Limit on 3000 Mobile Series" https://forums.developer.nvidia.com/t/power-limit-on-3000-mobile-series/193443 · RTX 4060 laptop https://forums.developer.nvidia.com/t/unable-to-run-an-rtx-4060-laptop-gpu-at-more-than-80w-on-linux/319804
5. NvAPIWrapper is C#/.NET (not Python) — https://stackoverflow.com/questions/29667666/how-get-gpu-information-in-c · https://github.com/SoroushFalahati/NvAPIWrapper
6. MSI Afterburner `-profile1..5` command-line applies profiles — https://www.reddit.com/r/overclocking/comments/bdlfjl/change_afterburner_oc_profiles_on_program_launch/ · https://forums.guru3d.com/threads/afterburner-command-line-options-and-startup.322469/ · `/s` autostart https://www.reddit.com/r/MSI_Gaming/comments/nhnuch/how_to_make_msi_afterburner_start_up_with_windows/ · MSI guide https://www.msi.com/blog/msi-afterburner-overclocking-undervolting-guide
7. GTX 1650 Mobile (TU117) specs — https://www.techpowerup.com/gpu-specs/geforce-gtx-1650-mobile.c3367
8. LibreHardwareMonitor `HardwareType` enum (`GpuNvidia`, `GpuAmd`, `GpuIntel`) — https://github.com/LibreHardwareMonitor/LibreHardwareMonitor (HardwareType.cs)
9. LHM via pythonnet `import clr` + `Computer` — https://stackoverflow.com/questions/62617789/get-cpu-and-gpu-temp-using-python-windows · https://github.com/nicolargo/glances/issues/3265
10. AMD ADLX SDK (Performance Monitoring / GPU Tuning; Python binding wrapper) — https://gpuopen.com/adlx/ · https://github.com/GPUOpen-LibrariesAndSDKs/ADLX · programming guide https://gpuopen.com/manuals/adlx/programming-with-adlx/adlx-programming-guide/quick-start/using-adlx-in-an-application/
11. RyzenAdj options (`--max-gfxclk`, `--min-gfxclk`, `--stapm-limit`, `--fast-limit`, `--slow-limit`, `--tctl-temp`) + Cezanne fix — https://github.com/FlyGoat/RyzenAdj (README) · v0.8.2 notes https://coolenjoy.net/bbs/pds/147033
12. `UserGpuPreferences` (`GpuPreference=0/1/2`) — https://learn.microsoft.com/en-us/answers/questions/4301937/how-can-i-set-the-default-gpu-for-all-apps-on-windows-10 · https://github.com/thiwaK/preferred-gpu-changer
13. Nvidia Profile Inspector (DRS profile editor, `.nip` import) — https://www.pcgamingwiki.com/wiki/Nvidia_Profile_Inspector
14. AN515-45 **no MUX**, panel via Vega iGPU — https://www.ultrabookreview.com/45156-acer-nitro-5-amd-review/
15. `\GPU Engine(*)\Utilization Percentage` per-PID split across adapters + DXGI adapter list — https://github.com/anthropics/claude-code/issues/81836 · https://github.com/dvalfrid/rigstats
