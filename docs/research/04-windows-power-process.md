# Research 04 — Windows 11 Power, Process & Service APIs

**Scope:** OS-level APIs for NitroMaster Pro Control Center (Python 3.11 + PyQt6, Acer Nitro AN515-45, Windows 11 x64).
Everything below was verified against Microsoft Learn / Windows SDK headers / cited community sources on 2026-10-10. Unverifiable claims are explicitly marked `UNVERIFIED`.

## Executive summary

1. Power-plan manipulation is the backbone of the Mode system: `powercfg` covers list/duplicate/activate/delete/export/import/per-setting values; the same work can be done in-process through `powrprof.dll` (`PowerGetActiveScheme`, `PowerWriteACValueIndex`, `PowerSetActiveScheme`). **Recommendation: ctypes `powrprof.dll` for hot-path writes, `powercfg` subprocess for query/export/attributes/diagnostics** [S1][S2][S3][S4][S5].
2. All setting GUIDs needed for the Mode matrix are verified (SUB_PROCESSOR `54533251-…`, SUB_VIDEO `7516b95f-…`, SUB_SLEEP `238c9fa8-…`, SUB_PCIEXPRESS `501a4d13-…`, SUB_WIRELESS `19cbb8fa-…`, plus per-setting GUIDs) [S7][S8][S9][S12][S14][S15].
3. **Correction to the brief:** `SCHEME_MAX` alias = *Power saver* (`a1841308-…`), `SCHEME_MIN` alias = *High performance* (`8c5e7fda-…`), and `8c5e7fda-…` is **not** Ultimate Performance. Ultimate Performance = `e9a42b02-d5df-448d-aa00-03f14749eb61` [S2][S7][S38]. Use GUIDs in code, never the aliases' direction-of-naming.
4. Plan writes require an elevated process; reads do not [S2]. Ship `asInvoker` manifest + in-app "Relaunch as admin" via `ShellExecuteW(…, "runas", …)` [S34][S35].
5. Modern Standby (S0ix) replaces classic S3 on supported machines: `powercfg /a` shows "Standby (S0 Low Power Idle) Network Connected/Disconnected" and S1–S3 as *not available*. Sleep timeouts then drive S0ix entry, away-mode requests are S3-only, and on DC power system/execution power requests are killed 5 minutes after the sleep timeout [S17][S19][S40].
6. For "Ultra Battery Saver" prefer **EcoQoS throttling** (`SetProcessInformation(ProcessPowerThrottling, …)`, `PROCESS_POWER_THROTTLING_EXECUTION_SPEED`) + priority/affinity + service stop, and only use `NtSuspendProcess`/`NtResumeProcess` (ntdll, undocumented) for selected user apps [S20][S21][S22][S28].
7. Service control: `sc.exe` (`config/query/qc/stop`) or pywin32 `win32service` (`QueryServiceConfigW`, `ChangeServiceConfigW`, `ControlService`) — always snapshot `dwStartType` first and restore afterwards; never touch RPCSS/DcomLaunch/LSM/Winmgmt/Power/AudioSrv and friends [S29][S30][S31][S32][S37].
8. Brightness for the laptop panel: WMI `root\wmi` → `WmiMonitorBrightnessMethods.WmiSetBrightness(Timeout, Brightness%)`; `dxva2!SetMonitorBrightness` is for external MCCS monitors only and Microsoft warns against it for arbitrary displays [S41][S42][S43].
9. Per-app GPU preference lives in `HKCU\SOFTWARE\Microsoft\DirectX\UserGpuPreferences`, value name = absolute exe path, data `GpuPreference=0|1|2;` (decide / power-saving / high-performance) [S44].

---

## 1. Power plans — the backbone of the Mode system

### 1.1 `powercfg` relevant surface

Source: official switch list [S1], practical notes/alias list [S2].

| Switch | Syntax | Notes |
|---|---|---|
| `/list`, `/L` | `powercfg /list` | Lists schemes with GUID and active marker `*` [S1] |
| `/query`, `/Q` | `powercfg /query [scheme_GUID] [sub_GUID]` | Dumps settings incl. current AC/DC indices; no args = active scheme [S1] |
| `/QH` (undoc.) | `powercfg /qh [scheme] [sub] > file` | Includes **hidden** settings; >1500 lines — always redirect [S2] |
| `/getactivescheme` | `powercfg /getactivescheme` | Prints active scheme GUID [S1] |
| `/setactive`, `/S` | `powercfg /setactive scheme_GUID` | Activate a scheme [S1] |
| `/duplicatescheme` | `powercfg /duplicatescheme scheme_GUID [dest_GUID]` | Returns new GUID; this is how the app creates its per-mode plans [S1] |
| `/changename` | `powercfg /changename scheme_GUID "Name" ["desc"]` | Rename plan [S1] |
| `/delete`, `/D` | `powercfg /delete scheme_GUID` | Delete plan (built-ins cannot be deleted) [S1] |
| `/setacvalueindex` | `powercfg /setacvalueindex scheme sub setting index` | Per-setting AC value [S1] |
| `/setdcvalueindex` | `powercfg /setdcvalueindex scheme sub setting index` | Per-setting DC value [S1] |
| `/change`, `/X` | `powercfg /change monitor-timeout-ac 5` | Shorthand for monitor/disk/standby/hibernate timeouts (minutes; 0 = Never) [S1][S2] |
| `/deletesetting` | `powercfg /deletesetting sub setting` | Removes a setting from a scheme [S1] |
| `/attributes` | `powercfg /attributes SUB_GUID setting_GUID [+|-]ATTRIB_HIDE` | Hide/unhide a setting in the Power Options UI. Not in the MS switch table; verified from Microsoft Q&A usage `powercfg -attributes SUB_PROCESSOR 7b224883-… -ATTRIB_HIDE` [S39] and from the registry mechanism (`Attributes` DWORD, `2` = visible) [S37] |
| `/aliases`, `/aliasesH` | `powercfg /aliases` | Alias→GUID map; `/aliasesH` includes hidden aliases incl. `SCHEME_CURRENT` [S2] |
| `/import` | `powercfg /import file.pow [GUID]` | Restores a scheme; optional fixed GUID [S1] |
| `/export` | `powercfg /export file.pow GUID` | Binary snapshot of one scheme [S1] |
| `/hibernate` | `powercfg /hibernate [on|off|/size %|/type reduced\|full]` | Hibernate & hiberfile management [S1] |
| `/availablesleepstates`, `/A` | `powercfg /a` | Lists available/unavailable sleep states + reasons — **Modern Standby detection** [S1] |
| `/requests`, `/requestsoverride` | `powercfg /requests`, `powercfg /requestsoverride process foo.exe display system` | Power requests blocking sleep/display-off; overrides per process/service/driver [S1] |
| `/waketimers`, `/lastwake`, `/devicequery`, `/deviceenableawake`, `/devicedisablewake` | | Wake sources; useful diagnostics for "didn't sleep" bugs [S1] |
| `/energy`, `/batteryreport`, `/sleepstudy`, `/systempowerreport`, `/systemsleepdiagnostics` | | Diagnostic reports (some require elevation) [S1][S2] |
| `/restoredefaultschemes` (undoc.) | | **Do not use** — reported to wipe settings instead of restoring, esp. with Modern Standby [S2] |

- **Elevation:** "To make changes to power settings, Powercfg must be run from an elevated command prompt" [S2]. Reads (`/list`, `/q`, `/a`, …) work without elevation.
- **Exit codes:** `powercfg` writes fail with nonzero exit and a stderr message (typically `Access is denied` / `The GUID passed was not recognized…`); wrap in `subprocess.run(..., capture_output=True)` and check `returncode` [S1].

### 1.2 Verified GUIDs

Scheme GUIDs (SDK `winnt.h` constants [S7]; alias map from real `powercfg /aliases` output [S2]):

| Plan | GUID | SDK constant | powercfg alias |
|---|---|---|---|
| Power saver | `a1841308-3541-4fab-bc81-f71556f20b4a` | `GUID_MAX_POWER_SAVINGS` | `SCHEME_MAX` ("max power saving") [S2][S7] |
| Balanced | `381b4222-f694-41f0-9685-ff5bb260df2e` | `GUID_TYPICAL_POWER_SAVINGS` | `SCHEME_BALANCED` [S2][S7] |
| High performance | `8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c` | `GUID_MIN_POWER_SAVINGS` | `SCHEME_MIN` ("min power saving") [S2][S7] |
| Ultimate performance | `e9a42b02-d5df-448d-aa00-03f14749eb61` | (hidden; created via `powercfg /duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61`) | — [S38] |
| (any) current scheme | — | — | `SCHEME_CURRENT` (via `/aliasesH`) [S2] |

> ⚠️ **Naming trap (verified):** `SCHEME_MAX` is *Power saver* and `SCHEME_MIN` is *High performance* — the alias names refer to **power saving**, not performance [S2]. The research brief stated the opposite and mislabeled `8c5e7fda-…` as Ultimate Performance; both are corrected above. **Code must use GUIDs.**

Subgroup GUIDs (all from SDK `winnt.h` [S7], cross-checked against MS docs parameter tables [S4]):

| Subgroup | Alias | GUID |
|---|---|---|
| Processor power management | `SUB_PROCESSOR` | `54533251-82be-4824-96c1-47b60b740d00` (`GUID_PROCESSOR_SETTINGS_SUBGROUP`) [S4][S7] |
| Display / video | `SUB_VIDEO` | `7516b95f-f776-4464-8c53-06167f40cc99` (`GUID_VIDEO_SUBGROUP`) [S4][S7] |
| Sleep | `SUB_SLEEP` | `238c9fa8-0aad-41ed-83f4-97be242c8f20` (`GUID_SLEEP_SUBGROUP`) [S4][S7] |
| PCI Express (ASPM) | `SUB_PCIEXPRESS` | `501a4d13-42af-4429-9fd1-a8218c268e20` (`GUID_PCIEXPRESS_SETTINGS_SUBGROUP`) [S4][S7] |
| Wireless adapter settings | `SUB_WIRELESS` | `19cbb8fa-5279-450e-9fac-8a3d5fedd0c1` (community-verified; not in `winnt.h`) [S45] |
| Hard disk | `SUB_DISK` | `0012ee47-9041-4b5d-9b77-535fba8b1442` (`GUID_DISK_SUBGROUP`) [S4][S7] |
| Buttons / lid | `SUB_BUTTONS` | `4f971e89-eebd-4455-a8de-9e59040e7347` (`GUID_SYSTEM_BUTTON_SUBGROUP`) [S4][S7] |
| Battery | `SUB_BATTERY` | `e73a048d-bf27-4f12-9731-8b2076e8891f` (`GUID_BATTERY_SUBGROUP`) [S4][S7] |
| Default (no subgroup) | `SUB_NONE` | `fea3413e-7e05-4911-9a71-700331f1c294` (`NO_SUBGROUP_GUID`) [S4][S7] |

Per-setting GUIDs (SDK `winnt.h` [S7] unless noted):

**SUB_PROCESSOR (`54533251-…`)**

| powercfg alias | Setting | GUID | Values |
|---|---|---|---|
| `PERFBOOSTMODE` | Processor performance boost mode | `be337238-0d82-4146-a960-4f3749d470c7` (`GUID_PROCESSOR_PERF_BOOST_MODE`) | 0 Disabled, 1 Enabled, 2 Aggressive, 3 = 1, 4 = 2 (hidden) [S8] |
| `PERFBOOSTPOL` | Processor performance boost policy | `45bcc044-d885-43e2-8605-ee0ec6e96b59` (`GUID_PROCESSOR_PERF_BOOST_POLICY`) | 0–100 (%) (hidden) [S9] |
| `PROCTHROTTLEMAX` | Maximum processor state | `bc5038f7-23e0-4960-96da-33abaf5935ec` (`GUID_PROCESSOR_THROTTLE_MAXIMUM`) | 0–100 (%) [S10][S7][S46] |
| `PROCTHROTTLEMIN` | Minimum processor state | `893dee8e-2bef-41e0-89c6-b55d0929964c` (`GUID_PROCESSOR_THROTTLE_MINIMUM`) | 0–100 (%) [S11][S7] |
| `PERFTHROTTLING` | **UNVERIFIED alias.** Throttling-related processor settings in the SDK are `GUID_PROCESSOR_ALLOW_THROTTLING` = `3b04d4fd-1cc7-4f23-ab1c-d1337819c4bb` and `GUID_PROCESSOR_THROTTLE_POLICY` = `57027304-4af6-4104-9260-e3d95248fc36`; no Microsoft or community source maps the name `PERFTHROTTLING` to either. Resolve at runtime via `powercfg /aliases` or `powercfg /qh` and fail soft. | `3b04d4fd-…` / `57027304-…` [S7] | 0/1 style flags (UNVERIFIED) |
| (extra, useful) `IDLEDISABLE` | Processor idle disable | `5d76a2ca-e8c0-402f-a1a3-2158492d58ad` (`GUID_PROCESSOR_IDLE_DISABLE`) | 0 = idle enabled, 1 = idle disabled [S7] |

> Note on `IDLEDISABLE`: SS64 shows the alias usage `powercfg /SetacValueIndex SCHEME_CURRENT sub_processor IDLEDISABLE 0` and warns that a stray `1` pins the CPU at 100% (a known misconfiguration) [S2]; the GUID is from `winnt.h` [S7].

**SUB_VIDEO (`7516b95f-…`)**

| Setting | GUID (SDK name) | Use |
|---|---|---|
| Turn off display after | `3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e` (`GUID_VIDEO_POWERDOWN_TIMEOUT`) | display timeout, seconds (0 = Never) [S7] |
| Dim display after | `17aaa29b-8b43-4b94-aafe-35f64daaf1ee` (`GUID_VIDEO_DIM_TIMEOUT`) | dim timeout, seconds [S7] |
| Display brightness (level) | `aded5e82-b909-4619-9949-f5d71dac0bcb` (`GUID_DEVICE_POWER_POLICY_VIDEO_BRIGHTNESS`) | per-AC/DC brightness %, hidden [S7] |
| Dim brightness level | `f1fbfde2-a960-4165-9f88-50667911ce96` (`GUID_DEVICE_POWER_POLICY_VIDEO_DIM_BRIGHTNESS`) | dimmed %, hidden [S7] |
| Adaptive brightness | `fbd9aa66-9553-4097-ba44-ed6e9d65eab8` (`GUID_VIDEO_ADAPTIVE_DISPLAY_BRIGHTNESS`) | 0/1 (ALS-based) [S7] |
| Console lock timeout | `8ec4b3a5-6868-48c2-be75-4f3044be88a7` (`GUID_VIDEO_CONSOLE_LOCK_TIMEOUT`) | seconds, hidden [S7] |

**SUB_SLEEP (`238c9fa8-…`)**

| powercfg alias | Setting | GUID | Values |
|---|---|---|---|
| `STANDBYIDLE` | Sleep after (standby idle timeout) | `29f6c1db-86da-48c5-9fdb-f2b67b1f44da` (`GUID_STANDBY_TIMEOUT`) | seconds; 0 = Never [S12][S7][S2] |
| `HIBERNATEIDLE` | Hibernate after | `9d7815a6-7ee4-497e-8888-515a05f02364` (`GUID_HIBERNATE_TIMEOUT`) | seconds; 0 = hibernate at adaptive threshold. "This setting enables the hibernate option on Modern Standby systems" [S13][S7] |
| `HYBRIDSLEEP` | Allow hybrid sleep | `94ac6d29-73ce-41a6-809f-6363ba21b47e` (`GUID_HIBERNATE_FASTS4_POLICY`) | 0 Disabled / 1 Enabled [S14][S7] |
| — | Unattended sleep timeout | `7bc4a2f9-d8fc-4469-b07b-33eb785aaca0` (`GUID_UNATTEND_SLEEP_TIMEOUT`) | seconds, hidden [S7] |

**SUB_PCIEXPRESS (`501a4d13-…`)**

| powercfg alias | Setting | GUID | Values |
|---|---|---|---|
| `ASPM` | Link state power management | `ee12f906-d277-404b-b6da-e5fa1a576df5` (`GUID_PCIEXPRESS_ASPM_POLICY`) | 0 = None, 1 = Moderate power savings (L0s/L1), 2 = Maximum power savings (L1) — hidden [S15][S7] |

**SUB_WIRELESS (`19cbb8fa-…`)**

| Setting | GUID | Values |
|---|---|---|
| Power Saving Mode | **UNVERIFIED** (setting GUID not published by MS; the subgroup GUID itself is community-verified [S45]). Discover at runtime: enumerate `HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerSettings\19cbb8fa-5279-450e-9fac-8a3d5fedd0c1\<setting>` or use `powercfg /qh` [S2][S37] | UI offers Maximum Performance / Low / Medium / Maximum Power Saving → indices 0–3 in UI order (UNVERIFIED mapping; read index list from `powercfg /q` on the target machine) |

Also useful: `GUID_SYSTEM_COOLING_POLICY` = `94d3a615-a899-4ac5-ae2b-e4d8f634367f` (System cooling policy, `SUB_PROCESSOR`, 0 = Active, 1 = Passive) [S7].

### 1.3 Hidden settings

- Many Mode-critical settings (`PERFBOOSTMODE`, `PERFBOOSTPOL`, `STANDBYIDLE`, `HYBRIDSLEEP`, `ASPM`, …) are flagged **Hidden setting: Yes** in Microsoft's own pages [S8][S9][S12][S14][S15]. Hidden status only affects the Control Panel UI — `powercfg /setacvalueindex` and `PowerWriteACValueIndex` work regardless.
- Unhide for UI debugging: `powercfg -attributes SUB_PROCESSOR be337238-0d82-4146-a960-4f3749d470c7 -ATTRIB_HIDE` [S39]; equivalently set `HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerSettings\<sub>\<setting>\Attributes` = `2` (visible) [S37].
- Bulk-unhide script pattern (elevated PowerShell) iterates the whole `PowerSettings` hive [S37].

### 1.4 Modern Standby (S0ix) — what it changes on this laptop

- Modern Standby uses the **S0 low-power idle model** instead of classic S3; the system stays network-connected in low power and wakes instantly; software must be "quiesced" and runs in short controlled bursts; activators can block idle entry [S17].
- **Detection:** `powercfg /a` [S1]. On an S0ix machine the output lists:
  ```
  The following sleep states are available on this system:
      Standby (S0 Low Power Idle) Network Connected
      Standby (S0 Low Power Idle) Network Disconnected
      Hibernate
      Fast Startup
  The following sleep states are not available on this system:
      Standby (S1)
          The system firmware does not support this standby state.
      Standby (S3)
          The system firmware does not support this standby state.
  ```
  (Output shape verified from real-world `powercfg /a` dumps on Modern Standby laptops [S40].)
- **Consequences for the app:**
  - "Sleep after" (`STANDBYIDLE`) enters S0ix, not S3. Battery drain during "sleep" is possible if background tasks/activators run; keep Ultra Battery Saver's service/telemetry stops especially relevant [S17].
  - `PowerRequestAwayModeRequired` is **only applicable on Traditional Sleep (S3) systems** — do not rely on away mode on S0ix machines [S19].
  - On Modern Standby + DC, system/execution power requests are terminated 5 minutes after the sleep timeout expires [S19].
  - `HIBERNATEIDLE` is what exposes/configures hibernate on Modern Standby systems [S13].
  - Only the Ultimate/High-Performance style plans may be hidden on S0ix systems; SS64 notes plan availability quirks with Modern Standby [S2].
- **AN515-45 specific:** whether this exact SKU/BIOS exposes S0ix or S3 is `UNVERIFIED` here (Acer gaming laptops vary by BIOS; Acer community threads show both S0ix-only and S3 machines [S40b]). The app **must** branch on `powercfg /a` output at runtime, not on assumptions. Toggling `HKLM\SYSTEM\CurrentControlSet\Control\Power\CSEnabled` = 0 "disables Connected Standby" [S37] — treat as **risky/unsupported** (requires firmware S3; not an OS-supported switch [S17]).

### 1.5 `powercfg` subprocess vs Win32 `Power*` APIs — recommendation

**Use a hybrid:**

| Task | Use | Why |
|---|---|---|
| Get/set active scheme; read/write AC/DC value indices (hot path of Mode switching) | `powrprof.dll` via ctypes | No console flash, no process spawn, structured Win32 error codes [S3][S4][S5] |
| Full text dump (`/q`, `/qh`), hidden-setting discovery | `powercfg` subprocess | No API equivalent for the human-readable dump [S1][S2] |
| Baseline snapshot/restore (`.pow`) | `powercfg /export` `/import` | No documented API for `.pow` serialization [S1] |
| `/attributes`, `/aliases`, `/a`, `/requests`, `/energy`, `/batteryreport` | `powercfg` subprocess | Only exists as CLI [S1][S2][S39] |
| Duplicate/delete scheme without spawning | `PowerDuplicateScheme` / `PowerDeleteScheme` / `PowerEnumerate` (powrprof) | Available if preferred [S6][S47][S48][S49] |

**Exact signatures (powrprof.dll, `powersetting.h`/`powrprof.h`):**

```cpp
// [S3]
DWORD PowerGetActiveScheme([in, optional] HKEY UserRootPowerKey /* NULL */,
                           [out] GUID **ActivePolicyGuid);
// returned GUID must be freed with LocalFree(); returns ERROR_SUCCESS (0) or Win32 error.

// [S4]  (RootPowerKey must be NULL; SubGroup/Setting may be NO_SUBGROUP_GUID / NULL)
DWORD PowerWriteACValueIndex([in, optional] HKEY RootPowerKey,
                             [in] const GUID *SchemeGuid,
                             [in, optional] const GUID *SubGroupOfPowerSettingsGuid,
                             [in, optional] const GUID *PowerSettingGuid,
                             [in] DWORD AcValueIndex);
// Mirror: PowerWriteDCValueIndex(... DcValueIndex).
// IMPORTANT: "Changes to the settings for the active power scheme do not take effect
// until you call the PowerSetActiveScheme function." [S4]

// [S5]
DWORD PowerSetActiveScheme([in, optional] HKEY UserRootPowerKey /* NULL */,
                           [in] const GUID *SchemeGuid);

// Read current index (powrprof): PowerReadACValueIndex/PowerReadDCValueIndex [S47]
DWORD PowerReadACValueIndex(HKEY RootPowerKey, const GUID *SchemeGuid,
                            const GUID *SubGroupOfPowerSettingsGuid,
                            const GUID *PowerSettingGuid, LPDWORD AcValueIndex /*, …*/);
```

**Error handling:** every `Power*` function returns a Win32 error code as `DWORD` (`ERROR_SUCCESS` = 0) [S3][S4][S5]. In ctypes: `rc = fn(...); if rc != 0: raise ctypes.WinError(rc)`. Expect `ERROR_ACCESS_DENIED` (5) for value writes / plan creation when not elevated (powercfg's CLI writes demand elevation [S2]; scheme data lives under `HKLM\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes` [S2]). `PowerGetActiveScheme` output must be released with `LocalFree` [S3].

### 1.6 Snapshot & baseline restore (per-mode rollback)

1. **Binary snapshot (preferred):** `powercfg /export C:\...\baseline-<guid>.pow <scheme_GUID>` [S1]; restore with `powercfg /import C:\...\baseline-<guid>.pow <same_GUID>` then `powercfg /setactive <GUID>` [S1]. Importing with an explicit GUID restores *in place*; without GUID a new GUID is created [S1].
2. **Text snapshot:** `powercfg /qh <scheme_GUID> > baseline.txt` (includes hidden settings) [S2]; parse `GUID:\n  Alias:\n  Setting: … \n Current AC Power Setting Index: 0x…` blocks to diff/restore individual indices via `/setacvalueindex`.
3. **Whole-machine reference:** keep one untouched duplicate of Balanced created at first run (`powercfg /duplicatescheme 381b4222-… <fixed GUID>`) — the app's "baseline restore" target [S1].
4. Do **not** use `powercfg /restoredefaultschemes` (undocumented, reported destructive) [S2].

---

## 2. Background process/service suspension & single-app-focus (Ultra Battery Saver)

### 2.1 Suspending/resuming processes — `NtSuspendProcess` / `NtResumeProcess`

- These are **ntdll exports, undocumented** (widely used; psutil's Windows backend calls exactly these) [S28].
- Signature (from psutil's ntdll typedefs, i.e. real-world usage) [S28]:
  ```c
  typedef NTSTATUS (WINAPI *NtSuspendProcess)(HANDLE hProcess);  // ntdll.dll
  typedef NTSTATUS (WINAPI *NtResumeProcess)(HANDLE hProcess);   // ntdll.dll
  ```
  Return `NTSTATUS` (`>= 0` success, `NT_SUCCESS(status)`).
- Access needed: `OpenProcess(PROCESS_SUSPEND_RESUME (0x0800) | PROCESS_QUERY_LIMITED_INFORMATION, …)` — psutil opens with exactly `PROCESS_SUSPEND_RESUME | PROCESS_QUERY_LIMITED_INFORMATION` [S28]; `PROCESS_SUSPEND_RESUME` = `0x0800` per SDK headers [S26][S7].
- **Privileges:** opening another user's/system processes requires appropriate DACL access; `SeDebugPrivilege` (`SE_DEBUG_NAME` = `"SeDebugPrivilege"`) lets you open practically any process — documented in the Debug context ("If the debugging process has the SE_DEBUG_NAME privilege granted and enabled, it can debug any process") [S25][S27]. Enabling it needs an elevated token + `LookupPrivilegeValue` + `AdjustTokenPrivileges` [S27]. So: same-user apps suspend fine non-elevated; system/protected processes need admin + `SeDebugPrivilege` (and protected processes/PPL remain off-limits).
- **Caveats:** never suspend service-hosting processes (SCM watchdog / `ERROR_TIMEOUT`, service marked unresponsive), never suspend the process holding a lock your UI needs; suspended apps still hold memory; Modern Standby quiescing dislikes long-stalled processes. Prefer EcoQoS (§2.7) and only suspend explicitly selected user apps (games/launchers) as part of "single-app focus".

### 2.2 `DebugActiveProcess` trick (attach = freeze)

- `DebugActiveProcess(dwProcessId)` attaches as debugger and "the system suspends all threads in the process" until debug events are continued [S25].
- Requires `PROCESS_ALL_ACCESS`; `SE_DEBUG_NAME` grants it to any process [S25]. Must call `DebugSetProcessKillOnExit(FALSE)` and `DebugActiveProcessStop` to detach without killing the target [S25].
- **Recommendation: don't ship this.** Only one debugger may attach; AV/EDR flags debugger attach; a crashed app instance leaves the target frozen. Documented here for completeness.

### 2.3 psutil equivalents (Python)

| psutil API | Win32 implementation | Notes |
|---|---|---|
| `p.suspend()` / `p.resume()` | `NtSuspendProcess` / `NtResumeProcess` (verified in psutil source) [S28] | Exactly §2.1 semantics |
| `p.nice(psutil.IDLE_PRIORITY_CLASS)` etc. | `SetPriorityClass` (verified in psutil source) [S28] | Constants exported by psutil: `IDLE/BELOW_NORMAL/NORMAL/ABOVE_NORMAL/…_PRIORITY_CLASS` [S28] |
| `p.cpu_affinity([...])` | `SetProcessAffinityMask` (verified in psutil source) [S28] | Core-parking substitute for limiting a process to efficiency cores |
| `p.ionice(...)` | Windows: mapped to priority class (no separate I/O QoS) | psutil docs: `psutil.IOPRIO_CLASS_*` degrade to priority classes on Windows — see psutil docs [S36] |
| `p.terminate()` / `p.kill()` | `TerminateProcess` | Last resort only |

### 2.4 `PssCaptureSnapshot`

```cpp
DWORD PssCaptureSnapshot([in] HANDLE ProcessHandle,
                         [in] PSS_CAPTURE_FLAGS CaptureFlags,
                         [in, optional] DWORD ThreadContextFlags,
                         [out] HPSS *SnapshotHandle);   // kernel32.dll, Win 8.1+ [S24]
```
It captures a *snapshot* (incl. `PSS_CAPTURE_VA_CLONE` working-set clone) — it is a memory/telemetry tool (e.g., for measuring a suspended app's footprint), **not** a suspend mechanism [S24]. Use for the Ultra Battery Saver "reclaim" diagnostics if needed; otherwise skip.

### 2.5 Stopping/disabling services

**sc.exe** [S32][S33]:
```
sc  query  <name>                 :: state
sc  qc     <name>                 :: config incl. START_TYPE (snapshot!)
sc  config <name> start= disabled :: or demand | auto | delayed-auto
sc  stop   <name>                 :: then wait until STATE=STOPPED
sc  start  <name>
```
`sc config` supports `start= {boot|system|auto|demand|disabled|delayed-auto}`, `error= …`, `depend= …` etc. [S32]; `sc query` enumerates with `state= {active|inactive|all}` [S33].

**pywin32 `win32service`** (same SCM APIs):
```python
# Signatures from winsvc.h docs:
ChangeServiceConfigW(hService, dwServiceType, dwStartType, dwErrorControl,
                     lpBinaryPathName, lpLoadOrderGroup, lpdwTagId, lpDependencies,
                     lpServiceStartName, lpPassword, lpDisplayName)   # [S29]
ControlService(hService, dwControl /* SERVICE_CONTROL_STOP=1, PAUSE=2, CONTINUE=3 */,
               LPSERVICE_STATUS)                                      # [S30]
QueryServiceConfigW(hService, LPQUERY_SERVICE_CONFIG, cbBufSize, pcbBytesNeeded)  # [S31]
```
`dwStartType` values: `SERVICE_BOOT_START=0, SERVICE_SYSTEM_START=1, SERVICE_AUTO_START=2, SERVICE_DEMAND_START=3, SERVICE_DISABLED=4`, and `SERVICE_NO_CHANGE` to leave fields untouched [S29]. Handles need `SERVICE_CHANGE_CONFIG` for config, `SERVICE_STOP` for stop [S29][S30], `SERVICE_QUERY_CONFIG` for query [S31]. For optional config (delayed-auto start, description, triggers) use `ChangeServiceConfig2`/`QueryServiceConfig2` [S50][S51]; trigger-started services can restart despite `demand` start type — check `sc qtriggerinfo` semantics (service trigger events) [S52].

**Snapshot & restore recipe (mandatory before any service change):**
1. For each target service record `sc qc <name>` (START_TYPE, DEPENDENCIES, SERVICE_START_NAME) or `QueryServiceConfigW` fields [S29][S31]; store JSON in the app's profile dir.
2. For "stop now, restore later": `ControlService(SERVICE_CONTROL_STOP)` only; do **not** change start type unless the user picks "disable" explicitly [S30].
3. Restore: `ChangeServiceConfigW(..., dwStartType=snapshot.START_TYPE, SERVICE_NO_CHANGE…)` + `StartService` if it was running [S29].
4. Per-service-user (`CDPUserSvc_*`, `OneSyncSvc_*`) must be disabled via registry `HKLM\SYSTEM\CurrentControlSet\Services\<name>\Start = 4` because they are per-user instances [S37].

### 2.6 Timer resolution & execution state

```c
MMRESULT timeBeginPeriod(UINT uPeriod);   // Winmm.dll [S23]
MMRESULT timeEndPeriod(UINT uPeriod);
```
- Must pair every `timeBeginPeriod` with `timeEndPeriod` [S23].
- **Win10 2004+:** resolution requests are **per-process** (no longer global) [S23].
- **Win11:** if the process's window is fully occluded/minimized/inaudible, Windows does not honor higher resolution [S23][S20]. High resolution prevents CPU power-saving entry — so *lowering* (or ignoring) timer resolution is itself a battery-saver lever (`PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION`, §2.7).

```c
EXECUTION_STATE SetThreadExecutionState(EXECUTION_STATE esFlags);  // Kernel32 [S18]
// ES_SYSTEM_REQUIRED 0x1, ES_DISPLAY_REQUIRED 0x2, ES_CONTINUOUS 0x80000000,
// ES_AWAYMODE_REQUIRED 0x40 (S3 only), ES_USER_PRESENT 0x4 (unsupported — do not use) [S18]
```
Use `ES_CONTINUOUS | ES_SYSTEM_REQUIRED` only while the app legitimately must keep the machine awake (e.g., an active fan/BIOS write); clear with `SetThreadExecutionState(ES_CONTINUOUS)` [S18].

```c
BOOL PowerSetRequest(HANDLE PowerRequest, POWER_REQUEST_TYPE RequestType);   // [S19]
BOOL PowerClearRequest(HANDLE PowerRequest, POWER_REQUEST_TYPE RequestType); // [S53]
// PowerRequestDisplayRequired / SystemRequired / AwayModeRequired (S3-only) / ExecutionRequired [S19]
```
On Modern Standby + DC, system & execution requests are dropped 5 minutes after the sleep timeout [S19]; user-initiated sleep clears requests (except away mode on S3) [S19]. The CLI surface for auditing is `powercfg /requests` / `/requestsoverride` [S1].

### 2.7 Power throttling (the modern, safe "background throttling")

EcoQoS — exactly what Task Manager's "Efficiency mode" does [S20][S22]:

```cpp
BOOL SetProcessInformation(HANDLE hProcess, PROCESS_INFORMATION_CLASS ProcessInformationClass,
                           LPVOID ProcessInformation, DWORD ProcessInformationSize);  // [S20]

// ProcessInformationClass = ProcessPowerThrottling (value in PROCESS_INFORMATION_CLASS) [S54]
typedef struct _PROCESS_POWER_THROTTLING_STATE {
  ULONG Version;       // PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
  ULONG ControlMask;   // PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
  ULONG StateMask;     // 0x1 = enable EcoQoS throttling, 0 = disable (HighQoS)
} PROCESS_POWER_THROTTLING_STATE;                       // [S21][S54]
// PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4 — ignores timer-res requests [S20][S54]
```
- Opting into `PROCESS_POWER_THROTTLING_EXECUTION_SPEED` classifies the process as **EcoQoS**: Windows reduces CPU frequency and prefers efficiency cores; Win11 introduced the Eco level (previously "LowQoS") [S20][S22].
- Opting into `PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION` makes the process's timer-resolution requests be ignored → measurable power win for background apps [S20].
- Per-thread variant: `SetThreadInformation(..., ThreadPowerThrottling, THREAD_POWER_THROTTLING_STATE)` with `THREAD_POWER_THROTTLING_EXECUTION_SPEED = 0x1` [S22][S54].
- Handle rights: `PROCESS_SET_INFORMATION` (`0x0200`) [S20][S7].
- **Ultra Battery Saver recommendation:** for every non-focused app: EcoQoS on + `IGNORE_TIMER_RESOLUTION` + `IDLE_PRIORITY_CLASS` + optional affinity to efficiency cores (psutil) + service stops; escalate to `NtSuspendProcess` only for a user-picked allowlist. This is reversible, low-risk and OS-sanctioned [S20][S22].

### 2.8 Display brightness (battery mode)

**Primary — WMI (works for the laptop panel, per-monitor instance in `root\wmi`)** [S41][S42]:
```python
# class WmiMonitorBrightnessMethods { boolean Active; string InstanceName; }  [S41]
# uint32 WmiSetBrightness(uint32 Timeout /*seconds*/, uint8 Brightness /*percent*/)  [S42]
```
PowerShell reference implementation from Microsoft: `Get-WmiObject -Namespace root\wmi -Class WmiMonitorBrightnessMethods | % { $_.WmiSetBrightness(5, 50) }` [S42]. Also `WmiSetALSBrightness`/`WmiSetALSBrightnessState` (ambient light) and `WmiRevertToPolicyBrightness` [S41]. Companion read class: `WmiMonitorBrightness` (levels/current) in the same namespace [S41].

**Secondary — dxva2 `SetMonitorBrightness`** [S43]:
```cpp
BOOL SetMonitorBrightness(HANDLE hMonitor, DWORD dwNewBrightness);  // Dxva2.dll [S43]
```
Microsoft's own warning: this uses VESA MCCS over I²C; "many monitors don't fully implement that standard… We don't recommend using these functions for arbitrary monitors" [S43]. Use only for external monitors that report `MC_CAPS_BRIGHTNESS`; for the AN515-45 panel use WMI. Plan-level brightness can additionally be written via `GUID_DEVICE_POWER_POLICY_VIDEO_BRIGHTNESS` (§1.2).

---

## 3. Elevation & integrity

### 3.1 Detect Administrator

```python
import ctypes
is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())   # Shell32.dll [S34]
```
`IsUserAnAdmin()` returns TRUE if the user is a member of the Administrators group; Microsoft marks it "may be altered or unavailable" and recommends calling `CheckTokenMembership` directly [S34]. Robust alternative: `CheckTokenMembership(NULL, admin_sid)` (`securitybaseapi`) [S34], or in Python: `ctypes.windll.advapi32.CheckTokenMembership`. Note the difference between *is member* and *is elevated* (UAC split token); for "are my writes going to succeed" also try a probe write (e.g., `powercfg /setacvalueindex` on the app's own plan) [S2].

### 3.2 Self-elevation pattern (recommended: `asInvoker` + in-app relaunch)

- `ShellExecuteW(hwnd, "runas", file, params, dir, SW_SHOWNORMAL)` — documented verb: "**runas**: Launches an application as Administrator. User Account Control (UAC) will prompt the user for consent…" [S35]. Return value > 32 = success; `ERROR_CANCELLED` (1223) = user declined the UAC prompt [S35].
- Recommended flow: manifest stays `asInvoker` (app starts instantly for the 90% read-only features); privileged actions show a dialog "Administrator privileges required — [Relaunch as admin]" which restarts the app via `ShellExecuteW(…, "runas", sys.executable, …)` (or the frozen exe path) and exits the unelevated instance. This beats `requireAdministrator` (UAC prompt at *every* launch) for a GUI tool [S34][S35].
- Manifest placement: embed as resource or ship `nitromaster.exe.manifest` next to the exe ("an application manifest that refers to `example.exe` … `example.exe.<resource ID>.manifest`") [S33m].

**Exact `app.manifest` (asInvoker, with the UAC + Win11 compatibility boilerplate):**
```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity version="1.0.0.0" name="NitroMasterPro.ControlCenter" type="win32"/>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <!-- asInvoker: no UAC prompt at startup. Use requireAdministrator only if
             the app is useless without elevation. -->
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <!-- Windows 10 / 11 -->
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
      <!-- Windows 8.1 -->
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"/>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
    </windowsSettings>
  </application>
</assembly>
```
(`trustInfo`/`requestedExecutionLevel` and element list per application-manifest schema docs [S33m]; the manifest assembly element must be in `urn:schemas-microsoft-com:asm.v1` [S33m].)

### 3.3 Which features need elevation

See the Admin-required operations table below. Rule of thumb: anything touching `HKLM`, the SCM, `powercfg` writes, or other users'/system processes needs a high-integrity (elevated) process [S2][S29][S27]; everything under `HKCU` and same-user process manipulation does not.

---

## 4. Graphics performance preference registry (force per-app GPU)

- **Key:** `HKEY_CURRENT_USER\Software\Microsoft\DirectX\UserGpuPreferences` [S44].
- **Value name:** the **absolute path** of the target executable (the exact string is the key); values are `REG_SZ` [S44].
- **Data format:** `GpuPreference=N;` where `N` is `0` = Let Windows decide, `1` = Power-saving GPU (iGPU on the AN515-45), `2` = High-performance GPU (RTX dGPU) [S44]. Windows 10 1803+ hosts this feature [S44].
- **Enumerate existing entries:** `winreg.OpenKey(HKCU, r"Software\Microsoft\DirectX\UserGpuPreferences")` + `EnumValue(i)` → each `(exe_path, "GpuPreference=N;", REG_SZ)`; to find one app, `QueryValueEx(key, exe_path)` [S44].
- **Write:** `winreg.SetValueEx(key, exe_path, 0, winreg.REG_SZ, "GpuPreference=2;")` — no admin required (HKCU). Deleting the value restores "Let Windows decide" [S44].
- **Backup/restore for the app's profiles:** `reg export "HKCU\Software\Microsoft\DirectX\UserGpuPreferences" gpu.reg /y` / `reg import gpu.reg`; a full key export/restore is the supported migration path — entries only work when the app paths match on the target system [S44].
- **Caveats:** entries are per-user and per-exe-path; UWP/Store apps are managed separately and this key may not apply to them (`UNVERIFIED`). An optional `Default` value name under the same key is reported by community sources but `UNVERIFIED` here — do not rely on it.
- Interaction with the Mode system: Gaming/Performance modes set `GpuPreference=2;` for the detected game executables; Ultra Battery Saver sets `GpuPreference=1;` for browsers/teams, and reverts on exit.

---

## Python integration recipe

### 5.1 Power plan control via ctypes (`powrprof.dll`)

```python
import ctypes
from ctypes import wintypes

ERROR_SUCCESS = 0

class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_str(cls, s: str) -> "GUID":
        s = s.strip("{}")
        p = s.split("-")
        b = bytes.fromhex(p[4])
        return cls(int(p[0], 16), int(p[1], 16), int(p[2], 16),
                   (ctypes.c_ubyte * 8)(*bytes.fromhex(p[3]), *b))

powrprof = ctypes.WinDLL("powrprof.dll")
powrprof.PowerGetActiveScheme.restype = wintypes.DWORD
powrprof.PowerGetActiveScheme.argtypes = [wintypes.HKEY, ctypes.POINTER(ctypes.c_void_p)]
powrprof.PowerWriteACValueIndex.restype = wintypes.DWORD
powrprof.PowerWriteACValueIndex.argtypes = [
    wintypes.HKEY, ctypes.POINTER(GUID), ctypes.POINTER(GUID), ctypes.POINTER(GUID), wintypes.DWORD]
powrprof.PowerWriteDCValueIndex.argtypes = powrprof.PowerWriteACValueIndex.argtypes
powrprof.PowerSetActiveScheme.restype = wintypes.DWORD
powrprof.PowerSetActiveScheme.argtypes = [wintypes.HKEY, ctypes.POINTER(GUID)]

kernel32 = ctypes.WinDLL("kernel32")
kernel32.LocalFree.argtypes = [ctypes.c_void_p]

def active_scheme_guid() -> GUID:                      # [S3]
    ptr = ctypes.c_void_p()
    rc = powrprof.PowerGetActiveScheme(None, ctypes.byref(ptr))
    if rc != ERROR_SUCCESS:
        raise ctypes.WinError(rc)
    try:
        return GUID.from_buffer_copy(ctypes.string_at(ptr, ctypes.sizeof(GUID)))
    finally:
        kernel32.LocalFree(ptr)                        # mandatory: LocalFree [S3]

def set_value(scheme: GUID, subgroup: GUID, setting: GUID,
              ac_index: int | None, dc_index: int | None) -> None:
    s, g, st = ctypes.byref(scheme), ctypes.byref(subgroup), ctypes.byref(setting)
    if ac_index is not None:
        rc = powrprof.PowerWriteACValueIndex(None, s, g, st, ac_index)   # [S4]
        if rc != ERROR_SUCCESS:
            raise ctypes.WinError(rc)                  # 5 = ERROR_ACCESS_DENIED -> needs elevation
    if dc_index is not None:
        rc = powrprof.PowerWriteDCValueIndex(None, s, g, st, dc_index)
        if rc != ERROR_SUCCESS:
            raise ctypes.WinError(rc)
    # Values on the ACTIVE scheme only take effect after re-activation [S4]:
    rc = powrprof.PowerSetActiveScheme(None, s)        # [S5]
    if rc != ERROR_SUCCESS:
        raise ctypes.WinError(rc)
```

### 5.2 `powercfg` subprocess helpers

```python
import subprocess

def run_powercfg(*args: str, need_admin: bool = False) -> str:
    p = subprocess.run(["powercfg", *args], capture_output=True, text=True, timeout=20)
    if p.returncode != 0:
        raise RuntimeError(f"powercfg {' '.join(args)} -> {p.returncode}: {p.stderr.strip()}")
    return p.stdout

def create_mode_plan(base_guid: str, name: str) -> str:      # returns new plan GUID
    out = run_powercfg("/duplicatescheme", base_guid)         # [S1]
    guid = out.split("(")[1].split(")")[0]                    # "(GUID) Name"
    run_powercfg("/changename", guid, name)                   # [S1]
    return guid

def apply_mode(plan_guid: str, subgroup: str, setting: str,
               ac: int | None = None, dc: int | None = None) -> None:
    if ac is not None:
        run_powercfg("/setacvalueindex", plan_guid, subgroup, setting, str(ac))  # [S1]
    if dc is not None:
        run_powercfg("/setdcvalueindex", plan_guid, subgroup, setting, str(dc))  # [S1]
    run_powercfg("/setactive", plan_guid)                                        # [S1]

def snapshot_plan(plan_guid: str, path: str) -> None:
    run_powercfg("/export", path, plan_guid)                  # .pow binary [S1]

def restore_plan(path: str, plan_guid: str | None = None) -> None:
    run_powercfg("/import", path, *( [plan_guid] if plan_guid else [] ))  # [S1]
```

### 5.3 Process suspend / EcoQoS

```python
import ctypes, psutil
from ctypes import wintypes

PROCESS_SUSPEND_RESUME   = 0x0800      # [S7]
PROCESS_SET_INFORMATION  = 0x0200      # [S7]
PROCESS_POWER_THROTTLING_CURRENT_VERSION        = 1   # [S54]
PROCESS_POWER_THROTTLING_EXECUTION_SPEED        = 0x1 # [S54]
PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION= 0x4 # [S54]
ProcessPowerThrottling = 4   # Enum member of PROCESS_INFORMATION_CLASS (verified index in SDK header) [S54]

class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG),
                ("ControlMask", wintypes.ULONG),
                ("StateMask", wintypes.ULONG)]               # [S21]

ntdll = ctypes.WinDLL("ntdll")
ntdll.NtSuspendProcess = ctypes.WINFUNCTYPE(wintypes.LONG, wintypes.HANDLE)(
    ("NtSuspendProcess", ntdll), ((1, "hProcess"),))          # undocumented [S28]
ntdll.NtResumeProcess = ctypes.WINFUNCTYPE(wintypes.LONG, wintypes.HANDLE)(
    ("NtResumeProcess", ntdll), ((1, "hProcess"),))           # undocumented [S28]

def suspend(pid: int) -> None:
    h = psutil.Process(pid).handle  # or OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if ntdll.NtSuspendProcess(h) < 0:                          # NTSTATUS
        raise OSError("NtSuspendProcess failed")

def set_eco_qos(pid: int, on: bool) -> None:                   # EcoQoS [S20][S22]
    k32 = ctypes.WinDLL("kernel32")
    h = k32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    st = PROCESS_POWER_THROTTLING_STATE(
        PROCESS_POWER_THROTTLING_CURRENT_VERSION,
        PROCESS_POWER_THROTTLING_EXECUTION_SPEED | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION,
        PROCESS_POWER_THROTTLING_EXECUTION_SPEED if on else 0)
    ok = k32.SetProcessInformation(h, ProcessPowerThrottling, ctypes.byref(st), ctypes.sizeof(st))
    err = ctypes.get_last_error()
    k32.CloseHandle(h)
    if not ok:
        raise ctypes.WinError(err)                             # [S20]

# Non-UI throttling fallbacks (psutil → SetPriorityClass / SetProcessAffinityMask [S28]):
#   psutil.Process(pid).nice(psutil.IDLE_PRIORITY_CLASS)
#   psutil.Process(pid).cpu_affinity([efficiency core ids])
```

### 5.4 Service snapshot / stop / restore (pywin32 or sc.exe)

```python
import json, subprocess
# snapshot before touching anything  [S29][S31][S32]
SNAP = {}
for svc in TARGETS:
    out = subprocess.run(["sc", "qc", svc], capture_output=True, text=True).stdout
    SNAP[svc] = out           # or QueryServiceConfigW() -> {start_type, binpath, deps, account}
json.dump(SNAP, open("service-baseline.json", "w"))

# stop only (reversible)  [S30]
subprocess.run(["sc", "stop", svc], capture_output=True)

# disable explicitly (user opted in)  [S29][S32]
subprocess.run(["sc", "config", svc, "start=", "disabled"], capture_output=True)

# restore on exit / profile switch  [S29][S32]
subprocess.run(["sc", "config", svc, "start=", "demand"], capture_output=True)  # from snapshot
subprocess.run(["sc", "start", svc], capture_output=True)
```

### 5.5 Brightness (WMI) — battery mode

```python
import wmi  # or win32com.client
c = wmi.WMI(namespace=r"root\wmi")
for mon in c.WmiMonitorBrightnessMethods():
    if mon.Active:
        mon.WmiSetBrightness(1, 40)   # Timeout=1s, Brightness=40%  [S42]
```

### 5.6 Admin detection + relaunch

```python
import sys, ctypes
from ctypes import wintypes

def is_admin() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())          # [S34]

def relaunch_as_admin() -> None:                                # "runas" verb [S35]
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.restype = ctypes.c_void_p              # HINSTANCE > 32 == ok [S35]
    rc = shell32.ShellExecuteW(None, "runas", sys.executable,
                               " ".join(sys.argv), None, 1)     # SW_SHOWNORMAL = 1
    if rc <= 32:
        raise ctypes.WinError(ctypes.get_last_error())           # 1223 = user cancelled UAC
    sys.exit(0)
```

---

## Admin-required operations table

| Operation | API / command | Elevated? | Notes |
|---|---|---|---|
| Read plans / active scheme / `powercfg /list /q /a` | `powercfg`, `PowerGetActiveScheme`, `PowerReadACValueIndex` | No | [S1][S3][S47] |
| Write power setting values / create / delete plans | `powercfg /setacvalueindex /duplicatescheme /delete`, `PowerWriteACValueIndex`, `PowerSetActiveScheme` | **Yes** (writes) | powercfg: "must be run from an elevated command prompt" for changes [S2]; expect `ERROR_ACCESS_DENIED` otherwise |
| Export/import `.pow`, `/attributes`, `/energy`, `/batteryreport`, `/systempowerreport` | `powercfg` | **Yes** for writes & reports [S2] | |
| Stop/start/change services | `sc`, `ControlService`, `ChangeServiceConfigW` | **Yes** | SCM rights `SERVICE_STOP`/`SERVICE_CHANGE_CONFIG` [S29][S30]; standard users may query [S31] |
| Query services | `sc query/qc`, `QueryServiceConfigW` | No | [S31][S33] |
| Suspend own-user apps | `NtSuspendProcess`, psutil | No (same user) | access `PROCESS_SUSPEND_RESUME` [S26][S28] |
| Suspend system/other-user processes | `NtSuspendProcess` + `SeDebugPrivilege` | **Yes** | `SE_DEBUG_NAME` is admin-granted [S25][S27] |
| EcoQoS / priority / affinity on own processes | `SetProcessInformation`, psutil | No | `PROCESS_SET_INFORMATION` on your own processes [S20] |
| EcoQoS on arbitrary processes | `SetProcessInformation` | Usually Yes (system procs) | DACL-dependent [S20][S26] |
| `timeBeginPeriod`, `SetThreadExecutionState`, `PowerSetRequest` | kernel32/winmm | No | per-process [S18][S19][S23] |
| Brightness (laptop panel) | WMI `WmiSetBrightness` | No (typical) — `UNVERIFIED` edge cases | `root\wmi` provider [S41][S42] |
| Brightness (external MCCS) | `SetMonitorBrightness` (dxva2) | No | monitor support varies [S43] |
| GPU preference registry | `HKCU\...\DirectX\UserGpuPreferences` | No | per-user hive [S44] |
| Disable Connected Standby (`CSEnabled`), unhiding settings (`Attributes`) | registry `HKLM\SYSTEM\CurrentControlSet\Control\Power\...` | **Yes** | risky [S37] |
| Admin check / self-elevation | `IsUserAnAdmin`, `ShellExecuteW("runas")` | n/a | [S34][S35] |

## Service suspension safety table (Windows 11)

Categories: **SAFE** = stop/disable for a battery-saver profile is low-risk · **CAUTIOUS** = only stop with user opt-in and automatic restore · **FORBIDDEN** = never stop/never disable.
Community safety research [S37] + service docs; risk notes are per-source or standard platform behavior.

| Service (name) | Display name | Class | Risk notes |
|---|---|---|---|
| `DiagTrack` | Connected User Experiences and Telemetry | **SAFE** | Telemetry only; safe to disable [S37] |
| `dmwappushservice` | WAP Push message Routing | **SAFE** | [S37] |
| `DPS` | Diagnostic Policy Service | **SAFE** (note) | Needed by `powercfg /batteryreport` — don't disable while battery diagnostics run [S37] |
| `diagnosticshub.standardcollector.service` | MS Diagnostics Hub collector | **SAFE** | [S37] |
| `TabletInputService` | Touch Keyboard and Handwriting Panel | **SAFE** (note) | Needed by Windows Terminal on Win11 [S37] |
| `tzautoupdate` | Auto Time Zone Updater | **SAFE** | [S37] |
| `lfsvc` | Geolocation Service | **SAFE** | [S37] |
| `DoSvc` | Delivery Optimization | **SAFE** (note) | P2P update sharing only; disables LAN update sharing [S37] |
| `RetailDemo` / `WpcMonSvc` / `MapsBroker` | Retail demo / parental / downloaded maps | **SAFE** | standard non-essentials (community-accepted; `UNVERIFIED` individually) |
| `WSearch` | Windows Search | **CAUTIOUS** | Saves CPU/index I/O; Start-menu/taskbar search degrades to slow enumeration. Not covered by [S37]; treat as opt-in |
| `SysMain` | SysMain (Superfetch) | **CAUTIOUS** | Reduces background prefetch I/O; may affect app launch latency. Community-recommended for SSD gaming rigs; opt-in |
| `BITS` | Background Intelligent Transfer Service | **CAUTIOUS** | Pauses update/Store downloads; auto-resume when restored. Windows Update depends on it |
| `wuauserv` | Windows Update | **CAUTIOUS** | Security updates stall while stopped; always restore before exit |
| `WlanSvc` | WLAN AutoConfig | **CAUTIOUS** | "Might be needed for Wi-Fi" — killing it drops wireless [S37]; only for plugged-in "focus" mode |
| `iphlpsvc` | IP Helper | **CAUTIOUS** | Not needed for IPv6 tunnels but some features use it [S37] |
| `RmSvc` | Radio Management | **CAUTIOUS** | May be needed for Wi-Fi/Bluetooth toggling [S37] |
| `bthserv` / `BluetoothUserService_*` | Bluetooth Support | **CAUTIOUS** | Required for BT pairing/usage; disable only if BT unused [S37] |
| `WbioSrvc` | Windows Biometric | **CAUTIOUS** | Breaks fingerprint sign-in & Settings page [S37] |
| `NlaSvc` | Network Location Awareness | **FORBIDDEN-ish** | Wrong network state when disabled [S37] — keep running |
| `WpnService` / `WpnUserService_*` | Windows Push Notifications | **FORBIDDEN-ish** | Breaks notifications/Action Center [S37] |
| `TokenBroker` | Web Account Manager | **FORBIDDEN-ish** | Settings › Accounts breaks [S37] |
| `SensorService` | Sensor Service | **FORBIDDEN-ish** | Settings › System › Power won't load on Win11 [S37] |
| `CDPSvc` / `CDPUserSvc_*` | Connected Devices Platform | **CAUTIOUS** | Needed for Night Light; per-user instances need registry `Start=4` to disable [S37] |
| `RpcSs` | Remote Procedure Call (RPC) | **FORBIDDEN** | System-wide RPC endpoint mapper host; system collapse |
| `DcomLaunch` | DCOM Server Process Launcher | **FORBIDDEN** | Required to start COM servers incl. SCM clients |
| `RpcEptMapper` | RPC Endpoint Mapper | **FORBIDDEN** | Required by RPC |
| `LSM` | Local Session Manager | **FORBIDDEN** | Session/logon state |
| `Winmgmt` | Windows Management Instrumentation | **FORBIDDEN** | WMI breaks → our own brightness/monitoring code breaks |
| `Power` | Power | **FORBIDDEN** | The power/powercfg subsystem itself |
| `AudioSrv` (+ `AudioEndpointBuilder`) | Windows Audio | **FORBIDDEN** | Breaks all sound; on a gaming laptop unacceptable |
| `Schedule` | Task Scheduler | **FORBIDDEN** | Many services/tasks depend on it |
| `EventLog` | Windows Event Log | **FORBIDDEN** | Required by numerous services |
| `PlugPlay` | Plug and Play | **FORBIDDEN** | Device lifecycle |
| `ProfSvc` / `UserManager` / `BrokerInfrastructure` | Profile/User/Broker infra | **FORBIDDEN** | Logon & UWP lifetime |
| `mpsdrv`, `WdFilter`, `WinDefend`, `SecurityHealthService` | Windows Defender stack | **FORBIDDEN** | Tamper-protected security |

Notes: per-user services with `_*` suffixes can't be disabled through `sc config` — use `HKLM\SYSTEM\CurrentControlSet\Services\<name>\Start=4` and expect regeneration by the OS [S37]. Trigger-started services can come back regardless of `start=` — inspect `sc qtriggerinfo` before claiming "disabled" [S52].

## Power plan settings matrix (per app mode)

All GUIDs verified in §1.2. Value indices are `powercfg` setting indices (timeouts in **seconds**; 0 = Never) [S12][S13][S1]. Apply AC and DC columns via `/setacvalueindex` + `/setdcvalueindex` or `PowerWriteAC/DCValueIndex` [S1][S4]. `—` = leave at plan default.

| Setting (alias) | Subgroup | Setting GUID | Normal (Balanced-based) AC / DC | Battery Saver AC / DC | Ultra Battery Saver AC / DC | Performance AC / DC | Gaming (Ultimate-based) AC / DC |
|---|---|---|---|---|---|---|---|
| Boost mode `PERFBOOSTMODE` [S8] | `54533251-…` | `be337238-…` | 2 / 1 (Aggressive / Enabled) | 1 / 0 (Enabled / Disabled) | 0 / 0 (Disabled) | 2 / 2 (Aggressive) | 2 / 2 (Aggressive) |
| Boost policy `PERFBOOSTPOL` [S9] | `54533251-…` | `45bcc044-…` | 100 / 60 | 50 / 30 | 0 / 0 | 100 / 100 | 100 / 100 |
| Max proc state `PROCTHROTTLEMAX` [S10] | `54533251-…` | `bc5038f7-…` | 100 / 100 | 100 / 80 | 55 / 50 | 100 / 100 | 100 / 100 |
| Min proc state `PROCTHROTTLEMIN` [S11] | `54533251-…` | `893dee8e-…` | 5 / 5 | 5 / 5 | 0 / 0 | 100 / 100 (pinned) | 100 / 100 |
| Cooling policy [S7] | `54533251-…` | `94d3a615-…` | 0 (Active) / 0 | 1 (Passive) / 1 | 1 / 1 | 0 / 0 | 0 / 0 |
| Display off `VIDEOIDLE` [S7] | `7516b95f-…` | `3c0bc021-…` | 600 / 300 | 180 / 120 | 60 / 60 | 900 / 600 | 0 (never while gaming UI) / 600 |
| Dim after `DIMTIMEOUT` [S7] | `7516b95f-…` | `17aaa29b-…` | 480 / 240 | 120 / 90 | 30 / 30 | — / — | — / — |
| Brightness level [S7] (hidden) | `7516b95f-…` | `aded5e82-…` | 100 / 80 | 60 / 45 | 35 / 25 | 100 / 100 | 100 / 100 |
| Sleep after `STANDBYIDLE` [S12] | `238c9fa8-…` | `29f6c1db-…` | 1800 / 900 | 600 / 300 | 300 / 180 | 3600 / 1800 | 0 / 1800 |
| Hibernate after `HIBERNATEIDLE` [S13] | `238c9fa8-…` | `9d7815a6-…` | 0 / 3600 | 0 / 1800 | 0 / 900 | 0 / 7200 | 0 / 0 |
| Hybrid sleep `HYBRIDSLEEP` [S14] | `238c9fa8-…` | `94ac6d29-…` | 1 / 1 | 0 / 0 | 0 / 0 | 1 / 1 | 1 / 1 |
| PCIe ASPM `ASPM` [S15] | `501a4d13-…` | `ee12f906-…` | 1 (Moderate) / 2 (Max) | 2 / 2 | 2 / 2 | 0 (Off) / 1 | 0 / 0 |
| Wireless power saving [S45] (`UNVERIFIED` GUID) | `19cbb8fa-…` | (runtime) | 0/1 (Max perf / Low) | 2/3 (Med / Max saving) | 3 / 3 | 0 / 0 | 0 / 0 |

Companion (non-plan) actions per mode:

| Action | Normal | Battery Saver | Ultra Battery Saver | Performance | Gaming |
|---|---|---|---|---|---|
| EcoQoS on background apps [S20][S22] | on | on | on + foreground too | off | off (game: HighQoS) |
| `IGNORE_TIMER_RESOLUTION` for background [S20] | on | on | on | off | off |
| Background priority (psutil `IDLE_PRIORITY_CLASS`) [S28] | selective | all non-focused | all non-focused | — | — |
| Service stops (per safety table) | none | DiagTrack, dmwappush, lfsvc, tzautoupdate | + WSearch, SysMain, BITS, wuauserv, DoSvc (all auto-restored) | none | DiagTrack only |
| GPU preference (`UserGpuPreferences`) [S44] | default | iGPU for office apps | iGPU for everything | dGPU for target app | dGPU for game exe |
| Display brightness (WMI) [S42] | 100% AC / 80% DC | 60% / 45% | 35% / 25% | 100% | 100% |
| `SetThreadExecutionState` [S18] | `ES_CONTINUOUS` only during active maintenance | — | — | `ES_CONTINUOUS\|ES_SYSTEM_REQUIRED` during benchmarks | same, during gameplay |

## Unsupported / risky

- **`powercfg /restoredefaultschemes`** (undocumented) — reports of wiping schemes instead of restoring, worse under Modern Standby [S2]. Never expose in UI.
- **`NtSuspendProcess`/`NtResumeProcess`** — undocumented ntdll APIs [S28]; no forward-compat guarantee; must not be used on services, PPL processes, `csrss`, or anything with in-flight I/O holding locks. AV may flag; document in release notes.
- **`DebugActiveProcess` freezing** — works but single-debugger semantics + `PROCESS_ALL_ACCESS` + `SE_DEBUG_NAME` make it fragile and heuristically hostile [S25]. Unsupported in the product.
- **Disabling Modern Standby (`HKLM\...\Control\Power\CSEnabled` = 0)** [S37] — only effective if the firmware exposes S3; Microsoft states switching between S3 and Modern Standby "is not supported in Windows without a complete OS re-install" [S17]. Mark unsupported; detect with `powercfg /a` instead.
- **`SetMonitorBrightness` (dxva2)** on non-MCCS monitors — Microsoft warns of undefined monitor behavior [S43]. Restrict to monitors reporting `MC_CAPS_BRIGHTNESS`; use WMI for the laptop panel [S41].
- **`ES_AWAYMODE_REQUIRED`** — S3-only; misleading on Modern Standby laptops [S18][S19].
- **`PowerRequestAwayModeRequired`** — "only applicable on Traditional Sleep (S3) systems" [S19].
- **System-wide `timeBeginPeriod`** — no longer global since Win10 2004 and ignored for occluded windows on Win11; battery-hostile if misused [S23].
- **Forcing min=100% proc state (`PROCTHROTTLEMIN=100`)** — pins CPU, disables core parking/idle; only in Gaming/Performance, never persisted across reboots by default.
- **Disabling `Winmgmt`/`Power`/`RpcSs` etc.** — system collapse (see FORBIDDEN list).
- **`PERFTHROTTLING` alias mapping** and **SUB_WIRELESS setting GUID** — `UNVERIFIED`; resolve at runtime (`powercfg /aliases`, `/qh`, registry enumeration) and fail soft rather than hardcoding guesses.
- **GPU preference for UWP/Store apps** — `UserGpuPreferences` documented format covers desktop exe paths [S44]; applicability to UWP is `UNVERIFIED`.
- **Ultimate Performance on battery** — community reports it is unavailable/AC-only on some laptops [S38]; if `/duplicatescheme e9a42b02-…` fails or activation errors, fall back to High performance.

## Sources

[S1] Microsoft Learn — *Powercfg command-line options*: https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/powercfg-command-line-options
[S2] SS64 — *PowerCfg.exe (Windows CMD)* (real `powercfg /aliases` output, elevation note, `/qh`, undocumented switches): https://ss64.com/nt/powercfg.html
[S3] Microsoft Learn — *PowerGetActiveScheme function*: https://learn.microsoft.com/en-us/windows/win32/api/powersetting/nf-powersetting-powergetactivescheme
[S4] Microsoft Learn — *PowerWriteACValueIndex function* (subgroup GUID table, re-activation remark): https://learn.microsoft.com/en-us/windows/win32/api/powersetting/nf-powersetting-powerwriteacvalueindex
[S5] Microsoft Learn — *PowerSetActiveScheme function*: https://learn.microsoft.com/en-us/windows/win32/api/powersetting/nf-powersetting-powersetactivescheme
[S6] Microsoft Learn — *Power Scheme Management*: https://learn.microsoft.com/en-us/windows/win32/power/managing-power-schemes
[S7] mingw-w64 `winnt.h` (public mirror of Windows SDK power-setting GUIDs `GUID_*`): https://github.com/mingw-w64/mingw-w64/blob/master/mingw-w64-headers/include/winnt.h
[S8] Microsoft Learn — *PERFBOOSTMODE*: https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/options-for-perf-state-engine-perfboostmode
[S9] Microsoft Learn — *PERFBOOSTPOL*: https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/legacy-config-options-perfboostpol
[S10] Microsoft Learn — *MaxPerformance* (`PROCTHROTTLEMAX`): https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/options-for-perf-state-engine-maxperformance
[S11] Microsoft Learn — *MinPerformance* (`PROCTHROTTLEMIN`): https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/options-for-perf-state-engine-minperformance
[S12] Microsoft Learn — *Sleep idle timeout* (`STANDBYIDLE`, GUID `29f6c1db-…`, seconds): https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/sleep-settings-sleep-idle-timeout
[S13] Microsoft Learn — *Hibernate idle timeout* (`HIBERNATEIDLE`, Modern Standby note): https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/sleep-settings-hibernate-idle-timeout
[S14] Microsoft Learn — *Hybrid sleep* (`HYBRIDSLEEP`, 0/1): https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/sleep-settings-hybrid-sleep
[S15] Microsoft Learn — *Link state power management* (`ASPM` GUID + 0/1/2 values): https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/pci-express-settings-link-state-power-management
[S16] Microsoft Learn — *Processor power management options* (setting list, battery-saver "Constrained" profile): https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/configure-processor-power-management-options
[S17] Microsoft Learn — *Modern Standby*: https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/modern-standby
[S18] Microsoft Learn — *SetThreadExecutionState*: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate
[S19] Microsoft Learn — *PowerSetRequest* (Modern Standby DC 5-minute rule, away-mode S3-only): https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-powersetrequest
[S20] Microsoft Learn — *SetProcessInformation* (EcoQoS, `PROCESS_POWER_THROTTLING_*` semantics): https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation
[S21] Microsoft Learn — *PROCESS_POWER_THROTTLING_STATE*: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ns-processthreadsapi-process_power_throttling_state
[S22] Microsoft Learn — *Quality of Service* (QoS levels incl. Eco/Utility): https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service
[S23] Microsoft Learn — *timeBeginPeriod* (Win10 2004 per-process, Win11 occluded-window rule): https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod
[S24] Microsoft Learn — *PssCaptureSnapshot*: https://learn.microsoft.com/en-us/windows/win32/api/processsnapshot/nf-processsnapshot-psscapturesnapshot
[S25] Microsoft Learn — *DebugActiveProcess* (thread suspension, `SE_DEBUG_NAME`, `PROCESS_ALL_ACCESS`): https://learn.microsoft.com/en-us/windows/win32/api/debugapi/nf-debugapi-debugactiveprocess
[S26] Microsoft Learn — *Process Security and Access Rights* (`PROCESS_SUSPEND_RESUME`, `PROCESS_SET_INFORMATION`): https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights
[S27] Microsoft Learn — *Privilege Constants* (`SE_DEBUG_NAME`, `LookupPrivilegeValue`): https://learn.microsoft.com/en-us/windows/win32/secauthz/privilege-constants
[S28] psutil source — `psutil/arch/windows/proc.c` (`NtSuspendProcess`/`NtResumeProcess`, `SetPriorityClass`, `SetProcessAffinityMask`) and `psutil/arch/windows/ntextapi.h` (typedefs): https://github.com/giampaolo/psutil/blob/master/psutil/arch/windows/proc.c · https://github.com/giampaolo/psutil/blob/master/psutil/arch/windows/ntextapi.h
[S29] Microsoft Learn — *ChangeServiceConfigW*: https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-changeserviceconfigw
[S30] Microsoft Learn — *ControlService*: https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-controlservice
[S31] Microsoft Learn — *QueryServiceConfigW*: https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-queryserviceconfigw
[S32] Microsoft Learn — *sc.exe config*: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/sc-config
[S33] Microsoft Learn — *sc.exe query*: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/sc-query
[S33m] Microsoft Learn — *Application manifests* (element schema, `example.exe.manifest` naming, `trustInfo`): https://learn.microsoft.com/en-us/windows/win32/sbscs/application-manifests
[S34] Microsoft Learn — *IsUserAnAdmin* (wrapper for `CheckTokenMembership`): https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-isuseranadmin
[S35] Microsoft Learn — *ShellExecuteW* ("runas" verb, return > 32): https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecutew
[S36] psutil documentation (nice/ionice/cpu_affinity/suspend): https://psutil.readthedocs.io/en/latest/
[S37] GitHub gist (Aldaviva) — *Safety of disabling services in Windows 10 and 11* (safe / do-not-disable tables): https://gist.github.com/Aldaviva/0eb62993639da319dc456cc01efa3fe5
[S38] Community verification of Ultimate Performance GUID `e9a42b02-d5df-448d-aa00-03f14749eb61` (`powercfg -duplicatescheme`): https://superuser.com/questions/1327298/how-to-enable-ultimate-performance-power-plan-in-windows-10 · https://www.tenforums.com/tutorials/107613-add-remove-ultimate-performance-power-plan-windows-10-a-2.html · https://github.com/memstechtips/UnattendedWinstall/discussions/101
[S39] Microsoft Q&A — *Hidden Power Settings* (`powercfg -attributes SUB_PROCESSOR … -ATTRIB_HIDE`): https://learn.microsoft.com/en-us/answers/questions/3905423/hidden-power-settings
[S40] Real `powercfg /a` output on Modern Standby laptops (S0 Low Power Idle listed, S1–S3 "system firmware does not support this standby state"): https://www.tenforums.com/general-support/192514-uh-ok-what-happened-sleep.html · https://h30434.www3.hp.com/t5/Desktops-Archive-Read-Only/Enable-S3-Sleep-State-in-BIOS-Firmware/td-p/8283201
[S40b] Acer community — Predator laptop without S3 (S0ix behavior): https://community.acer.com/en/discussion/711315/predator-ph18-72-does-not-enter-sleep-mode-s3
[S41] Microsoft Learn — *WmiMonitorBrightnessMethods class* (`root\wmi`): https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmimonitorbrightnessmethods
[S42] Microsoft Learn — *WmiSetBrightness method* (`uint32 Timeout, uint8 Brightness`): https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmisetbrightness-method-in-class-wmimonitorbrightnessmethods
[S43] Microsoft Learn — *SetMonitorBrightness* (dxva2, MCCS warning): https://learn.microsoft.com/en-us/windows/win32/api/highlevelmonitorconfigurationapi/nf-highlevelmonitorconfigurationapi-setmonitorbrightness
[S44] NinjaOne — *Backup & Restore GPU Preferences for Apps* (`HKCU\Software\Microsoft\DirectX\UserGpuPreferences`, `GpuPreference=0|1|2;`): https://www.ninjaone.com/blog/restore-gpu-preferences-for-apps-in-windows/ (independent confirmation of key path: https://stackoverflow.com/questions/59732181/programmatically-set-graphics-performance-for-an-app)
[S45] TenForums — *Add or Remove "Wireless Adapter Settings" in Power Options* (subgroup GUID `19cbb8fa-5279-450e-9fac-8a3d5fedd0c1`): https://www.tenforums.com/tutorials/73119-add-remove-wireless-adapter-settings-power-options-windows-10-a.html
[S46] Community/MS Q&A verification that Maximum processor state = `bc5038f7-23e0-4960-96da-33abaf5935ec`: https://www.tenforums.com/tutorials/107967-add-remove-maximum-processor-state-power-options-windows.html · https://learn.microsoft.com/en-us/answers/questions/3771576/how-to-enable-maximum-processor-state
[S47] Microsoft Learn — *PowerReadACValueIndex*: https://learn.microsoft.com/en-us/windows/win32/api/powrprof/nf-powrprof-powerreadacvalueindex
[S48] Microsoft Learn — *PowerDuplicateScheme*: https://learn.microsoft.com/en-us/windows/win32/api/powrprof/nf-powrprof-powerduplicatescheme
[S49] Microsoft Learn — *PowerDeleteScheme*: https://learn.microsoft.com/en-us/windows/win32/api/powrprof/nf-powrprof-powerdeletescheme
[S50] Microsoft Learn — *ChangeServiceConfig2W* (delayed-auto, description, triggers): https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-changeserviceconfig2w
[S51] Microsoft Learn — *QueryServiceConfig2W*: https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-queryserviceconfig2w
[S52] Microsoft Learn — *Service Trigger Events*: https://learn.microsoft.com/en-us/windows/win32/services/service-trigger-events
[S53] Microsoft Learn — *PowerClearRequest*: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-powerclearrequest
[S54] mingw-w64 `processthreadsapi.h` (SDK mirror: `PROCESS_POWER_THROTTLING_*` numeric values, `ProcessPowerThrottling` enum, `THREAD_POWER_THROTTLING_STATE`): https://github.com/mingw-w64/mingw-w64/blob/master/mingw-w64-headers/include/processthreadsapi.h
