# Module Contracts — public API summary

Signatures that other modules rely on. All codecs/parsers are pure and OS-independent.

## core/monitoring/sensors_backend.py
- `encode_fan_behavior(cpu_mode, gpu_mode, fan_bitmap=0x09) -> int`
- `decode_fan_behavior_reply(value) -> (cpu_mode, gpu_mode, status)`
- `encode_fan_speed(selector, percent) -> int` · `decode_fan_speed_reply(value) -> (status, percent)`
- `decode_sysinfo_reply(value, mask) -> Optional[int]`
- `encode_rgb_kb(zone_mask, r, g, b) -> int` · `encode_kb_backlight(mode, speed, brightness, r, g, b, direction=0) -> bytes[16]`
- `decode_kb_backlight_reply(data) -> Optional[dict]`
- `encode_misc_setting(index, value) -> int` · `decode_misc_setting_reply(value) -> (status, value)`
- `AcerWmiBackend`: `set/get_fan_behavior`, `set/get_fan_speed`, `apply_custom_duty`,
  `read_sysinfo`, `read_sensors -> AcerSensorReading`, `set/get_thermal_profile`,
  `get_supported_profiles`, `enable_keyboard_panel`, `set_zone_color`, `set_kb_effect`,
  `get_kb_state` — raises `AcerWmiError` on transport failure, returns firmware status bytes
- `LhmBridge`: `available`, `read() -> dict[(group, name), float]`, `close()`

## core/monitoring
- `CpuMonitor.sample() -> CpuSample(usage_total, usage_per_core, effective_mhz, nominal_mhz, temp_c, temp_source, core_count, thread_count)`
- `RamMonitor.sample() -> RamSample(total, used, available, percent, used_gb, total_gb)`
- `GpuMonitor.sample() -> GpuSample(nvidia: NvidiaSample|None, amd: AmdSample|None, gpu_temp_c, gpu_fan_rpm, cpu_fan_rpm, temp_source)`

## core/power
- `PowerCfg`: `get_active_scheme`, `list_schemes`, `set_active`, `set_values`,
  `query`, `export_scheme`, `import_scheme`, `duplicate_scheme`, `delete_scheme`, `rename_scheme`
- Parsers: `parse_scheme_list`, `parse_active_scheme`, `parse_query` (locale-tolerant)
- `BaselineManager`: `ensure_captured`, `capture -> Baseline`, `restore -> list[str]`
- `ModeEngine.specs() -> dict[str, ModeSpec]`; `apply(mode_key) -> list[ModeStepResult]`
- `ProcessPolicy`: `set_ecoqos`, `throttle`, `restore`, `restore_all`, `suspend`, `resume`, `resume_all`, `throttle_all_except`
- `ServiceManager`: `snapshot(names)`, `stop(names)`, `restore()`
- `FocusMode`: `start(pid=None) -> int`, `stop() -> int`, `set_focus(pid)`

## core/cooling
- `FanCurve`: `duty_for(temp_c) -> int`, `to_dict/from_dict`, `default_cool()`
- `FanController`: `set_profile(profile, cpu_duty, gpu_duty)`, `refresh_state()`,
  `start_curve(temp_fn, interval_s)`, `stop_curve()`, `curve_running`, `curve_duty`
- `KeyboardBacklight`: `set_zone(i, ZoneColor)`, `set_all_zones`, `set_effect`,
  `set_brightness`, `off`, `restore`, `readback`
- `ambient_sync`: `dominant_color(samples, min_chroma, dark_cutoff) -> Color`,
  `region_samples(bgra, w, h, n) -> list[list[Color]]`, `lerp_color`, `lerp_state`,
  `ScreenSampler.grab() -> (w, h, bgra)`,
  `AmbientSyncEngine(keyboard, acer, interval_s, fade, per_zone, sampler)`:
  `start()/run()`, `tick() -> list[Color]`, `stop(persist=True)`, `running`

## core/graphics
- `format_gpu_pref(pref) -> "GpuPreference=N;"` · `parse_gpu_pref(data) -> int`
- `GpuSwitcher`: `set_preference`, `get_preference`, `clear_preference`,
  `list_preferences`, `export_backup`, `restore_backup`
- `AppProfileStore`: `list`, `add`, `remove`, `apply_all`, `apply_mode(mode_key)`

## core/workers
- `HardwarePollWorker(cpu, ram, gpu, interval_s)` → signal `sample_ready(dict)`
- `ModeApplyWorker(engine, mode_key)` → signals `finished(str, list)`, `failed(str, str)`

## utils
- `admin.is_admin()`, `admin.relaunch_as_admin(argv)`, `admin.run_elevated(cmd)`
- `state_store.StateStore`: `load(key, default)`, `save(key, data)`, `delete(key)`
- `platform.IS_WINDOWS`, `platform.require_windows(feature)`
