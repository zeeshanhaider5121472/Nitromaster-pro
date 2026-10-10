# 02 — AMD Ryzen 5 5600H (Cezanne) CPU Telemetry & Power Control on Windows

> Research agent report #2 of 20 — "NitroMaster Pro Control Center" (target: Acer Nitro AN515-45, Ryzen 5 5600H + GTX 1650, 16 GB, Windows 11 x64).
> All claims are sourced inline. Anything not verified against a fetched source is tagged `UNVERIFIED`.

## Executive summary

1. **Authoritative CPU temperature on Cezanne = Tctl/Tdie**, read from SMN register `THM_TCON_CUR_TMP` (bits [31:21], 0.125 °C steps) — the exact path LibreHardwareMonitor (LHM) uses. There is **no reliable driverless** temperature path on this laptop; WMI thermal classes are widely unreliable and `psutil` gives **no temperature at all on Windows**.
2. Best tool: **LibreHardwareMonitorLib** (NuGet, .NET) via **pythonnet**. Class `LibreHardwareMonitor.Hardware.Cpu.Amd17Cpu` (internal; consumed via public `Computer`/`IHardware`/`ISensor` API) exposes `Core (Tctl)`, `Core (Tdie)`, `Core (Tctl/Tdie)`, `Package` power, per-core + `Cores (Average Effective)` clocks. Requires **Administrator** + its low-level driver (PawnIo module).
3. **Clocks:** `Win32_Processor.CurrentClockSpeed` is stale/unreliable; `psutil.cpu_freq()` on Windows returns the nominal fixed value. Use LHM effective clocks or `\Processor Information(_Total)\% Processor Performance` × nominal MHz (Task-Manager-style).
4. **Usage:** `psutil.cpu_percent(percpu=True)` is fine for per-core %; Windows `% Processor Time` under-reports vs Task Manager on boost-capable CPUs — prefer `% Processor Utility` / `% Processor Performance` semantics for "work vs. frequency" displays.
5. **Power control without BIOS:** (a) `powercfg` processor power management (`PERFBOOSTMODE`, `PERFBOOSTPOL`, `PROCTHROTTLEMIN/MAX`, `CPMINCORES/CPMAXCORES`) per power scheme, (b) **ryzenadj** SMU mailbox limits (fast/slow PPT, TDC/EDC, Tctl limit) — works on Cezanne for `fast-limit`, `slow-limit`, `tctl-temp`, VRM currents; `stapm-limit` only when STTv2 is disabled. Zen 3 adds OEM **upper caps** — ryzenadj returns success but silently clamps.
6. ryzenadj (v0.19.0) needs **Administrator** and ships `WinRing0x64.dll` + `WinRing0x64.sys` (a known vulnerable driver that Windows 11 Memory Integrity / vulnerable-driver blocklists may block).
7. Safe envelope to hardcode: Tctl warn 85 °C / act 90–95 °C (Tjmax 105 °C), sustained (STAPM/slow) ≤ 45 W default + 54 W max (cTDP up), fast PPT ≤ 54 W, `--tctl-temp=90`.
8. Admin split: perf counters, WMI, `powercfg /query`, psutil work as a normal user; `powercfg /set*`, registry unhide, LHM sensors, ryzenadj all need elevation.

---

## 0. Target facts (verified)

| Item | Value | Source |
|---|---|---|
| CPU | AMD Ryzen 5 5600H, code name **Cezanne**, Zen 3, 6C/12T | [AMD support page](https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-5000-series/amd-ryzen-5-5600h.html), [heise listing](https://preisvergleich.heise.de/lenovo-ideapad-5-pro-16ach6-cloud-grey-82l500tlge-a2688473.html) |
| Base / boost clock | 3.3 GHz / up to 4.2 GHz | [AMD support page](https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-5000-series/amd-ryzen-5-5600h.html) |
| Cache | L2 3 MB, L3 16 MB | same |
| Default TDP | 45 W | same |
| cTDP | 35–54 W | [heise listing](https://preisvergleich.heise.de/lenovo-ideapad-5-pro-16ach6-cloud-grey-82l500tlge-a2688473.html) |
| Max operating temp (Tjmax) | 105 °C | [AMD support page](https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-5000-series/amd-ryzen-5-5600h.html) |
| iGPU | Radeon Vega 7 | task brief (UNVERIFIED against fetched AMD page — not on the fetched support-page snippet) |
| ACPI PPM | CPPC (Zen 3 mobile) → Windows "Processor Performance Boost Mode" applies with CPPC semantics | [MS Server PPM tuning](https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/hardware/power/power-performance-tuning) |

---

## 1. Temperature telemetry

### 1.1 The authoritative sensor: Tctl/Tdie

- On AMD Family 17h (Zen/Zen 2/Zen 3 incl. Cezanne, model 0x21) the die temperature is the SMN register **`F17H_M01H_THM_TCON_CUR_TMP`**, current temperature in bits **[31:21]**, in units of 0.125 °C (LibreHardwareMonitor computes `(reg >> 21) * 125` and works in millidegrees). Verified directly in [Amd17Cpu.cs](https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/LibreHardwareMonitorLib/Hardware/Cpu/Amd17Cpu.cs).
- LHM exposes three temperature sensors for this register: **`Core (Tctl)`**, **`Core (Tdie)`**, and merged **`Core (Tctl/Tdie)`**, plus up to 8 **CCD** temperatures (enabled for CPU model `0x21` = Zen 3 / Cezanne — `supportsPerCcdTemperatures = true` in the same source). On Cezanne (monolithic APU) the CCD temperature is the same silicon, so per-CCD is not additional insight.
- **Offset quirk:** some models signal a +49 °C adjustment through `RANGE_SEL[19]` / `TJ_SEL[17:16]`; LHM applies the k10temp-style offset table (code comment links to [k10temp.c offset table](https://github.com/torvalds/linux/blob/master/drivers/hwmon/k10temp.c#L78)). Tctl is the *control* temperature (may carry offset), Tdie = Tctl − offset. On mobile Cezanne Tctl and Tdie are typically identical → LHM shows the merged `Core (Tctl/Tdie)` sensor. For the app: **use `Core (Tctl/Tdie)` if present, else `Core (Tctl)`**.
- **Tctl is the right number for fan/throttle logic** — it is what AMD's boost/firmware control uses (the `--tctl-temp` limit in ryzenadj is also expressed in Tctl, see §4).

### 1.2 Reading it on Windows: LibreHardwareMonitor (best path)

Current master layout (verified via GitHub contents API + raw sources):

| Piece | Exact location | Role |
|---|---|---|
| Public API | `LibreHardwareMonitor.Hardware.Computer`, `IHardware`, `ISensor`, `IVisitor`, `IParameter` | what apps consume ([README sample](https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/README.md)) |
| AMD Zen driver class | `LibreHardwareMonitor.Hardware.Cpu.Amd17Cpu` (**`internal sealed class`**, file `LibreHardwareMonitorLib/Hardware/Cpu/Amd17Cpu.cs`) | creates all sensors listed above |
| MSR / SMN access | `LibreHardwareMonitor.PawnIo.AmdFamily17` (`ReadMsr`, `ReadSmn`) | register reads ([PawnIo dir](https://api.github.com/repos/LibreHardwareMonitor/LibreHardwareMonitor/contents/LibreHardwareMonitorLib/PawnIo)) |
| SMU mailbox | `LibreHardwareMonitor.PawnIo.RyzenSmu` — `GetSmuVersion()`, `GetCodeName()`, `ReadPmTable(size)`, `UpdatePmTable()`, `ResolvePmTable(out version, out tableBase)` ([RyzenSmu.cs](https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/LibreHardwareMonitorLib/PawnIo/RyzenSmu.cs)) | PM Table (power metrics) + SMU version |
| PM-table sensor map | `RyzenSMU.GetPmTableStructure()` / `GetReport()` referenced by `Amd17Cpu.cs` (exact file containing the `RyzenSMU` type not located in master — `UNVERIFIED`) | per-APU PM Table sensors |

**Correction to the brief:** there is no `LibreHardwareMonitor.Hardware.Amd.Amd17Cpu` / `AmdSmu` in current master. The real names are `LibreHardwareMonitor.Hardware.Cpu.Amd17Cpu` and `LibreHardwareMonitor.PawnIo.RyzenSmu`. Consumers never touch these classes directly — they use `Computer { IsCpuEnabled = true }` and enumerate `hardware.Sensors`.

**Driver requirement (the catch):** reading SMN/MSR requires ring-0 I/O. LHM uses its PawnIo-based module (loaded from embedded resource `LibreHardwareMonitor.Resources.PawnIo.RyzenSMU.bin` per [RyzenSmu.cs](https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/LibreHardwareMonitorLib/PawnIo/RyzenSmu.cs)); older builds / sibling projects use **WinRing0**. The Python wrapper **PyHardwareMonitor** instructs installing the PawnIO driver (`winget install PawnIO`) for system sensors ([PyHardwareMonitor README](https://raw.githubusercontent.com/snip3rnick/PyHardwareMonitor/master/README.md)). LHM's README: *"Some sensors require administrator privileges to access the data."* ([README](https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/README.md)).

**So the honest answer to "without a kernel driver":** *there is no trustworthy driverless CPU-temperature path on Windows for this APU.* Everything real (LHM, HWiNFO, Ryzen Master, ryzenadj) goes through a signed helper driver; the driverless WMI routes (§1.4) are exactly the "often fake" ones.

Package/LHM version: NuGet `LibreHardwareMonitorLib` latest stable **0.9.6** (prerelease 0.9.7-pre752), targets .NET Framework 4.7.2 / .NET Standard 2.0 / .NET 8–10 ([README](https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/README.md), [NuGet index](https://api.nuget.org/v3-flatcontainer/librehardwaremonitorlib/index.json) queried 2026-10-10).

### 1.3 Ryzen Master / AMD SMU mailbox

- **AMD Ryzen Master is not a telemetry source we can embed** and is aimed at desktop Ryzen CPUs (AMD markets it as an overclocking utility for desktop parts: [Ryzen Master page](https://www.amd.com/en/products/software/ryzen-master.html)). That it refuses mobile/H-series APUs like the 5600H is community consensus but I could not fetch an official compatibility sentence — `UNVERIFIED` (exact wording). **Do not depend on Ryzen Master in the app.**
- The **SMU mailbox** itself is reachable programmatically: LHM's `RyzenSmu` (read PM Table, `GetSmuVersion()`), or **ryzenadj** (`ryzenadj --info` prints SMU version + power metrics; `--dump-table` dumps the whole PM Table) ([RyzenAdj Options wiki](https://github.com/FlyGoat/RyzenAdj/wiki/Options)). Both need admin + driver.
- SMU firmware version for Cezanne: read at runtime via `ryzenadj --info` or LHM's `GetSmuVersion()`; a fixed version number is not safe to hardcode (`UNVERIFIED`).

### 1.4 WMI: `Win32_TemperatureProbe` / `MSAcpi_ThermalZoneTemperature` — unreliable, treat as last resort

- `MSAcpi_ThermalZoneTemperature` reads the **ACPI thermal zone**, not the CPU's Tctl. It is frequently missing, stuck, or plainly wrong on laptops (classic report: [SO "MSAcpi_ThermalZoneTemperature class not showing actual temperature"](https://stackoverflow.com/questions/9101295/msacpi-thermalzonetemperature-class-not-showing-actual-temperature)); tools have documented "Standard Windows WMI thermal zones … are not available on all systems" ([all-smi README](https://github.com/lablup/all-smi)). Even Microsoft support threads treat Windows ACPI thermal values as "most likely incorrect" ([MS Q&A](https://learn.microsoft.com/en-us/answers/questions/3759165/kernel-power-event-41-63-caused-by-erroneous-windo)).
- `Win32_TemperatureProbe` is an abstract CIM class OEMs rarely implement; on the AN515-45 expect **no instances or placeholder values** (`UNVERIFIED` on this exact machine — must be verified on target hardware at first run).
- **App policy:** query `root\wmi: MSAcpi_ThermalZoneTemperature` only as a *display-only* fallback clearly labeled "ACPI zone", never for fan/thermal protection logic, and sanity-check it (reject values that never move, values < 20 °C, or values that don't correlate with load).

### 1.5 What `psutil` can and cannot give

Verified against the psutil docs source ([docs/api.rst](https://raw.githubusercontent.com/giampaolo/psutil/master/docs/api.rst), [psutil.io/api](https://psutil.io/api/)):

- `psutil.sensors_temperatures()` → **availability: Linux, FreeBSD. Not Windows.** On Windows it is simply unavailable (no implementation in `_pswindows`). **psutil gives no CPU temperature on Windows.**
- `psutil.cpu_percent(interval=None, percpu=True)` → per-core + total usage ✔ (see §3).
- `psutil.cpu_freq()` → on Windows "this usually represents the nominal *fixed* value (never changing)" (direct doc quote, [psutil.io/api](https://psutil.io/api/)) and `percpu=True` is only supported on Linux/FreeBSD. So on Windows it is **not** a live frequency source.
- `psutil.cpu_times(percpu=True)`, `cpu_stats()`, `Process.cpu_affinity()` → ✔ useful (§3).

---

## 2. Clock speeds (per-core & package, effective vs nominal)

### 2.1 CPUID 0x15 / 0x16 (static topology facts)

- **Leaf 0x15** ("TSC/core crystal ratio"): EAX=denominator, EBX=numerator, ECX=core crystal frequency — used to derive TSC frequency ([CPUID reference](https://www.felixcloutier.com/x86/cpuid), [Wikipedia CPUID](https://en.wikipedia.org/wiki/CPUID)). On Zen, ECX is commonly 0 and tools fall back to 100 MHz crystal assumption — `UNVERIFIED` for Cezanne specifically.
- **Leaf 0x16** ("Processor Frequency Information"): EAX = processor base frequency (MHz), EBX = max frequency (MHz), ECX = bus/reference frequency (MHz) ([Wikipedia CPUID](https://en.wikipedia.org/wiki/CPUID), [felixcloutier CPUID](https://www.felixcloutier.com/x86/cpuid)). For the 5600H this yields 3300 / 4200 MHz; treat as *advertised* numbers for UI, not live data.
- `py-cpuinfo` fields relevant here ([py-cpuinfo README](https://github.com/workhorsy/py-cpuinfo)): `hz_advertised`/`hz_advertised_friendly`, `hz_actual`/`hz_actual_friendly`, `brand_raw`, `arch`, `family`, `model`, `stepping`, `count`, cache sizes, `flags`. **Note:** `hz_actual` on Windows is a snapshot from CPUID/registry-style sources, not a live per-core clock; the README itself marks raw fields as "unverified… wildly unexpected results or garbage". Use py-cpuinfo for identity only.

### 2.2 `Win32_Processor.CurrentClockSpeed` staleness

- WMI `Win32_Processor.CurrentClockSpeed` is documented as "current speed … in MHz" but in practice is **rarely refreshed** (updates slowly / sticks at base or max depending on firmware). Community reports: [SO "Unable to get current CPU frequency in Powershell or Python"](https://stackoverflow.com/questions/61802420/unable-to-get-current-cpu-frequency-in-powershell-or-python), [SO "C#: How to find the CPU's CURRENT Clock Speed?"](https://stackoverflow.com/questions/51332103/c-how-to-find-the-cpus-current-clock-speed), [ServerFault "Difference between CurrentClockSpeed and MaxClockSpeed"](https://serverfault.com/questions/121669/difference-between-currentclockspeed-and-maxclockspeed).
- **App policy:** use `MaxClockSpeed` (3300) as the nominal base; never render `CurrentClockSpeed` as a live gauge.

### 2.3 Performance counters (Task-Manager-grade, no driver)

- `\Processor Information(_Total)\% Processor Performance` (and per-instance `"0,0"`-style NUMA,CPU instance names) gives the *average* performance percentage; **effective frequency ≈ nominal MHz × %ProcessorPerformance / 100**. This is exactly the technique described in [SO 59969778 "How to get current CPU clock speed same as in Task Manager?"](https://stackoverflow.com/questions/59969778/how-to-get-current-cpu-clock-speed-same-as-in-task-manager) and reproduced in [windows_exporter #787](https://github.com/prometheus-community/windows_exporter/issues/787) ("On an AMD system, you will get a nice graph showing the effective P-state frequency of each hyperthread").
- `% Processor Performance` **can exceed 100 %** while boosting (it scales against nominal frequency) — that is how we show 4.2 GHz boost on a 3.3 GHz part.
- Per-core: same counter per `Processor Information(n,m)` instance. For truly per-core effective clocks with no math, LHM publishes per-core clock sensors plus `Cores (Average)` and `Cores (Average Effective)` (sensor names verified in [Amd17Cpu.cs](https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/LibreHardwareMonitorLib/Hardware/Cpu/Amd17Cpu.cs)).
- Counter reading via `PdhAddCounter`/`Perflib` needs **no admin** (MS's own Perflib sample consumes "Processor Information": [Using the Perflib functions](https://learn.microsoft.com/en-us/windows/win32/perfctrs/using-the-perflib-functions-to-consume-counter-data)).

---

## 3. Usage (per-core %, parking, affinity)

- **Total & per-core %:** `psutil.cpu_percent(interval=None, percpu=True)` (0–100 per logical CPU, thread-safe since 5.9.6, [psutil.io/api](https://psutil.io/api/)) — or `\Processor Information(*)\% Processor Utility`. psutil is fine here.
- **`% Processor Time` vs `% Processor Performance` (and why AMD boost makes it confusing):**
  - `% Processor Time` (old `\Processor` object) is *time-scheduling* based: it does **not** account for frequency variance. On frequency-scaling CPUs it disagrees with Task Manager by 10–15 % under load ([windows_exporter #787](https://github.com/prometheus-community/windows_exporter/issues/787)).
  - `% Processor Utility` is the frequency-weighted utilization Task Manager shows (same issue thread confirms Task Manager ≈ `% Processor Utility`).
  - `% Processor Performance` is *not* utilization — it is delivered performance vs nominal (used for frequency, §2.3). A "busy but downclocked" core can show high `% Processor Time`, lower `% Processor Utility`, and sub-100 `% Processor Performance`.
  - **App rule:** gauges labeled "CPU usage" → `% Processor Utility` semantics (or psutil); anything labeled "speed/frequency" → `% Processor Performance`-derived; never mix them in one chart.
- **Per-core parking:** controlled by `CPMINCORES`/`CPMAXCORES` power settings (§4). Observability: Resource Monitor shows parked cores; the `\Processor Information(*)\% Parking Status` counter reportedly exposes per-core parking (0/100) — `UNVERIFIED` (could not confirm against a fetched doc; verify on target with `typeperf "\Processor Information(*)\% Parking Status"` before shipping).
- **Affinity:** `psutil.Process().cpu_affinity()` / `cpu_affinity([0,1])` for get/set on Windows ([psutil.io/api-overview](https://psutil.io/api-overview/)). Note SMT pairing: 5600H = 6 cores × 2 threads; Windows exposes 12 logical CPUs ordered 0..11 (pairs UNVERIFIED — enumerate at runtime).

---

## 4. Power / boost control on Windows

### 4.1 `powercfg` processor power management (works without BIOS)

Setting group: **Processor power management** (`SUB_PROCESSOR`, subgroup GUID `54533251-82be-4824-96c1-47b60b740d00` — registry path seen in [this guide](https://gist.github.com/ehsan18t/268fa28f581e512a0a0df66b95daab88)).

| Alias (powercfg) | Setting | GUID | Notes |
|---|---|---|---|
| `PERFBOOSTMODE` | Processor performance boost mode | `be337238-0d82-4146-a960-4f3749d470c7` | **Hidden by default**; [MS docs](https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/options-for-perf-state-engine-perfboostmode) |
| `PERFBOOSTPOL` | Processor performance boost policy (0–100 %) | `45bcc044-d885-43e2-8605-ee0ec6e96b59` | [MS docs](https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/legacy-config-options-perfboostpol) |
| `PROCTHROTTLEMAX` | Maximum processor state (%) | `bc5038f7-23e0-4960-96da-33abaf5935ec` | [MS PPM tuning](https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/hardware/power/power-performance-tuning) |
| `PROCTHROTTLEMIN` | Minimum processor state (%) | `893dee8e-2bef-41e0-89c6-b55d0929964c` | same |
| `CPMINCORES` / `CPMAXCORES` | Core parking min/max cores (%) | `0cc5b647-c1df-4637-891a-dec35c318583` / `ea062031-0e34-4ff1-9b6d-eb1059334028` | [GUID list from `powercfg /aliases`](https://github.com/mkht/DSCR_PowerPlan/blob/master/DSCResources/cPowerPlanSetting/DATA/GUID_LIST_SETTING) |
| `PERFEPP` | Energy performance preference (0–100) | `36687f9e-e3a5-4dbf-b1dc-15eb381c6863` | [MS PPM tuning](https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/hardware/power/power-performance-tuning) |
| `THROTTLING` | Allow throttle states (on/off) | `3b04d4fd-1cc7-4f23-ab1c-d1337819c4bb` | the alias list calls it "Allow Throttle States"; **there is no `PERFTHROTTLING` alias** in `powercfg /aliases` output — `UNVERIFIED` claim in the brief; use `THROTTLING` |
| `PROCFREQMAX` | Maximum processor frequency (MHz) | `75b0ae3f-bce0-45a7-8c89-c9611c25e100` | hard MHz cap, coarser than `PROCTHROTTLEMAX` |

Full alias→GUID table (derived from `powercfg /aliases`): [mkht/DSCR_PowerPlan GUID_LIST_SETTING](https://github.com/mkht/DSCR_PowerPlan/blob/master/DSCResources/cPowerPlanSetting/DATA/GUID_LIST_SETTING).

**Processor Performance Boost Mode values** ([MS Server PPM table](https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/hardware/power/power-performance-tuning) + [MS PERFBOOSTMODE page](https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/options-for-perf-state-engine-perfboostmode)):

| Index | Name | P-state behavior | CPPC behavior (this CPU!) |
|---|---|---|---|
| 0 | Disabled | no boost | Disabled |
| 1 | Enabled | boost available on nominal request | "Enabled" (Windows picks target boost) |
| 2 | Aggressive | boost enabled | Windows requests **maximum** boost |
| 3 | Efficient Enabled | = index 1 | = index 1 |
| 4 | Efficient Aggressive | = index 2 | = index 2 |

Windows 11's UI additionally lists "Aggressive at Guaranteed" / "Efficient at Guaranteed" variants (reported as indices 5/6 in [this community write-up](https://gist.github.com/ehsan18t/268fa28f581e512a0a0df66b95daab88)); MS's own page only documents 0–4, so treat 5/6 as `UNVERIFIED` and validate with `powercfg /qh SUB_PROCESSOR PERFBOOSTMODE` on the target machine.

**Unhide the setting (registry, admin):**

```
HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerSettings\54533251-82be-4824-96c1-47b60b740d00\be337238-0d82-4146-a960-4f3749d470c7
  "Attributes" (REG_DWORD) 1 → 2      # 2 = visible in Advanced Power Settings
```

(from [the boost-mode guide](https://gist.github.com/ehsan18t/268fa28f581e512a0a0df66b95daab88); equivalently `powercfg -attributes SUB_PROCESSOR be337238-0d82-4146-a960-4f3749d470c7 -ATTRIB_HIDE` to re-hide). The setting is officially marked **"Hidden setting: Yes"** ([MS docs](https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/options-for-perf-state-engine-perfboostmode)).

**Apply per power scheme (must run `setactive` afterwards to take effect — MS: "You must run the powercfg -setactive command to enable the new settings"; no reboot needed) ([MS PPM tuning](https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/hardware/power/power-performance-tuning)):**

```bat
:: Boost OFF on battery, Aggressive on AC, for scheme 381b4222-f694-41f0-9685-ff5bb260df2e (Balanced)
powercfg /setdcvalueindex 381b4222-f694-41f0-9685-ff5bb260df2e sub_processor PERFBOOSTMODE 0
powercfg /setacvalueindex 381b4222-f694-41f0-9685-ff5bb260df2e sub_processor PERFBOOSTMODE 2

:: Cap 75% max frequency on battery; keep min state low
powercfg /setdcvalueindex 381b4222-f694-41f0-9685-ff5bb260df2e sub_processor PROCTHROTTLEMAX 75
powercfg /setdcvalueindex 381b4222-f694-41f0-9685-ff5bb260df2e sub_processor PROCTHROTTLEMIN 5

:: Park down to 50% cores on battery (quiet mode)
powercfg /setdcvalueindex 381b4222-f694-41f0-9685-ff5bb260df2e sub_processor CPMAXCORES 50

:: apply
powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e
```

(`sub_processor` alias and `/setacvalueindex` semantics per [powercfg docs](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/powercfg-command-line-options); `scheme_current` works as a scheme alias. Boost-mode command example per [MS PPM tuning](https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/hardware/power/power-performance-tuning).)

### 4.2 ryzenadj — real PPT/TDC/EDC/Tctl control on Cezanne

- Project: [FlyGoat/RyzenAdj](https://github.com/FlyGoat/RyzenAdj) — latest release **v0.19.0** (2026-05-13, GitHub API). Windows build ships `ryzenadj.exe` + `WinRing0x64.dll` + `WinRing0x64.sys` (verified: [win32 folder](https://api.github.com/repos/FlyGoat/RyzenAdj/contents/win32)); README: "put the dll library and sys driver in the same folder with ryzenadj.exe" and "You should run it with Administrator on Windows" ([README](https://github.com/FlyGoat/RyzenAdj)). No `inpout32/64` dependency — that's used by other tools, not ryzenadj.
- **Cezanne support matrix** ([Supported Models wiki](https://github.com/FlyGoat/RyzenAdj/wiki/Supported-Models)):

| Option | Cezanne | Meaning |
|---|---|---|
| `--fast-limit` (PPT fast, mW) | ✅ | current power limit |
| `--slow-limit` (PPT slow, mW) | ✅ | average power limit (`--slow-time` sets the constant, ✅) |
| `--stapm-limit` (mW) | ⚠ | **only if STTv2 is disabled**; if STTv2 is on, the value is accepted but overwritten by STTv2 |
| `--stapm-time` | ⚠ | no effect when STTv2 on |
| `--tctl-temp` (°C) | ✅ | Tctl temperature limit |
| `--vrm-current` / `--vrmsoc-current` (TDC, mA) | ✅ | sustained VRM current |
| `--vrmmax-current` / `--vrmsocmax-current` (EDC, mA) | ✅ | peak VRM current |
| `--prochot-deassertion-ramp` | ✅ | post-PROCHOT limit ramp |
| `--apu-skin-temp` / `--dgpu-skin-temp` / `--skin-temp-limit` (STT) | ⚠ | only effective if STTv2 is enabled |
| `--power-saving` / `--max-performance` | ✅ | AC/DC "setpoint" modes |
| `--max-gfxclk` etc. frequency knobs | ⛔ | removed on Zen 2/Zen 3 |

- **STTv2 vs STAPM (Zen 2/Zen 3 laptops):** with STTv2 enabled (common on OEM laptops) the sustained limit is managed by skin-temperature tracking — `stapm-limit` gets overwritten by fast-limit or the STT power value ([Options wiki](https://github.com/FlyGoat/RyzenAdj/wiki/Options), [Supported Models wiki](https://github.com/FlyGoat/RyzenAdj/wiki/Supported-Models)). Detect mode with `ryzenadj --info` / `--dump-table` (0.000 readings mean not measured / disabled — [issue #145 discussion](https://github.com/FlyGoat/RyzenAdj/issues/145)).
- **Zen 3 OEM value-range caps (critical for Acer):** "With Zen3 AMD did add a new way to prevent adjustments beyond a definable point… All adjustments return success, even if value did not get set; only values below the limit get applied; values above… get changed to (limit + 0.001)" ([Supported Models wiki](https://github.com/FlyGoat/RyzenAdj/wiki/Supported-Models)). **The app must verify effects via `--dump-table` after setting, never trust exit codes alone.**
- Values don't persist: "some settings could get overwritten by power management features of your device, and you need to regularly set your values again" — the repo ships `readjustService.ps1` + Task Scheduler install (`installServiceTask.bat`, task `AMD\RyzenAdj`) ([README](https://github.com/FlyGoat/RyzenAdj)).

**Concrete command lines (safe defaults for AN515-45 / 5600H):**

```bat
:: 1) inspect stock limits & SMU (always do this first)
ryzenadj.exe --info
ryzenadj.exe --dump-table

:: 2) "Balanced cool" — sustained 42 W, burst 54 W, Tctl target 90 C
ryzenadj.exe --stapm-limit=42000 --fast-limit=54000 --slow-limit=45000 --slow-time=30 --tctl-temp=90

:: 3) "Quiet" — sustained 25 W, no boost past 45 W
ryzenadj.exe --stapm-limit=25000 --fast-limit=35000 --slow-limit=30000 --tctl-temp=85

:: 4) "Performance (AC)" — sustained 45 W (= cTDP default), burst 54 W (= cTDP up)
ryzenadj.exe --stapm-limit=45000 --fast-limit=54000 --slow-limit=54000 --tctl-temp=95

:: 5) STTv2-style alternative when --info shows STTv2 active (skin temps in C, STT power in mW)
ryzenadj.exe --apu-skin-temp=45 --dgpu-skin-temp=45 --skin-temp-limit=25000 --fast-limit=54000 --slow-limit=45000

:: 6) emergency cool-down hook
ryzenadj.exe --power-saving
```

Units (verified [Options wiki](https://github.com/FlyGoat/RyzenAdj/wiki/Options)): power limits **mW**, currents **mA**, temps **°C**, times **s**. Order semantics: "Fast Limit > Slow Limit > STAPM Limit" (same wiki). `--tctl-temp`: "you need to set it 5–10 °C lower than your prochot limit" because enforcement is not fast enough (same wiki) → with Tjmax 105 °C, use **90** as the default target and never > 95.

### 4.3 What is NOT controllable from Windows on this machine

- No undervolting / Curve Optimizer from Windows on Cezanne laptops (firmware-locked; community consensus incl. the [boost-mode guide's 5800H experience](https://gist.github.com/ehsan18t/268fa28f581e512a0a0df66b95daab88)) — `UNVERIFIED` at the official-doc level, but plan the app **without** voltage control.
- No per-core frequency pinning below what `PROCTHROTTLEMAX`/`PROCFREQMAX` give.
- Fan control is EC/ACPI (Acer NitroSense territory) — out of scope for this report.

---

## 5. Administrator vs normal user

| Operation | Needs admin? | Source |
|---|---|---|
| Read perf counters (`\Processor Information`, Pdh/Perflib) | **No** | [MS Perflib sample](https://learn.microsoft.com/en-us/windows/win32/perfctrs/using-the-perflib-functions-to-consume-counter-data) |
| WMI queries (`Win32_Processor`, `MSAcpi_*`) | **No** (standard users can read `root\cimv2`, `root\wmi`) | general WMI security model (`UNVERIFIED` inline doc; validate locally) |
| `powercfg /query`, `/getactivescheme`, `/list`, `/aliases` | **No** | [powercfg docs](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/powercfg-command-line-options) (read-only options) |
| `powercfg /setacvalueindex`, `/setdcvalueindex`, `/setactive`, `/import` | **Yes** | MS PPM guide: boost mode "must be configured by the administrator" ([MS PPM tuning](https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/hardware/power/power-performance-tuning)) |
| Unhide `PERFBOOSTMODE` (HKLM `Attributes` 1→2) | **Yes** | HKLM write ([guide](https://gist.github.com/ehsan18t/268fa28f581e512a0a0df66b95daab88)) |
| psutil usage/freq/affinity read | **No** | [psutil.io/api](https://psutil.io/api/) |
| LHM temperature/power/clock sensors | **Yes** | LHM README: "Some sensors require administrator privileges" ([README](https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/README.md)) |
| ryzenadj (any SMU write or PM-table read) | **Yes** | ryzenadj README: "run it with Administrator on Windows" ([README](https://github.com/FlyGoat/RyzenAdj)) |
| Loading WinRing0x64.sys / PawnIO driver | **Yes** (driver install) + blocklist risk (§"Unsupported / risky") | [PyHardwareMonitor README](https://raw.githubusercontent.com/snip3rnick/PyHardwareMonitor/master/README.md) |

**App architecture recommendation:** run the UI unelevated; put LHM + ryzenadj behind a small elevated helper process/service (UAC prompt once at install/start). Telemetry-only degraded mode (usage + counters + WMI) must work unelevated.

---

## Python integration recipe

Versions verified against PyPI/NuGet/GitHub on **2026-10-10**:

```
pythonnet==3.2.1
psutil==7.2.2          # 8.x is in dev with breaking changes; pin <8 until migrated
py-cpuinfo==9.0.0
HardwareMonitor==1.2.1 # PyHardwareMonitor, thin pythonnet wrapper over LibreHardwareMonitorLib
LibreHardwareMonitorLib==0.9.6   # NuGet (0.9.7-pre752 is prerelease)
ryzenadj v0.19.0       # external exe + WinRing0x64.dll/.sys
```

### A. LHM via pythonnet (canonical)

```python
# requires: pip install pythonnet==3.2.1 ; NuGet LibreHardwareMonitorLib 0.9.6 dll next to app
# RUN ELEVATED (admin) for CPU temperature/power sensors
import clr
clr.AddReference("LibreHardwareMonitorLib")
from LibreHardwareMonitor.Hardware import Computer, IVisitor, IComputer, IHardware, ISensor, IParameter

class UpdateVisitor(IVisitor):
    __namespace__ = "NitroMaster.UpdateVisitor"   # must be unique per IVisitor impl
    def VisitComputer(self, computer: IComputer): computer.Traverse(self)
    def VisitHardware(self, hardware: IHardware):
        hardware.Update()
        for sh in hardware.SubHardware:
            sh.Update()
    def VisitSensor(self, sensor: ISensor): pass
    def VisitParameter(self, parameter: IParameter): pass

computer = Computer()
computer.IsCpuEnabled = True          # creates LibreHardwareMonitor.Hardware.Cpu.Amd17Cpu for our Zen 3
computer.Open()

def read_cpu():
    computer.Accept(UpdateVisitor())
    out = {}
    for hw in computer.Hardware:      # hardware type Cpu
        for s in hw.Sensors:
            out[s.Name] = s.Value     # names verified in Amd17Cpu.cs:
            # "Core (Tctl)", "Core (Tdie)", "Core (Tctl/Tdie)", "Package" (Power),
            # "Cores (Average)", "Cores (Average Effective)", "Bus Speed",
            # "Core (SVI2 TFN)", "SoC (SVI2 TFN)", "Core VIDs", CCD temps
    return out

tctl = read_cpu().get("Core (Tctl/Tdie)") or read_cpu().get("Core (Tctl)")  # °C
computer.Close()
```

(Computer/sensor iteration pattern is the README sample code: [LHM README](https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/README.md); per-sensor names from [Amd17Cpu.cs](https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/LibreHardwareMonitorLib/Hardware/Cpu/Amd17Cpu.cs). pythonnet on .NET Framework 4.7.2 build of the lib is the least-friction combo; `UNVERIFIED` which TFM pythonnet 3.2.1 binds best — test Framework 4.7.2 first.)

### B. LHM via PyHardwareMonitor (less boilerplate)

```python
# pip install HardwareMonitor==1.2.1  (pulls pythonnet + LibreHardwareMonitorLib; needs PawnIO driver + admin)
from HardwareMonitor.Hardware import Computer, IVisitor, IComputer, IHardware, ISensor, IParameter
from HardwareMonitor.Util import OpenComputer, ToBuiltinTypes, GroupSensorsByType

computer = OpenComputer(cpu=True)     # kwargs enable components
computer.Update()                     # refresh all sensors
data = ToBuiltinTypes(computer.Hardware)   # plain dicts for JSON
computer.Close()
```

(Wrapper API + admin/PawnIO notes: [PyHardwareMonitor README](https://raw.githubusercontent.com/snip3rnick/PyHardwareMonitor/master/README.md).)

### C. Usage + affinity (no admin)

```python
import psutil
total = psutil.cpu_percent(interval=None)
per_core = psutil.cpu_percent(interval=None, percpu=True)      # 12 entries on 5600H
p = psutil.Process()
aff = p.cpu_affinity()          # [0..11]
# p.cpu_affinity([0, 2, 4, 6, 8, 10])   # example pin (logical CPU ids; SMT pairing UNVERIFIED)
```

### D. Effective frequency via perf counters (no admin)

```python
# pattern: pywin32 win32pdh against "\Processor Information(_Total)\% Processor Performance"
import win32pdh
path = r"\Processor Information(_Total)\% Processor Performance"
q = win32pdh.OpenQuery()
h = win32pdh.AddCounter(q, path)
win32pdh.CollectQueryData(q)
# ...wait >= 1 s, collect again...
_, pct = win32pdh.GetFormattedCounterValue(h, win32pdh.PDH_FMT_DOUBLE)
base_mhz = 3300                      # from CPUID 0x16 / Win32_Processor.MaxClockSpeed
effective_mhz = base_mhz * pct / 100.0   # can exceed 4200 briefly? clamp to 4200 for display
```

(Counter semantics per [SO 59969778](https://stackoverflow.com/questions/59969778/how-to-get-current-cpu-clock-speed-same-as-in-task-manager), [windows_exporter #787](https://github.com/prometheus-community/windows_exporter/issues/787); fallback: shell out to `typeperf -sc 1`.)

### E. powercfg & ryzenadj from Python

```python
import subprocess, json

def set_boost(scheme: str, mode_ac: int, mode_dc: int):
    # elevated required
    subprocess.run(["powercfg", "/setacvalueindex", scheme, "sub_processor", "PERFBOOSTMODE", str(mode_ac)], check=True)
    subprocess.run(["powercfg", "/setdcvalueindex", scheme, "sub_processor", "PERFBOOSTMODE", str(mode_dc)], check=True)
    subprocess.run(["powercfg", "/setactive", scheme], check=True)   # required to apply

def ryzenadj(*args: str) -> int:      # elevated required; ship exe+WinRing0x64.dll+.sys together
    return subprocess.run(["ryzenadj.exe", *args]).returncode

# read current power metrics first (returns text; parse in-app)
subprocess.run(["ryzenadj.exe", "--info"])
```

---

## Fallback chain (best → worst)

**Temperature (Tctl):**
1. LibreHardwareMonitor `Core (Tctl/Tdie)` (admin + driver) — authoritative SMN reading.
2. HWiNFO64 shared-memory export if user has HWiNFO running (`UNVERIFIED` API details — do not block on it).
3. `MSAcpi_ThermalZoneTemperature` (WMI, no admin) — display-only, label "ACPI", sanity-check.
4. No value → show "n/a (run as admin)" — **never** fake a number; psutil is not an option (no Windows temp support).

**Clock (effective frequency):**
1. LHM per-core / `Cores (Average Effective)` sensors.
2. `\Processor Information(*)\% Processor Performance` × nominal MHz (per-core & total).
3. CPUID 0x16 base/max (static) for labels only.
4. `Win32_Processor.CurrentClockSpeed` / `psutil.cpu_freq()` — last resort, label "nominal".

**Usage:**
1. `psutil.cpu_percent(percpu=True)` (fast, no admin).
2. `\Processor Information(*)\% Processor Utility` (Task-Manager parity).
3. `\Processor(_Total)\% Processor Time` (legacy; known to disagree under boost).

**Power/boost control:**
1. `powercfg` PPM settings (PERFBOOSTMODE/PROCTHROTTLE*/CPMINMAXCORES) — always available, reversible, per-scheme.
2. ryzenadj fast/slow/tctl-temp (+ TDC/EDC) — real limits, admin + WinRing0, verify with `--dump-table`.
3. ryzenadj STT knobs if STTv2 active; `--power-saving` for emergency.
4. Nothing else without BIOS.

---

## Safety limits table (hardcode these in NitroMaster Pro)

| Parameter | Green | Warn / act | App hard cap | Rationale / source |
|---|---|---|---|---|
| Tctl (°C) | ≤ 85 | 85–90: reduce boost (PERFBOOSTMODE→1); 90–95: apply `--stapm-limit=35000 --tctl-temp=90` | 95 → force `ryzenadj --power-saving` + alert | Tjmax 105 °C ([AMD](https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-5000-series/amd-ryzen-5-5600h.html)); ryzenadj Tctl limit "not checked/enforced fast enough" → keep 5–10 °C margin ([Options wiki](https://github.com/FlyGoat/RyzenAdj/wiki/Options)) |
| Sustained limit (STAPM/slow PPT, W) | ≤ 45 | 45–54 allowed on "Performance" preset | **54** | Default TDP 45 W, cTDP 35–54 W ([AMD](https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-5000-series/amd-ryzen-5-5600h.html), [heise](https://preisvergleich.heise.de/lenovo-ideapad-5-pro-16ach6-cloud-grey-82l500tlge-a2688473.html)) |
| Fast PPT (W) | ≤ 54 | burst only | **54** (60 `UNVERIFIED` chassis headroom) | cTDP up; AN515-45 chassis thermal headroom unverified for 5600H+GTX1650 config |
| Tctl limit setting (`--tctl-temp`) | 90 | 85 quiet / 95 performance | 95 | 5–10 °C under PROCHOT/Tjmax guidance ([Options wiki](https://github.com/FlyGoat/RyzenAdj/wiki/Options)) |
| TDC (`--vrm-current`) | stock (read via `--info`) | ≤ stock | stock × 1.1 max, never blindly raise | Zen 3 OEM caps silently clamp ([Supported Models](https://github.com/FlyGoat/RyzenAdj/wiki/Supported-Models)); VRM thermal risk |
| EDC (`--vrmmax-current`) | stock | ≤ stock | stock × 1.1 max | same |
| DC `PROCTHROTTLEMAX` | 100 (AC) | 75 (DC balanced) | min 50 for "quiet" | MS example uses 75 cap ([MS PPM](https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/hardware/power/power-performance-tuning)) |
| DC `PERFBOOSTMODE` | 2 (AC) | 1 (DC) | 0 = "quiet mode" | value table [MS docs](https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/options-for-perf-state-engine-perfboostmode) |
| UI floor for any limit change | — | — | re-apply loop every 60 s or Task-Scheduler service | values get overwritten by OEM power management ([RyzenAdj README](https://github.com/FlyGoat/RyzenAdj)) |

Hard rules: always `--fast-limit ≥ --slow-limit ≥ --stapm-limit` ([Options wiki](https://github.com/FlyGoat/RyzenAdj/wiki/Options)); always snapshot `ryzenadj --info` before first write and restore those values on "reset"; verify every write with `--dump-table` because Zen 3 reports success even when clamped.

---

## Unsupported / risky

- **WinRing0x64.sys** (required by ryzenadj on Windows) is a well-known vulnerable driver; it is catalogued by [LOLDrivers](https://www.loldrivers.io/) and abused in the wild ([Trellix deep dive](https://www.trellix.com/blogs/research/technical-deep-dive-the-monero-mining-campaign/)). Windows 11 **Memory Integrity / HVCI + Microsoft vulnerable driver blocklist** can refuse to load it — in that state ryzenadj (and the WinRing0-based LHM path) simply fails. Mitigation: detect failure and fall back to `powercfg`-only mode; do **not** instruct users to disable Memory Integrity by default (safety trade-off must be explicit UI consent).
- **Zen 3 OEM value-range caps**: ryzenadj cannot raise limits above Acer's firmware caps; success exit code ≠ applied value ([Supported Models](https://github.com/FlyGoat/RyzenAdj/wiki/Supported-Models)).
- **STTv2 laptops**: `stapm-limit`/`stapm-time` are no-ops unless STTv2 is disabled; STT knobs are no-ops unless STTv2 is enabled ([Supported Models](https://github.com/FlyGoat/RyzenAdj/wiki/Supported-Models)).
- **Ryzen Master**: not usable/needed; desktop-oriented ([AMD page](https://www.amd.com/en/products/software/ryzen-master.html)); mobile non-support `UNVERIFIED` officially.
- **Undervolting / Curve Optimizer**: not available from Windows on Cezanne laptops — exclude from v1.
- **WMI thermal classes**: fake/absent on this laptop class — never drive protection logic from them (§1.4).
- **`Win32_Processor.CurrentClockSpeed`, `psutil.cpu_freq()`**: not live data on Windows (§2.2).
- **`% Parking Status` counter**: `UNVERIFIED`, feature-detect before use.
- **Fan control**: EC-side (NitroSense), out of scope here.
- psutil 8.x is in development with breaking field-order/API changes ([psutil FAQ](https://psutil.io/faq/)) — pin `<8` until explicitly migrated.

---

## Sources

1. LibreHardwareMonitor `Amd17Cpu.cs` (sensor names, `THM_TCON_CUR_TMP`, Tctl/Tdie/Tctl-Tdie, energy MSRs, Zen 3 model 0x21): https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/LibreHardwareMonitorLib/Hardware/Cpu/Amd17Cpu.cs
2. LibreHardwareMonitor `PawnIo/RyzenSmu.cs` (SMU mailbox API, `GetSmuVersion`, PM table ioctls): https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/LibreHardwareMonitorLib/PawnIo/RyzenSmu.cs
3. LHM README (NuGet, sample code, "Some sensors require administrator privileges"): https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/README.md
4. LHM repo structure (Hardware/Cpu, PawnIo): https://api.github.com/repos/LibreHardwareMonitor/LibreHardwareMonitor/contents/LibreHardwareMonitorLib/Hardware/Cpu · https://api.github.com/repos/LibreHardwareMonitor/LibreHardwareMonitor/contents/LibreHardwareMonitorLib/PawnIo
5. LibreHardwareMonitorLib NuGet versions (0.9.6 stable / 0.9.7-pre752): https://api.nuget.org/v3-flatcontainer/librehardwaremonitorlib/index.json
6. PyHardwareMonitor (pythonnet wrapper, PawnIO driver install, admin note): https://github.com/snip3rnick/PyHardwareMonitor · https://raw.githubusercontent.com/snip3rnick/PyHardwareMonitor/master/README.md
7. RyzenAdj README (usage, admin, WinRing0 dll/sys, persistence & Task Scheduler): https://github.com/FlyGoat/RyzenAdj
8. RyzenAdj Options wiki (units, STT/STAPM semantics, tctl-temp margin): https://github.com/FlyGoat/RyzenAdj/wiki/Options
9. RyzenAdj Supported Models wiki (Cezanne matrix, STTv2, Zen 3 OEM caps): https://github.com/FlyGoat/RyzenAdj/wiki/Supported-Models
10. RyzenAdj win32 contents (WinRing0x64.dll/.sys): https://api.github.com/repos/FlyGoat/RyzenAdj/contents/win32 ; release v0.19.0: https://api.github.com/repos/FlyGoat/RyzenAdj/releases/latest
11. RyzenAdj issue #145 (Cezanne STTv2 behavior): https://github.com/FlyGoat/RyzenAdj/issues/145
12. MS Learn — PERFBOOSTMODE (GUID, hidden, values): https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/options-for-perf-state-engine-perfboostmode
13. MS Learn — PERFBOOSTPOL (GUID): https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/legacy-config-options-perfboostpol
14. MS Learn — Power and performance tuning (boost table 0–4, PROCTHROTTLEMIN/MAX, PERFEPP, setactive requirement): https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/hardware/power/power-performance-tuning
15. MS Learn — powercfg command-line options (`/setacvalueindex` syntax, `/aliases`): https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/powercfg-command-line-options
16. powercfg alias→GUID list (CPMINCORES, CPMAXCORES, PERFBOOSTPOL, THROTTLING …): https://github.com/mkht/DSCR_PowerPlan/blob/master/DSCResources/cPowerPlanSetting/DATA/GUID_LIST_SETTING
17. Boost-mode registry unhide + Win11 "at Guaranteed" variants (community): https://gist.github.com/ehsan18t/268fa28f581e512a0a0df66b95daab88
18. psutil API (cpu_percent/cpu_freq quotes, affinity): https://psutil.io/api/ · sensors availability (Linux, FreeBSD) in docs source: https://raw.githubusercontent.com/giampaolo/psutil/master/docs/api.rst · platform: https://psutil.io/platform/ · FAQ (8.x breaking changes): https://psutil.io/faq/
19. py-cpuinfo fields: https://github.com/workhorsy/py-cpuinfo
20. Task-Manager-grade frequency via `% Processor Performance`: https://stackoverflow.com/questions/59969778/how-to-get-current-cpu-clock-speed-same-as-in-task-manager
21. `% Processor Time` vs `% Processor Utility` vs `processor_performance` on AMD: https://github.com/prometheus-community/windows_exporter/issues/787
22. `Win32_Processor.CurrentClockSpeed` staleness reports: https://stackoverflow.com/questions/61802420/unable-to-get-current-cpu-frequency-in-powershell-or-python · https://stackoverflow.com/questions/51332103/c-how-to-find-the-cpus-current-clock-speed · https://serverfault.com/questions/121669/difference-between-currentclockspeed-and-maxclockspeed
23. MSAcpi_ThermalZoneTemperature unreliable: https://stackoverflow.com/questions/9101295/msacpi-thermalzonetemperature-class-not-showing-actual-temperature · https://github.com/lablup/all-smi · https://learn.microsoft.com/en-us/answers/questions/3759165/kernel-power-event-41-63-caused-by-erroneous-windo
24. Perflib counter consumption example ("Processor Information"): https://learn.microsoft.com/en-us/windows/win32/perfctrs/using-the-perflib-functions-to-consume-counter-data
25. AMD Ryzen 5 5600H specs (3.3/4.2 GHz, 45 W TDP, Tjmax 105 °C): https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-5000-series/amd-ryzen-5-5600h.html
26. 5600H cTDP 35–54 W (retailer spec listing): https://preisvergleich.heise.de/lenovo-ideapad-5-pro-16ach6-cloud-grey-82l500tlge-a2688473.html
27. AMD Ryzen Master (desktop overclocking utility): https://www.amd.com/en/products/software/ryzen-master.html
28. CPUID leaves 0x15/0x16: https://www.felixcloutier.com/x86/cpuid · https://en.wikipedia.org/wiki/CPUID
29. WinRing0 vulnerability context: https://www.loldrivers.io/ · https://www.trellix.com/blogs/research/technical-deep-dive-the-monero-mining-campaign/
30. k10temp temperature offset table (referenced by LHM code): https://github.com/torvalds/linux/blob/master/drivers/hwmon/k10temp.c
31. Library versions queried 2026-10-10 via PyPI/GitHub/NuGet APIs: pythonnet 3.2.1, psutil 7.2.2, py-cpuinfo 9.0.0, wmi 1.5.1, HardwareMonitor 1.2.1, ryzenadj v0.19.0.
