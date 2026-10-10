# 01 — Platform Research: Acer Nitro 5 AN515-45 (2021, AMD Cezanne)

## Executive summary (for the architecture agent)

1. **Board**: Acer Nitro 5 AN515-45 (shares platform with AN517-41). Motherboard silkscreen **"GH53Z"**, repair-doc code **"LA-L031P"** (Rev 1A/1B). OEM attribution is conflicting (see §1) — treat vendor as UNVERIFIED. DMI product name is `Nitro AN515-45` (this exact string is what Linux drivers match on).
2. **Control plane is one WMI firmware interface**: `root\wmi` class **`AcerGamingFunction`** (ACPI WMI GUID `7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56`, "WMID_GUID4"). Fans, thermal profiles, keyboard RGB and sensors all go through it. It is firmware-exposed (via the inbox WMI/ACPI stack), **not** an OEM kernel driver — no "Sandra" driver exists in any analyzed stack (UNVERIFIED/likely a misremembered name).
3. **Fan control (Windows)**: `SetGamingFanBehavior` (Auto/Max/Custom, fan bitmap `0x0009`, mode bits 17:16 CPU / 23:22 GPU) and `SetGamingFanSpeed` (`selector | percent<<8`, selector `0x01`=CPU, `0x04`=GPU, 0–100 %). Verified working constants: Auto `0x00410009`, Max `0x00820009`, Custom `0x00C30009`. Requires admin (or a LocalSystem service). No OEM service strictly required.
4. **Sensors**: `GetGamingSysInfo` selectors `0x0101` CPU temp °C, `0x0A01` GPU temp °C, `0x0201` CPU fan RPM, `0x0601` GPU fan RPM (status byte 0 = ok).
5. **Thermal profiles**: `SetGamingMiscSetting` index `0x0B`, values Quiet=0, Balanced=1, Performance=4, Turbo=5, Eco=6; supported mask readable at index `0x0A`. Profile changes can silently reset custom fan duty.
6. **Keyboard**: AN515-45 has a **4-zone RGB** keyboard (NitroSense `Plugs/Nitro AN515-45/HW_Support.ini`: `LightingType:1`, `PerKey=0`, 4 zones, default `#FF0000`). Control = `SetGamingLEDBehavior` (WMI method id 2, payload `8 | (15<<40)` to switch the panel on), per-zone color `SetGamingRgbKb` (4 bytes `{zone,r,g,b}`, zone bitmask `0x01,0x02,0x04,0x08`), mode/effect `SetGamingKBBacklight` (method id 20; 16-byte payload, modes 0–7).
7. **Critical gotcha (AN515-45 measured)**: colour writes are accepted and "succeed" while the panel stays dark unless the enable sequence (`GetGamingSysInfo(0)` then LED method 2 with `8 | (15<<40)`) is sent first; the panel can also be handed back to the EC (power cycle, clearing PSEE) — re-apply before every write.
8. **Persistence**: after a power cycle the keyboard returns to firmware default **red**, custom colours/effects do **not** survive reboot; custom fan duty is also volatile (`0,0` = firmware reclaims fans). The app must restore state at startup/resume.
9. **NitroSense key ("N" key)**: Linux evdev `KEY_PRESENTATION` (425), scancode `0xf5`, on the AT/PS2 keyboard device. Windows: other Acer models show extended scancode `0x75` (AN515-45 itself UNVERIFIED) — detect at runtime.
10. **NitroSense Windows stack** (evidence mostly from an AN17-42 teardown + AN515-45 installer strings): `AASSvc` service → `AcerAgentService.exe` + `AcerHardwareService.exe` (loopback JSON API `127.0.0.1:46933`, `ACER`-framed), `NitroSense.exe` + `TsDotNetLib.dll` (WMI wrapper `WMISetGaming*`), `AcerLightingService` → bundled OpenRGB 0.7.0 server on `TCP 6742`, `AcerDeviceEnablingServiceV2` + `AcerDeviceEnablingServiceComponent.sys`.
11. **Power**: CPU 45 W TDP (Cezanne-H, cTDP-down 35 W). GPU TGP by SKU: RTX 3060 = 95 W, RTX 3070 = 100 W, RTX 3080 Laptop = 100 W (Dynamic Boost nuances per BIOS). Dual fans (CPU fan id 1, GPU fan id 4); "CoolBoost" = firmware fan-speed bump.
12. **Do not implement**: raw EC/port I/O on Windows (needs a kernel driver, risky), OC misc settings `0x05`/`0x07` (not verified on this model), LCD override (firmware reports "not applicable", `0xFF`), and any assumption of `MSAcpi_ThermalZoneTemperature` (UNVERIFIED on this model — degrade gracefully).

---

## 1. Motherboard / platform identity

### 1.1 Board and chassis

- Motherboard marking **"GH53Z"**, schematic/boardview designation **"LA-L031P"** (Rev 1A / Rev 1B exist). The same board serves the **Acer Nitro 5 AN515-45 and AN517-41** (15" and 17" chassis). Repair sources: schematic packages titled "Acer Nitro 5 AN515-45 AN517-41 LA-L031P GH53Z Rev 1A" (https://diskrekuperar.com.br/products/pacote-de-esquemas-eletricos), "Acer Nitro 5 AN515-45 GH53Z LA-L031P Schematic Diagram" (https://thetechstall.com/acer-nitro-5-an515-45-gh53z-la-l031p-schematic-diagram/), BIOS requests for "GH53Z LA-L031P REV : 1B" (https://www.badcaps.net/forum/troubleshooting-hardware-devices-and-electronics-theory/troubleshooting-laptops-tablets-and-mobile-devices/bios-requests-only/103327-hello-i-need-bios-dump-for-gh53z-la-l031p-rev-1b/page2), "Acer Nitro AN515-45 GH53Z LA-L031P Rev 1B" (https://bioshelp.com/forum-acer-laptop-bios.html).
- **OEM/ODM attribution: UNVERIFIED / conflicting.** bioshelp lists GH53Z under "Quanta Motherboard / Quanta Notebook Bios" categories (https://bioshelp.com/forum-acer-laptop-bios.html), but the "LA-…" board code is the Compal naming scheme and no source states the actual manufacturer contract. Do not hard-code an ODM name in the app.
- Acer chassis/model numbering example from an owner thread: `AN515-45-R77J`, model no. `N20C1` (badcaps thread above).
- DMI strings matched by community drivers: `SYS_VENDOR = "Acer"`, `PRODUCT_NAME = "Nitro AN515-45"` — this is the identifier to match in the app (source: the AN515-45 DMI quirk added in https://github.com/participatory-doublethink2007/NitroSense-Linux-AN515-45/blob/main/patches/linuwu-sense-an515-45-rgb.patch).

### 1.2 Silicon

- **CPU/APU**: AMD Ryzen 5000H "Cezanne" (Zen 3, FP6 socket): Ryzen 5 5600H / Ryzen 7 5800H / Ryzen 9 5900HX depending on SKU. Ryzen 7 5800H: 45 W TDP (https://www.techpowerup.com/cpu-specs/ryzen-7-5800h.c2368), configurable down to 35 W (https://wccftech.com/amd-ryzen-7-5800h-8-core-16-thread-cezanne-zen-3-cpu-shows-up/). Cezanne is a single-die SoC; **any claim of a separate southbridge/chipset on this board is UNVERIFIED** — do not assume one exists.
- **GPU (dGPU)**: NVIDIA RTX 30-series laptop (GA106/GA104): RTX 3060 Laptop 95 W, RTX 3070 Laptop 100 W, RTX 3080 Laptop 100 W TGP options (https://laptopmedia.com/series/acer-nitro-5-an515-45/; https://laptopmedia.com/nl/review/acer-nitro-5-an515-45/). See §5.
- **EC (embedded controller)**: present as the standard ACPI `PNP0C09` device; it owns fan duty, keyboard-lighting registers and thermal behaviour. On Linux it is reachable read-only via `ec_sys` at `/sys/kernel/debug/ec/ec0/io` on this exact model (capture script in https://github.com/participatory-doublethink2007/NitroSense-Linux-AN515-45/blob/main/scripts/capture-boot-lighting.sh). **EC silicon vendor/model: UNVERIFIED** (no public source found). On Windows there is no inbox EC access; direct EC access needs a signed kernel driver (RWEverything-class) → see "Unsupported / risky".

### 1.3 ACPI / WMI device surface

WMI blocks are ACPI `PNP0C14` mapping devices whose method tables are addressed by GUID. GUIDs used by the Acer stack (from mainline `acer-wmi.c`, https://github.com/torvalds/linux/blob/master/drivers/platform/x86/acer-wmi.c):

```
AMW0_GUID1  67C3371D-95A3-4C37-BB61-DD47B491DAAB   (legacy AMW0 register interface)
AMW0_GUID2  431F16ED-0C2B-444C-B267-27DEB140CF9C
WMID_GUID1  6AF4F258-B401-42FD-BE91-3D4AC2D7C0D3   (WMID method-ID interface)
WMID_GUID2  95764E09-FB56-4E83-B31A-37761F60994A
WMID_GUID3  61EF69EA-865C-4BC3-A502-A0DEBA0CB531   (hotkey "get/set device status" v2)
WMID_GUID4  7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56   ("Gaming" interface — fans, LEDs,
            misc settings, sys info)  <-- THE ONE THAT MATTERS FOR AN515-45
ACERWMID_EVENT_GUID 676AA15E-6A47-4D9F-A2CC-1E6D18D14026   (WMI events/hotkeys)
```

- Presence check that works on AN515-45 (Linux): `ls /sys/bus/wmi/devices/7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56` (documented compatibility gate in https://github.com/JafarAkhondali/acer-predator-turbo-and-rgb-keyboard-linux-module README; that module lists **AN515-45 as RGB tested**).
- The legacy AMW0 call in mainline is literally named `wmab_execute()` — it evaluates `AMW0_GUID1` instance 0, method 1 with a 4×u32 "register" buffer (`eax/ebx/ecx/edx`), i.e. the classic Acer **`WMAB`** ACPI method interface. `WMBC` is the sibling method name seen in older Acer WMI AML. **On AN515-45 the fan/RGB functions do NOT go through WMAB/WMBC** — they go through `WMID_GUID4` ("Gaming"); whether the DSDT still exposes `WMAB`/`WMBC` at all on this model is UNVERIFIED.
- Windows exposes the same WMI blocks under **`root\wmi`** via the inbox WMI-ACPI mapper (device `WMIADAP`/`wmiacpi.sys` path). The class name Acer's own MOF gives the `WMID_GUID4` block is **`AcerGamingFunction`** (see §6).

### 1.4 What the Acer "NitroSense" stack actually is on Windows

Evidence: full service/process teardown of a modern Nitro (AN17-42, Windows 11 23H2, BIOS V1.29) in https://github.com/derenma/acer_control/blob/main/acer_analysis.md, plus strings extracted from the **AN515-45 NitroSense installer** (`NitroSense.exe`, `TsDotNetLib.dll`, `Plugs/Nitro AN515-45/HW_Support.ini`) documented in https://github.com/participatory-doublethink2007/NitroSense-Linux-AN515-45/blob/main/docs-rgb-findings.md.

Services (12 Acer services found on the analyzed Nitro; the important ones):

| Service | Executables | Role |
|---|---|---|
| `AASSvc` ("Acer Agent Service Central") | `AcerAgentService.exe`, `AcerHardwareService.exe` | The hardware-control backend NitroSense talks to: CPU/GPU temps, utilization, clocks, fan RPM, profiles (Quiet/Balanced/Performance/Turbo), GPU mode/OC, keyboard backlight timeout/brightness keys, NitroSense key, DTS audio. Exposes loopback JSON API on **TCP 127.0.0.1:46933** with `ACER`-style framing |
| `AcerLightingService` | starts **bundled OpenRGB 0.7.0** (`OpenRGB.exe --server`) | Keyboard RGB: 4 zones, brightness, static colors, breathing/neon/wave/shifting/zoom/meteor/twinkling effects. OpenRGB listens on **TCP 0.0.0.0:6742** (wildcard! — see risks) |
| `AcerDeviceEnablingServiceV2` (ADES) | `ADESv2Svc.exe`, `ADESv2BW.exe`, `FUB.exe`, driver `AcerDeviceEnablingServiceComponent.sys` | Privacy-consent/enrollment broker; UEFI variable `AcerDeviceEnablingServiceFlag`; loopback TCP 51779–51782 (`ADESSocket`, JSON, `ACER` framing). Not needed for fan/profile/RGB control |
| `AcerServiceSvc` | `AcerService.exe` (Node.js "XSense-Service") | Local API at `https://localhost:15152`; Acer warranty/driver-list backend calls |
| `AcerDIAgentSvis`, `AcerDeviceInfoAgentService`, `AcerEZSvc`, `AcerPixyService`, `AcerARTAIMMX*` | various | Device inventory/telemetry, "Experience Zone" local TLS web service (127.0.0.1:19443), webcam/camera MFT |
| `AcerCCAgentSvis` (Care Center), `AcerQAAgentSvis` (Quick Access) | disabled on analyzed unit | Battery charge limits/calibration, powered-off USB charging, BlueLight Shield |

Kernel/PnP drivers (three running Acer drivers on the analyzed unit):

```
AcerAirplaneModeController                 (airplane-mode key / radio state)
AcerApplicationBaseDriver_Device           (base interface used by Acer apps;
                                            PnP software component bound to
                                            ACPI\VEN_1025&DEV_165F&SUBSYS_10021025
                                            — "Acer application base device",
                                            subsystem classified as Acer Nitro)
AcerDeviceEnablingServiceComponentService  (KMDF companion for ADES;
                                            IOCTL contract not established)
```

Application layer:

- **`NitroSense.exe`** — UI. On the analyzed 2025-era unit it is an Electron app (`--no-sandbox`, Chromium debug endpoint `127.0.0.1:9993`). The 2021-era AN515-45 NitroSense is an earlier version of the same product family (`.NET`-based: strings live in `TsDotNetLib.dll`).
- **`TsDotNetLib.dll`** — the WMI bridge layer. Verified strings (from `strings` on the AN515-45 NitroSense binaries):
  `WMISetGamingKBBacklight`, `WMISetGamingRgbKbSetting`, `WMISetGamingLEDBehavior`, `WMISetGamingMiscSetting` (source: docs-rgb-findings.md, link above). These are thin wrappers over `root\wmi:AcerGamingFunction` methods.
- **`HW_Support.ini`** — per-model feature declaration shipped in the NitroSense installer under `Plugs/Nitro AN515-45/`:
  ```ini
  [LightingType]
  Type:1
  PerKey=0
  [ZoneDefaultColor]
  Zone1=#FF0000  Zone2=#FF0000  Zone3=#FF0000  Zone4=#FF0000
  ```
  (`Type:1` = zone lighting, `PerKey=0` = not per-key; 4 zones; firmware boot default is red.) All 28 Nitro models in that package declare the same block, including AN515-58 which mainline `acer-wmi` supports.
- **"Sandra"**: **no evidence found.** Searches for a `Sandra`-named Acer/NitroSense kernel driver return nothing, and the detailed service/driver teardown above lists no such driver. Treat "Sandra" as UNVERIFIED (probable conflation with some other name). The actual kernel-side components are `AcerDeviceEnablingServiceComponent.sys`, `AcerAirplaneModeController`, `AcerApplicationBaseDriver_Device`, plus the inbox `WmiAcpi`/ACPI stack that hosts `AcerGamingFunction`.

---

## 2. Fan control

### 2.1 The firmware contract (works on both Windows and Linux)

All evidence below cross-confirms **two independent implementations** of the same protocol: mainline Linux `acer-wmi.c` (https://github.com/torvalds/linux/blob/master/drivers/platform/x86/acer-wmi.c) and a Windows .NET/PowerShell implementation against `root\wmi:AcerGamingFunction` (https://github.com/derenma/acer_control).

**Method IDs on WMI GUID `7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56`** (mainline `acer-wmi.c` constants; Windows method names from `acer_control` and NitroSense strings):

```
id 2   SetGamingLED / SetGamingLEDBehavior     (keyboard panel/LED behaviour, §3)
id 4   GetGamingLED / GetGamingLEDBehavior
id 5   GetGamingSysInfo                        (sensors, §2.3)
id 14  SetGamingFanBehavior                    (auto/max/custom per fan)
id 15  GetGamingFanBehavior
id 16  SetGamingFanSpeed                       (custom duty % per fan)
id 17  GetGamingFanSpeed                       (readback duty %)
id 20  SetGamingKBBacklight                    (keyboard effect/mode payload, §3)
id 21  GetGamingKBBacklight
id 22  SetGamingMiscSetting                    (thermal profile, OC, misc)
id 23  GetGamingMiscSetting
(id 6  "static LED" per-zone colour write — facer names it SET_GAMING_STATIC_LED;
       Windows name observed as SetGamingRgbKb / WMISetGamingRgbKbSetting)
```

The Windows name↔ID mapping for id 2 is verified ("`SetGamingLEDBehavior` is WMI method 2 on `WMID_GUID4`", docs-rgb-findings.md); 20/21 verified in `src/facer.c` (`ACER_WMID_SET_GAMINGKBBL_METHODID 20`, `ACER_WMID_GET_GAMINGKBBL_METHODID 21`); 14–17 and 22/23 verified in mainline. Remaining pairings are high-confidence but formally UNVERIFIED.

**Fan behavior (mode) encoding** — `SetGamingFanBehavior`, input is one 64-bit integer:

```
bits 15:0   fan bitmap:  BIT(0)=CPU fan (id 0x01), BIT(3)=GPU fan (id 0x04)
bits 17:16  CPU fan mode      (set)
bits 23:22  GPU fan mode      (set)
bits 9:8    CPU fan mode      (get reply)
bits 15:14  GPU fan mode      (get reply)
bits 7:0    status            (get reply; 0 = success)
mode values: 0x1 = AUTO, 0x2 = TURBO (NitroSense "Max"), 0x3 = CUSTOM
```

Verified constant values used against real Windows firmware (https://github.com/derenma/acer_control/blob/main/installable_service/src/AcerControl.Service/Hardware/AcerHardwareController.cs):

```
AutoFanBehavior     = 0x00410009   /* both fans, AUTO  (bits17:16=1, bits23:22=1) */
MaxFanBehavior      = 0x00820009   /* both fans, TURBO (bits17:16=2, bits23:22=2) */
CustomFanBehavior   = 0x00C30009   /* both fans, CUSTOM(bits17:16=3, bits23:22=3) */
```

Mainline rejects unknown status/`ENXIO` on out-of-range mode values (`ACER_WMID_FAN_MODE_AUTO=1 … ACER_WMID_FAN_MODE_CUSTOM=3`).

**Fan speed (custom duty) encoding** — `SetGamingFanSpeed`:

```
bits 7:0    fan selector: 0x01 = CPU fan, 0x04 = GPU fan
bits 15:8   target duty, percent 0..100
reply bits 7:0  status: 0 ok, 1 device absent, 2 invalid parameter
```

- Verified working on Windows firmware: `EncodeFanTarget(selector, percent) = selector | (percent << 8)`, percent validated 0–100 (AcerHardwareController.cs / `acer-control.ps1`).
- **Order of operations matters** (verified): set behavior to CUSTOM first, then write both fan targets; the reference implementation retries the pair once, then reads back via `GetGamingFanSpeed` and compares (`ReadFanTarget(0x01/0x04)` returns `(value>>8)&0xFF`).
- Mainline caveat: `speed > 100` is rejected (`-EINVAL`).
- **Divergence warning**: some third-party Linux tools (DAM Fan Controls) speak a different raw range for other interfaces/models ("some models use 512–2560, others 128–512, multiples of 128" — https://github.com/PXDiv/Div-Acer-Manager-Fan-Controls README). That is a different, non-`AcerGamingFunction` path; for AN515-45 via `WMID_GUID4` the unit is **percent 0–100**.

### 2.2 Windows integration paths (all verified)

1. **Direct firmware, no OEM software needed**: `root\wmi:AcerGamingFunction`, methods `SetGamingFanBehavior`, `SetGamingFanSpeed`, `GetGamingFanSpeed`. One instance per machine (`SELECT * FROM AcerGamingFunction`), methods take exactly one input parameter, outputs `gmOutput` (u64/int) and `gmReturn` (byte status). Requires elevation (the reference tool self-elevates through UAC and re-launches under Windows PowerShell 5.1 because `Get-WmiObject` is absent in PS7 — https://github.com/derenma/acer_control/blob/main/acer-control.ps1).
2. **Acer's own service, no elevation**: `AcerAgentService` (`AASSvc`) loopback JSON API on `127.0.0.1:46933`, `ACER`-framed JSON request/response (https://github.com/derenma/acer_control/blob/main/acer-fan-control.ps1). A normal user is normally sufficient. Requires the Acer stack installed.
3. **Kernel drivers are NOT required** for fan control on Windows; the WMI call path goes through the inbox WMI-ACPI stack into firmware.

### 2.3 Telemetry (fan RPM, temps)

`GetGamingSysInfo` (method 5), input = command|selector, reply = status byte + reading. The reference Windows selectors map exactly onto the mainline Predator-V4 sensor IDs:

```
0x0201  CPU fan speed (RPM; mask 0xFFFF)     /* cmd 0x0001 | sensor 0x02 */
0x0601  GPU fan speed (RPM; mask 0xFFFF)     /* sensor 0x06 */
0x0101  CPU temperature (°C; mask 0xFF)      /* sensor 0x01 */
0x0A01  GPU temperature (°C; mask 0xFF)      /* sensor 0x0A */
0x0000  supported-sensor bitmap (Predator-V4: bits 39:24)
```

Reading decode used on real firmware: status byte 0 = ok, else sensor unavailable; value in bits 23:8 (`DecodeSensor = (value & 0xFF) == 0 ? (value >> 8) & mask : null`). Mainline uses the same masks (`ACER_PREDATOR_V4_SENSOR_READING_BIT_MASK GENMASK_ULL(23,8)` etc.).

### 2.4 Linux implementations (evidence that the same model is controllable)

- **mainline `acer-wmi`**: has the full gaming fan implementation (methods 14–17, modes Auto/Turbo/Custom, hwmon PWM on `predator_v4` models) but the AN515-45 has **no quirk entry** in mainline (only `Nitro AN515-58` etc.). Features therefore don't auto-enable.
- **`facer`** (JafarAkhondali/acer-predator-turbo-and-rgb-keyboard-linux-module): AN515-45 listed **RGB implemented+tested**; turbo mode "-" (not applicable/not tested) for AN515-45. Source `src/facer.c` defines `ACER_WMID_SET_GAMING_FAN_BEHAVIOR 14` and the fan-speed read selectors `0x0201/0x0601`.
- **`Div-Linuwu-Sense`** (PXDiv/Div-Linuwu-Sense, fork of the Linuwu-Sense acer-wmi clone) with the **`nitro_v4`** quirk: on AN515-45 this exposes `fan_speed`, `thermal_profile`, `battery_limiter`, `battery_calibration`, `backlight_timeout`, `boot_animation_sound`, `usb_charging`, `per_zone_mode`, `four_zone_mode` (feature probe list in https://github.com/participatory-doublethink2007/NitroSense-Linux-AN515-45/blob/main/app/scripts/probe.ts; AN515-45 DMI quirk patch in `patches/linuwu-sense-an515-45-rgb.patch`). Fan duty is applied via the same `SetGamingFanBehavior`/`SetGamingFanSpeed` pair and re-applied after boot from a saved `fan.json` (`service/nitrosense-daemon.py`).
- **Fan curves**: the firmware has **no curve interface** — only Auto/Max/Custom duty. "Curves" in DAM Fan Controls are implemented in userspace by polling temperature and rewriting duty. NitroMaster must do the same (its own curve engine → SetGamingFanSpeed).

---

## 3. Keyboard backlight

### 3.1 Hardware facts (AN515-45 measured)

- **4-zone RGB keyboard**, not single-color: declared by NitroSense `HW_Support.ini` (`LightingType:1`, `PerKey=0`, 4 zones) and confirmed working (static green + four independent zone colors) — https://github.com/participatory-doublethink2007/NitroSense-Linux-AN515-45/blob/main/docs-rgb-findings.md.
- `facer` lists AN515-45 as RGB tested; issue discussion for the same model symptom: https://github.com/JafarAkhondali/acer-predator-turbo-and-rgb-keyboard-linux-module/issues/63.
- Firmware **boot default is red** (`ZoneDefaultColor #FF0000`); a power cycle returns the keyboard to that default.

### 3.2 WMI payloads (Windows = same calls NitroSense makes)

Enable sequence (required! verified on AN515-45; taken from `facer`, the only driver known to light this model):

```
1. GetGamingSysInfo (method 5), input 0
2. SetGamingLEDBehavior (method 2), input = 8 | (15 << 40)
   byte0 = 0x08  = BIT(3)  "ACER_GAMING_KBL_SET_ON"
   bits 43:40 = 0xF        zone mask = all four zones (1,2,4,8)
```

Both halves matter: placing the 15 in byte 1 instead of byte 5 is accepted and does nothing. Return values may be ignored (models without the feature still work otherwise). The panel may be handed back to the EC between writes (power cycle; "clearing PSEE"), so the reference implementation re-runs the enable before **every** user-initiated write (idempotent, 2 WMI calls).

Per-zone colour — `SetGamingRgbKb` (a.k.a. static LED, method id 6 family):

```
input u32 = zone | (red << 8) | (green << 16) | (blue << 24)
zone = 0x01 | 0x02 | 0x04 | 0x08   (bitmask per zone; NOT 1..4 ids)
```

(4-byte payload is required on AN515-45; an 8-byte u64 payload "succeeds" and does nothing — verified diff vs `facer` in `patches/linuwu-sense-an515-45-rgb.patch`. Windows reference encoding is identical: `EncodeColor(zone, r, g, b)` = `zone | r<<8 | g<<16 | b<<24`, `KeyboardZones = [0x01, 0x02, 0x04, 0x08]` — AcerHardwareController.cs.)

Mode/effect + brightness — `SetGamingKBBacklight` (method 20) / `GetGamingKBBacklight` (method 21), 16-byte input buffer:

```
byte 0  mode: 0 Static, 1 Breathing, 2 Neon, 3 Wave, 4 Shifting, 5 Zoom,
              6 Meteor, 7 Twinkling
byte 1  speed
byte 2  brightness
byte 3  wave flag: 8 for Wave (mode 3), else 0
byte 4  direction
bytes 5-7  red, green, blue
byte 8  MUST be 0 (3 = accepted-but-dead on AN515-45 firmware)
byte 9  1
bytes 10-15  0
```

Readback (`GetGamingKBBacklight`, input 1) returns `gmReturn` (status byte) + `gmOutput` byte array; `data[0]` = mode, `data[2]` = brightness (verified in `acer_control` ReadKeyboardState). Only mode 0 (Static) normalizes speed/direction to 0; other modes must pass fields through or the effects park dark (verified on AN515-45).

### 3.3 EC register map (read-only evidence; from the machine's own DSDT field names)

Captured via `/sys/kernel/debug/ec/ec0/io` on AN515-45 (https://github.com/participatory-doublethink2007/NitroSense-Linux-AN515-45/blob/main/scripts/capture-boot-lighting.sh):

```
0x17  KBLE  (mode)          0x18  KBLS (speed)      0x19  KBBP (brightness)
0x1A  KBCS                  0x1B  KBED (direction)
0x1C  KBCR (red)            0x1D  KBCG (green)      0x1E  KBCB (blue)
0x48  KBBA (zone select)
0x3C-0x3E  zone1 R,G,B      0x3F-0x41  zone2 R,G,B
0x42-0x44  zone3 R,G,B      0x45-0x47  zone4 R,G,B
(DSDT byte-field names for the zone registers are KB1R..KB4B family)
```

`KBLE = 0` turns the backlight off. Writing colours via WMI lands them correctly in `KB1R..KB4B` even when the panel is dark — the enable call is what lights it.

### 3.4 Persistence & timeout

- **Custom colours/effects do NOT survive reboot/power cycle** — firmware restores the red `ZoneDefaultColor`. The application must re-apply state at startup (Linux reference daemon persists to `fan.json`-style state and restores at service start).
- Keyboard backlight **idle timeout**: `GetGamingMiscSetting`-style selector `0x88401` reply carries the timeout in **whole seconds in bits 63:40**, low word echoes the selector. Measured on AN515-45: as shipped `0x210000080000` = 33 s; write 1 → `0x1E0000080000` = 30 s; write 0 → `0x000000080000` = off (any nonzero = enabled) — `patches/linuwu-sense-backlight-timeout-decode.patch`.
- `Fn+F9`/`Fn+F10` are the hardware backlight up/down keys on this family (their scancode decode differs between quirk paths — `patches/linuwu-sense-an515-45-rgb.patch`).
- Windows-side tooling: NitroSense UI (via `TsDotNetLib.dll` `WMISetGaming*`), and on the analyzed AN17-42 Acer's `AcerLightingService` drives a **bundled OpenRGB 0.7.0 server on TCP 6742** (protocol v3+ can set static color/brightness; `acer-keyboard-led.ps1` uses it). Whether the AN515-45-era NitroSense ships the same OpenRGB lighting service is UNVERIFIED (the WMI path works regardless).

---

## 4. Turbo / Performance key, fan-mode semantics, thermal behavior

### 4.1 The dedicated "N" (NitroSense) key

- **Linux/AN515-45 (verified with evtest)**: the key reports **`KEY_PRESENTATION` (evdev 425, scancode `0xf5`)** on the AT/PS2 keyboard device — *not* on the Acer WMI hotkeys device. X keysym `XF86Presentation` (X keycode 433). Source: `app/electron/nitro-key.ts` in https://github.com/participatory-doublethink2007/NitroSense-Linux-AN515-45.
- **Windows**: the key delivers a keyboard scancode in the interactive session and can be intercepted with a low-level keyboard hook (AutoHotkey/`SetWindowsHookEx`). The reference tooling for a newer Nitro (AN17-42) expects **extended scancode `0x75`** and explicitly warns it is model-dependent (https://github.com/derenma/acer_control/blob/main/key-remap/README.md; similar remapper https://github.com/Ricardokraus/Win11-Key-Remapper-Acer-Nitrosense). **AN515-45's exact Windows scancode is UNVERIFIED — detect at runtime, never hard-code.**
- The firmware-level "turbo key" WMI event (`WMID_GAMING_TURBO_KEY_EVENT = 0x7` on the Acer event GUID `676AA15E-…`, handled by `acer_toggle_turbo()`/`acer_thermal_profile_change()` in mainline) applies to Predator-style models with a turbo button. `facer`'s compatibility table shows Turbo "-" (unimplemented/untested) for AN515-45; there is **no evidence of a turbo hardware event on AN515-45** (its N key is a plain keyboard key). The AN515-45 has no dedicated performance/turbo button beyond the N key and Fn hotkeys.

### 4.2 Fan-mode semantics (NitroSense "Auto / Max / Custom")

- Firmware modes: `AUTO=1`, `TURBO=2` (this is what NitroSense labels **"Max"** / "CoolBoost max"; the task's "Cool" ≈ "Max"), `CUSTOM=3` — per fan (CPU bit0, GPU bit3).
- **CoolBoost** is Acer marketing for a firmware fan-speed bump: "CoolBoost increases fan speed by 10% and CPU/GPU cooling by 9% compared to auto mode" (Acer product text, https://global.microless.com/product/acer-nitro-5-an515-45-r1jm-...). It is not a separate WMI knob in the discovered interface — treat it as part of Auto/Max firmware behavior (UNVERIFIED whether a discrete toggle exists via `AcerAgentService`).
- Custom mode is set by first selecting CUSTOM behavior, then writing duty per fan (see §2.1). Duty is **volatile**: writing `0,0` is "hand fans back to firmware", and the Linux daemon explicitly persists/restores duty because the firmware reclaims control (power events, profile changes).
- **Profile changes can reset custom fan behavior** (observed with the Acer stack; `acer-control.ps1` help: "Changing the performance profile can reset custom fan control"). The app must re-assert custom duty after profile switches.

### 4.3 Performance profiles (NitroSense mode tiles)

`SetGamingMiscSetting` / `GetGamingMiscSetting` (ids 22/23), packed reply: status bits 7:0, value bits 15:8 (verified on Windows firmware via `DecodeByte` and on Linux via the misc-setting patch).

```
index 0x0B  current thermal profile (value = profile id)
index 0x0A  supported-profile bitmask (bit position = profile id);
            flagged "Unreliable on some models" in mainline acer-wmi
profile ids: 0 Quiet, 1 Balanced, 4 Performance, 5 Turbo, 6 Eco
```

- Verified set call: `EncodeProfile(modeId) = 0x0B | (modeId << 8)` (Windows) — matches `ACER_WMID_MISC_SETTING_PLATFORM_PROFILE = 0x000B` + value bits 15:8 (Linux).
- Linux platform-profile mapping (mainline `acer_predator_v4_platform_profile_*`): Turbo→`performance`, Performance→`balanced_performance`, Balanced→`balanced`, Quiet→`quiet`, Eco→`low-power` (`/sys/firmware/acpi/platform_profile`).
- Availability constraints (documented for the Acer stack): **Eco may require battery power; Turbo may require AC power** (https://github.com/derenma/acer_control README). Which of Eco/Turbo exist on AN515-45 firmware is model-dependent — read `0x0A` and degrade.
- Misc-setting status byte must be checked on *both* get and set: a firmware refusal still returns an ACPI success object with status≠0 (verified bug class in `patches/linuwu-sense-misc-setting-status.patch`).

### 4.4 Thermal trip points / `MSAcpi_ThermalZoneTemperature`

- **UNVERIFIED for AN515-45.** No community source documents the `MSAcpi_ThermalZoneTemperature` (root\wmi, deciKelvin `CurrentTemperature`) behavior on this model, and Acer gaming firmware is known to be inconsistent here. Do **not** make it a required dependency; use `GetGamingSysInfo` temps (§2.3) as the primary source and treat ACPI thermal zones as an optional cross-check.
- The firmware's own trip points/throttling are not exposed through the discovered gaming WMI interface (no register/offset for trip points was found). Assume firmware-managed throttling; the app should only observe, never claim to move trip points.
- Turbo/OC misc settings (`ACER_WMID_MISC_SETTING_OC_1 = 0x05`, `OC_2 = 0x07`, values 0 normal / 2 turbo) exist in the protocol but are gated behind the `turbo` quirk on models with a turbo key (Predator PH315-53 etc.). **Not verified on AN515-45** — see risks.

---

## 5. Power limits & cooling capability (chassis)

- **CPU**: Ryzen 5000H Cezanne, **45 W TDP** (configurable down to 35 W cTDP). Ryzen 7 5800H: 8C/16T, base 3.2 GHz (https://www.techpowerup.com/cpu-specs/ryzen-7-5800h.c2368; https://www.ultrabookreview.com/45156-acer-nitro-5-amd-review/). No user-facing sustained-TDP (PPT/STAPM) control was found in the gaming WMI interface — **UNVERIFIED** whether AcerAgentService exposes any. The app should not promise TDP control.
- **GPU TGP by SKU** (laptopmedia spec database for AN515-45, https://laptopmedia.com/series/acer-nitro-5-an515-45/ and https://laptopmedia.com/nl/review/acer-nitro-5-an515-45/):
  `RTX 3060 Laptop = 95 W`, `RTX 3070 Laptop = 100 W`, `RTX 3080 Laptop = 100 W`.
  Early-2021 BIOS/units showed lower actual TGP (owner reports of "85 W max" on a 3070 unit, https://www.techpowerup.com/forums/threads/acer-nitro-5-rtx3070-tdp-vbios-update.284578/, and "Nitro 5 80W 3060" discussions, https://www.reddit.com/r/GamingLaptops/comments/nrdd35/nitro_5_80w_3060_gpu_bios_flash_adventures/); a BIOS update "increases the dynamic boost to 15W, thus making the max TGP 95W" on the reviewed SKU (https://www.ultrabookreview.com/45156-acer-nitro-5-amd-review/). **Display TGP as reported by the driver (NVAPI/nvidia-smi), not as a hard-coded constant.**
- **Cooling hardware**: two fans (fan ids 0x01 CPU, 0x04 GPU in the firmware protocol — two independent duty targets and two RPM sensors). NitroSense "CoolBoost" ≈ +10 % fan speed vs auto (Acer marketing text above). Notebookcheck's AN515-45 review ("Acer Nitro 5 AN515-45 in review: Compact QHD gaming laptop", https://www.notebookcheck.net/Acer-Nitro-5-AN515-45-in-review-Compact-QHD-gaming-laptop.555911.0.html) exists but is Cloudflare-blocked to automated access — do not quote specifics from it beyond the title.
- Chassis/cooling capability notes (safe claims only): sustained CPU+GPU load is bounded by a shared heat-pipe design typical of the Nitro 5 class; the firmware fan tables govern acoustics/thermals, and Max mode is the ceiling. Precise thermal test data: UNVERIFIED (review pages inaccessible).

---

## 6. Concrete Windows integration points

Everything in this section is a verified identifier (source: `derenma/acer_control` code + `acer_analysis.md` + AN515-45 NitroSense strings + mainline `acer-wmi.c`). This is the integration contract NitroMaster should code against.

### 6.1 Primary firmware channel (no OEM software required; admin/elevation required)

```
WMI namespace : root\wmi
WMI class     : AcerGamingFunction   (single instance)
ACPI WMI GUID : 7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56
Method shape  : exactly one input parameter (integer or byte[16]);
                outputs: gmOutput (u64 or byte[]), gmReturn (byte status)

Methods:
  SetGamingFanBehavior(in u64)   GetGamingFanBehavior(in u32)  -> gmOutput u64
  SetGamingFanSpeed(in u64)      GetGamingFanSpeed(in u32)     -> gmOutput u64
  SetGamingMiscSetting(in u64)   GetGamingMiscSetting(in u32)  -> gmOutput u64
  SetGamingRgbKb(in u32)         GetGamingRgbKb(in u32)        -> gmOutput u64
  SetGamingKBBacklight(in byte[16])                            -> gmOutput u64/status
  GetGamingKBBacklight(in u32=1)                               -> gmReturn byte,
                                                                  gmOutput byte[]
  GetGamingSysInfo(in u32)                                     -> gmOutput u64
  SetGamingLEDBehavior(in u64)   GetGamingLEDBehavior(in u32)   -> gmOutput u64
```

Constant table (encode/decode, little-endian bitfields):

```
FAN_BEHAVIOR  fan bitmap   : 0x0009 = CPU(0x01) | GPU(0x04)
               mode set    : CPU bits 17:16, GPU bits 23:22 (1 Auto, 2 Max/Turbo, 3 Custom)
               mode get    : CPU bits  9:8,  GPU bits 15:14
               status      : bits 7:0 (0 = ok)
               known-good : Auto 0x00410009 | Max 0x00820009 | Custom 0x00C30009
FAN_SPEED     selector    : bits 7:0  (0x01 CPU, 0x04 GPU)
               percent    : bits 15:8 (0..100)
               reply      : status bits 7:0 (0 ok, 1 no device, 2 bad param),
                            value bits 15:8
SYS_INFO      selectors   : 0x0101 CPU temp °C, 0x0A01 GPU temp °C,
                            0x0201 CPU fan RPM, 0x0601 GPU fan RPM,
                            0x0000 supported-sensor bitmap
               reply      : status bits 7:0 (0 ok), reading bits 23:8
MISC_SETTING  index/value : index bits 7:0, value bits 15:8, reply status bits 7:0
               0x0B = thermal profile (0 Quiet, 1 Balanced, 4 Performance,
                       5 Turbo, 6 Eco); 0x0A = supported-profile bitmask
               0x88401 (get) = kbd backlight timeout: seconds in bits 63:40
RGB_KB        u32         : zone(0x01/0x02/0x04/0x08) | R<<8 | G<<16 | B<<24
KB_BACKLIGHT  byte[16]    : {mode, speed, brightness, waveFlag(8 if Wave),
                            direction, R, G, B, 0, 1, 0,0,0,0,0,0}
               modes      : 0 Static, 1 Breathing, 2 Neon, 3 Wave, 4 Shifting,
                            5 Zoom, 6 Meteor, 7 Twinkling
LED_BEHAVIOR  u64         : 8 | (15 << 40)  = KBL panel ON, all four zones
                            (send after GetGamingSysInfo(0), before colour writes)
```

### 6.2 OEM service channels (when the Acer stack is installed)

```
AcerAgentService (AASSvc)        127.0.0.1:46933   ACER-framed JSON API
     -> fan duty, performance profiles; normal user usually sufficient
AcerLightingService              127.0.0.1:6742    OpenRGB 0.7.0 server (protocol v3+)
     -> keyboard static color/brightness (AN17-42 verified; AN515-45 UNVERIFIED)
AcerDeviceEnablingServiceV2      127.0.0.1:51779-51782   ADESSocket JSON (ACER framing)
     -> privacy consent only; NOT needed for hardware control
AcerService.exe (XSense)         https://localhost:15152   warranty/driver backend
     -> irrelevant to hardware control
```

### 6.3 Registry / files touched by the Acer stack (for detection & conflict handling)

```
HKLM\SOFTWARE\OEM\ADESV2          : Consensus, FUB (enrollment token), Time
C:\ProgramData\OEM\AcerService\                 : hardware/driver inventory caches
C:\ProgramData\OEM\Acer Device Enabling Service V2\HOLA_UAT.ini   (UAT switch)
Acer packages bind to PnP software components on:
  ACPI\VEN_1025&DEV_165F&SUBSYS_10021025        ("Acer application base device",
                                                  subsystem class = Acer Nitro)
```

NitroSense's own per-setting storage location on AN515-45: **UNVERIFIED** (not documented in any located source). Do not depend on it; keep NitroMaster's own state store.

### 6.4 Detection checklist for the app

```
1. WMI root\wmi class AcerGamingFunction present?     -> full control path
2. DMI product name == "Nitro AN515-45" (or AN517-41) -> known-good profile
3. GetGamingMiscSetting(0x0A) supported-profile mask  -> which mode tiles to show
4. GetGamingSysInfo(0x0000) sensor bitmap             -> which gauges to show
5. GetGamingKBBacklight(1) returns >= 8 bytes         -> 4-zone RGB present
6. AcerAgentService TCP 46933 listening?              -> optional no-elev path
7. NitroSense key: capture scancode at runtime (extended 0x75 on newer models;
   AN515-45 UNVERIFIED) -> hook/launch integration
```

---

## 7. Unsupported / risky (must degrade gracefully)

1. **Raw EC / port I/O (0x62/0x66) on Windows** — would require a kernel driver; unsigned drivers are blocked on Win11, signed ones are a support/BSOD liability. Everything the app needs is reachable via `AcerGamingFunction`. **Do not ship an EC driver.**
2. **"Sandra" driver** — does not exist in any located evidence. If a design doc references it, remove the dependency.
3. **`MSAcpi_ThermalZoneTemperature`** — UNVERIFIED on this model; may return nothing or stale values. Optional telemetry only.
4. **OC misc settings (`0x05`/`0x07`, values 0/2)** — protocol exists (Predator turbo models) but is not verified on AN515-45 and could interact with firmware power limits unpredictably. Keep hidden behind an explicit "experimental" gate or omit.
5. **LCD override** — firmware answers `0xFF` = "not applicable on this model" on AN515-45 (measured: `0x00FF000001000000` regardless of writes that report success) — `patches/linuwu-sense-backlight-timeout-decode.patch`. Show as "unsupported on this model".
6. **Turbo button / turbo WMI event** — not present on AN515-45 (facer table: Turbo "-"). Do not offer a "Turbo key" toggle.
7. **Keyboard state persistence** — impossible to make firmware remember custom lighting across power cycles (boot default red). Re-apply on app start/resume; never report this as an error.
8. **Silent-success hazard** — this firmware routinely returns success for writes it ignores (RGB writes to a disabled panel, byte-8=3 payloads, LCD override writes). Always **read back** (`GetGamingKBBacklight`, `GetGamingRgbKb`, `GetGamingFanSpeed`, `GetGamingMiscSetting`) and verify; treat "success + wrong readback" as failure.
9. **Fan duty volatility** — custom duty is lost on resume/profile change/EC reclaim (`0,0` = firmware takes over). Re-assert on power events; warn that Max/Auto is always safe.
10. **Profile constraints** — Turbo may require AC, Eco may require battery; the set call can be refused via the status byte. Surface as informational, not fatal.
11. **Conflict with NitroSense/AcerAgentService/Acer services** — they overwrite fan/profile/RGB settings concurrently (documented warning in `derenma/acer_control`). Serialize writes; consider a "exclusive control" mode that stops/disables the conflicting Acer services only with explicit user consent (disabling `AASSvc` degrades other Acer features).
12. **`AcerLightingService`/OpenRGB on TCP 6742** — listens on all interfaces with permissive firewall rules on the analyzed unit; if NitroMaster uses it, connect to `127.0.0.1` only and warn the user (security note from `acer_analysis.md`).
13. **Elevation model** — direct WMI control needs admin; the no-admin path needs the Acer stack (`AASSvc` 46933). Plan for both and detect which is available.
14. **AN515-45 scancode for the N key on Windows** — UNVERIFIED; implement runtime detection (low-level keyboard hook) instead of a constant.
15. **Backlight timeout** — writable via the misc-setting path but decoding is field-based (bits 63:40 seconds); never compare against magic constants (verified upstream bug class).
16. **Gaming-sensor coverage** — only CPU/GPU temps and both fan RPMs are exposed; no VRM/SSD/acpi-trip data. Anything else needs LibreHardwareMonitor-class SIO/EC reads (out of scope / risky).

---

## Sources

Code-level (primary):
1. Mainline Linux `acer-wmi.c` (gaming method IDs, fan behavior/speed encoding, misc settings, predator-v4 sensors, platform profiles, quirks): https://github.com/torvalds/linux/blob/master/drivers/platform/x86/acer-wmi.c
2. `facer` kernel module (AN515-45 RGB tested; KB method IDs 20/21; static-LED id 6; fan behavior id 14): https://github.com/JafarAkhondali/acer-predator-turbo-and-rgb-keyboard-linux-module (src/facer.c, README compatibility table) — AN515-45 issue: https://github.com/JafarAkhondali/acer-predator-turbo-and-rgb-keyboard-linux-module/issues/63
3. AN515-45-specific measured findings (RGB enable sequence, EC registers, HW_Support.ini, NitroSense strings, boot-default red): https://github.com/participatory-doublethink2007/NitroSense-Linux-AN515-45 (docs-rgb-findings.md, patches/linuwu-sense-an515-45-rgb.patch, patches/linuwu-sense-backlight-timeout-decode.patch, patches/linuwu-sense-misc-setting-status.patch, scripts/capture-boot-lighting.sh, service/nitrosense-daemon.py, app/electron/nitro-key.ts, app/scripts/probe.ts)
4. Windows implementation of the same protocol (`root\wmi:AcerGamingFunction`, gmOutput/gmReturn, encode constants, profile IDs, fan readback): https://github.com/derenma/acer_control (installable_service/src/AcerControl.Service/Hardware/WmiAcerGamingInterface.cs, FirmwareProtocol.cs, AcerHardwareController.cs, acer-control.ps1)
5. Acer Windows stack teardown (services, kernel drivers, AcerAgentService 46933, OpenRGB 6742, ADES, registry, ACPI\VEN_1025&DEV_165F): https://github.com/derenma/acer_control/blob/main/acer_analysis.md and https://github.com/derenma/acer_control/blob/main/SERVICES_AND_TOOLS.md
6. NitroSense key remapping/scancode tooling (extended scancode 0x75, hook-based detection): https://github.com/derenma/acer_control/blob/main/key-remap/README.md ; https://github.com/Ricardokraus/Win11-Key-Remapper-Acer-Nitrosense
7. `Div-Linuwu-Sense` driver (nitro_v4 / four_zone_kb quirks; parent of the AN515-45 patch): https://github.com/PXDiv/Div-Linuwu-Sense ; GUI: https://github.com/PXDiv/Div-Acer-Manager-Max
8. DAM Fan Controls (WMI fan-control suite; alternate raw fan-range warning): https://github.com/PXDiv/Div-Acer-Manager-Fan-Controls
9. Mainline acer-wmi 4-zone keyboard RFC (referenced by the AN515-45 findings; `ACER_GAMING_KBL_SET_ON = BIT(3)`, `ACER_GAMING_KBL_SET_ALL_ZONES`): https://ratatoskr.run/platform-driver-x86/2026/05/3541436/t (page blocks automated fetch; content as cited/quoted in source 3)

Hardware / platform identity & limits:
10. Schematic/boardview packages "Acer Nitro 5 AN515-45 AN517-41 LA-L031P GH53Z Rev 1A": https://diskrekuperar.com.br/products/pacote-de-esquemas-eletricos ; https://thetechstall.com/acer-nitro-5-an515-45-gh53z-la-l031p-schematic-diagram/ ; BIOS request thread (Rev 1B, AN515-45-R77J / N20C1): https://www.badcaps.net/forum/troubleshooting-hardware-devices-and-electronics-theory/troubleshooting-laptops-tablets-and-mobile-devices/bios-requests-only/103327-hello-i-need-bios-dump-for-gh53z-la-l031p-rev-1b/page2 ; https://bioshelp.com/forum-acer-laptop-bios.html
11. GPU TGP options (RTX 3060 95 W / 3070 100 W / 3080 100 W): https://laptopmedia.com/series/acer-nitro-5-an515-45/ ; https://laptopmedia.com/nl/review/acer-nitro-5-an515-45/
12. BIOS/Dynamic Boost TGP discussion: https://www.ultrabookreview.com/45156-acer-nitro-5-amd-review/ ; https://www.techpowerup.com/forums/threads/acer-nitro-5-rtx3070-tdp-vbios-update.284578/ ; https://www.reddit.com/r/GamingLaptops/comments/nrdd35/nitro_5_80w_3060_gpu_bios_flash_adventures/
13. CPU TDP 45 W (Ryzen 7 5800H, Cezanne): https://www.techpowerup.com/cpu-specs/ryzen-7-5800h.c2368 ; https://wccftech.com/amd-ryzen-7-5800h-8-core-16-thread-cezanne-zen-3-cpu-shows-up/
14. CoolBoost marketing numbers: https://global.microless.com/product/acer-nitro-5-an515-45-r1jm-15-6-fhd-ips-gaming-laptop-amd-ryzen-9-5900hx-nvidia-geforce-rtx-3080-gpu-32gb-ddr4-ram-1tb-ssd-mouse-headset-mousepad-windows-10-shale-black-nh-qbsem-003/
15. Notebookcheck AN515-45 review (title only; body blocked to automated access): https://www.notebookcheck.net/Acer-Nitro-5-AN515-45-in-review-Compact-QHD-gaming-laptop.555911.0.html
16. Additional community tooling pointers (not relied on for facts): Windows RGB flash helper https://github.com/AmmarHSufyan/NitroPulse ; stack reimplementation https://github.com/KRWCLASSIC/OpenPredator ; Java NitroSense frontend https://github.com/robothaver/Java-NitroSense
