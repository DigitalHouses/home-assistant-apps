# DH PVE Simplified Runtime, MQTT and HAOS Design

Date: 2026-09-15
Status: canonical design for the next `dh_pve_app` refactor
Target runtime: Proxmox VE 8.x
Branch at design time: `design/dh-pve-observability-ups-trigger-v2`

## Why this design replaces the previous observability plan

The previous Runtime Observability design treated expensive polling (`pvesh`, `qm`, `pct`, `pvesm`, guest exec and related subprocesses) as an architecture to instrument and measure. The new decision is to simplify the architecture first: do not repeatedly execute a heavy command when the same information is already available from local kernel/PVE files or PVE-maintained status cache.

Therefore the old Runtime Observability design and its implementation plan are removed. Command-level 60-second observability, an instrumented subprocess runner and command timing aggregation are not the first implementation target anymore. After the simplified runtime is running on the home PVE, add only the minimum observability that production evidence proves useful.

This document also defines the target Home Assistant contract discovered by reverse engineering the existing PVE/UPS dashboards and HA packages.

## Core principles

1. **PVE 8.x only.** Internal PVE file/cache formats may be used deliberately. We do not add compatibility complexity for other major PVE versions in this refactor.
2. **Files/cache first.** Prefer `read()` over spawning a process.
3. **Collection cadence is fixed.** System load never makes `dh_pve_app` collect more aggressively.
4. **Adaptive behavior affects MQTT publication only.** It is domain-local and cannot trigger extra digging, subprocesses or guest commands.
5. **HAOS is a light client.** The app owns data acquisition, averages, derived values, thresholds and problem states. HAOS displays, records selected history and sends notifications.
6. **Recorder is explicit.** Historical numeric telemetry is flat and attribute-light. Presentation/diagnostic objects with richer attributes are excluded from Recorder.
7. **Events are immediate.** Important discrete state changes do not wait for a 5/15-minute telemetry publication window.
8. **No destructive validation.** No FSD, UPS output-off, mains-unplug or deep-discharge validation is part of the refactor release gate.

---

## 1. Source architecture

### 1.1 Source priority

Use this order whenever possible:

```text
1. /proc, /sys
2. /etc/pve configuration and PVE-maintained cache/status files
3. subprocess only when the data does not exist in a cheap local source
4. pvesh/API only for rare/on-demand cases or actions, not normal monitoring polling
```

Important PVE sources include, where suitable for PVE 8.x:

```text
/etc/pve/qemu-server/*.conf
/etc/pve/lxc/*.conf
/etc/pve/storage.cfg
/etc/pve/.vmlist
/etc/pve/.rrd
/etc/pve/.version
/proc/*
/sys/*
```

The implementation must verify the exact PVE 8.x schema it consumes and cover it with fixtures/tests.

### 1.2 No automatic heavy fallback loop

Do **not** implement this behavior:

```text
file/cache read failed
  -> silently use pvesh/qm/pct every poll forever
```

If a supported PVE 8.x source cannot be parsed/read, expose the affected subsystem as unavailable/problem and log a useful transition. A fallback may exist only when explicitly designed and must not turn a source failure into a permanent high-load polling mode.

### 1.3 Static data

Static/configuration data is not periodically polled.

Read it on:

```text
startup
+ relevant /etc/pve change/version change
+ Manual Refresh
```

Examples:

- VM/LXC configuration;
- startup/shutdown order and timeout configuration;
- PCI passthrough topology;
- hardware inventory;
- PVE/kernel version;
- board/RAM inventory.

---

## 2. Fixed collection cadence

The initial production baseline intentionally has very few cadence classes and roughly an order-of-magnitude difference between them.

| Class | Interval | Initial responsibility |
|---|---:|---|
| `FAST` | 10 s | CPU usage, CPU temperature, CPU frequency, RAM, Swap, fans |
| `UPS` | 10 s | NUT runtime state, battery, runtime, load, voltages, status flags |
| `SLOW` | 1 min | storage percent used, disk temperature, GPU/transcoding, light runtime diagnostics |
| `HEALTH` | 1 h | full SMART/health, wear/counters, PVE runtime cache such as VM/LXC status and host load |
| `STATIC` | event | startup/change/manual-refresh configuration and inventory |

This is an **initial baseline**. We will tune it only after observing real production data.

### 2.1 Manual Refresh

Manual Refresh requests a complete current snapshot:

```text
STATIC
FAST
SLOW
HEALTH
UPS
```

Potentially expensive HEALTH work must run sequentially, not as a parallel burst.

### 2.2 No user poll controls

Remove runtime controls such as fast/disk poll interval MQTT numbers. Collection cadence is an internal app contract, not a Home Assistant setting.

---

## 3. MQTT publication model

Collection and publication are independent.

Initial publication baseline:

```text
NORMAL = every 15 min
DETAIL = every 5 min
EVENTS / PROBLEM TRANSITIONS = immediately
```

### 3.1 Domain-local DETAIL

DETAIL is selected independently per domain. Example domains:

```text
cpu
memory
storage
disk
gpu
cooling
ups
```

If CPU enters DETAIL, only CPU telemetry publishes on the DETAIL cadence. GPU/storage/UPS remain in their own profiles.

A profile change **must never**:

- increase collection frequency;
- start additional diagnostics;
- trigger `pvesh`/`qm`/`pct`/guest exec;
- increase SMART frequency;
- cause automatic "digging".

It only changes MQTT publication cadence for that domain.

### 3.2 Averages and profile decisions

Use averaged values for profile decisions and publication. Initial decision logic has no hysteresis.

Strict comparison semantics:

```text
average > threshold  -> DETAIL / problem ON
average < threshold  -> NORMAL / problem OFF
average == threshold -> keep current state
```

No `>=` or `<=` transition semantics.

Internal publication-profile thresholds are **not** exposed to HAOS. They live under the hood and are documented defaults. Tune them from production evidence later.

### 3.3 Immediate states

Discrete events/problems are change-oriented and publish immediately, independent of NORMAL/DETAIL telemetry cadence. Examples:

- UPS OL/OB/LB/FSD/alarm transitions;
- threshold problem ON/OFF;
- SMART problem transition after HEALTH detects it;
- CPU throttling transition;
- VM/LXC state transition when the runtime source is refreshed;
- collector/data-source failure/recovery;
- profile transition.

---

## 4. Home Assistant responsibility boundary

### 4.1 App owns

`dh_pve_app` owns:

- source acquisition;
- parsing;
- averages;
- derived values;
- publication profiles;
- user alert thresholds and their persistence/defaults;
- threshold comparison;
- problem binary states;
- compact presentation summaries needed by UI;
- UPS/NUT interpretation;
- shutdown history/evidence already owned by the app.

### 4.2 HAOS owns

HAOS owns:

- display/layout;
- explicit Recorder whitelist;
- notification delivery and repeat policy;
- site-specific notification gates;
- user interaction with MQTT Discovery controls.

`binary_sensor.bs_global_system_boot_completed` remains **HAOS-only**. It means HAOS has booted successfully and is safe to run HA-side notification automations. It is not moved into `dh_pve_app`.

### 4.3 Remove business logic from Lovelace/packages

The target UI must not repeatedly:

- scan all `states.sensor` / `states.binary_sensor`;
- join related entities by attributes;
- calculate thresholds;
- calculate storage used from percentage and total;
- construct VM/LXC/PCI topology;
- calculate warning state/color from multiple raw entities;
- format complex shutdown timelines from raw fields in many cards.

The app should provide a ready numeric entity, problem binary or non-Recorder presentation entity/attribute instead.

HA packages should converge toward:

```text
Recorder whitelist
+ notification automations
```

not a second application layer.

---

## 5. MQTT Discovery naming

Canonical entity prefixes:

```text
PVE: dh_app_pve_*
UPS: dh_app_pve_ups_*
```

Do not preserve legacy `digitalhouses_proxmox_*`, `dh_pve_*` or `myups_*` naming merely for historical compatibility in the new contract. Migration/cleanup must be explicit.

---

## 6. Home Assistant device-page grouping

There will be many entities. Discovery metadata is part of the UX contract.

### Main sensors

Normal telemetry/presentation entities have no `entity_category` unless they are purely diagnostic/configuration objects.

### Configuration

Use:

```text
entity_category: config
```

for user-settable configuration such as:

- alert threshold MQTT numbers;
- UPS battery-test schedules;
- scheduled-test beeper behavior;
- later approved UPS policy configuration controls.

### Diagnostics / problems

Use:

```text
entity_category: diagnostic
device_class: problem
```

for problem binaries where appropriate. This keeps thresholds and their resulting problem binaries in separate device-page groups.

Low-level technical debug entities may additionally use:

```text
enabled_by_default: false
```

so the default device card remains readable.

### Controls

Real actions remain normal controls, for example Refresh, battery-test buttons and the physical UPS beeper switch.

---

## 7. Recorder contract

Do not use broad globs such as:

```text
sensor.dh_app_pve_*
binary_sensor.dh_app_pve_*
```

Recorder uses an explicit whitelist.

### 7.1 Recorded PVE telemetry

Record useful historical numeric telemetry, including even if the old package did not yet list it:

```text
sensor.dh_app_pve_cpu_usage
sensor.dh_app_pve_cpu_temperature
sensor.dh_app_pve_cpu_frequency
sensor.dh_app_pve_memory_usage
sensor.dh_app_pve_swap_usage
sensor.dh_app_pve_fan_<id>_rpm
sensor.dh_app_pve_disk_<id>_temperature
sensor.dh_app_pve_disk_<id>_wear
sensor.dh_app_pve_storage_<id>_percent_used
sensor.dh_app_pve_gpu_<id>_temperature
sensor.dh_app_pve_gpu_<id>_transcoding
```

Recorded telemetry should have very few dynamic attributes. Prefer state + native HA metadata only.

### 7.2 Presentation/diagnostic entities

Entities whose purpose is UI composition, topology, history lists, policy descriptions or diagnostics are not written to Recorder. They may carry richer attributes because they are outside the time-series path.

---

## 8. Alert thresholds and problem binaries

Replace HA `input_number` threshold helpers with MQTT Discovery `number` entities owned by the app.

Initial threshold controls:

```text
number.dh_app_pve_storage_percent_used_threshold
number.dh_app_pve_cpu_temperature_threshold
number.dh_app_pve_hdd_temperature_threshold
number.dh_app_pve_ssd_temperature_threshold
number.dh_app_pve_nvme_temperature_threshold
number.dh_app_pve_gpu_temperature_threshold
```

Initial defaults remain:

```text
storage percent used  80 %
CPU temperature       90 C
HDD temperature       45 C
SSD temperature       75 C
NVMe temperature      80 C
GPU temperature       85 C
```

The app validates, persists and republishes the effective value. HA does not use `0 = default` and does not initialize defaults on startup.

### 8.1 Pair model

The basic model is deliberately simple:

```text
MQTT number threshold
+ problem binary
```

No extra enable/disable switch is added for ordinary alerts.

Examples:

```text
number.dh_app_pve_cpu_temperature_threshold
binary_sensor.dh_app_pve_cpu_temperature_problem

number.dh_app_pve_storage_percent_used_threshold
binary_sensor.dh_app_pve_storage_<id>_percent_used_problem

number.dh_app_pve_nvme_temperature_threshold
binary_sensor.dh_app_pve_disk_<id>_temperature_problem
```

When either the measured average **or the threshold itself** changes, the app immediately reevaluates the problem binary. Therefore HA needs no special `threshold_changed` automation.

Individual problem binaries are the automation trigger contract:

```text
OFF -> ON = alert
ON -> OFF = recovery
```

### 8.2 Aggregate PVE problems

Provide a non-Recorder presentation entity such as:

```text
sensor.dh_app_pve_problems
```

Its state is total active problem count. Compact category counts/details may be attributes, for example:

```text
temperature: 1
storage: 1
smart: 0
throttling: 0
data: 1
severity: warning
summary: "Обнаружено проблем: 3"
```

The UI must not rescan every entity to calculate this.

---

## 9. PVE presentation entities

Presentation entities are non-Recorder by default.

### 9.1 System overview

Keep a system overview entity, for example:

```text
sensor.dh_app_pve_system
```

The app provides the already formatted summary in this order:

```text
Manufacturer
Model
CPU
MB
RAM
FAN
Proxmox version / Kernel
IP
```

Hardware/cooling is intentionally shown before PVE software version.

### 9.2 Storage

Canonical metric naming is **percent used**:

```text
sensor.dh_app_pve_storage_<id>_percent_used
binary_sensor.dh_app_pve_storage_<id>_percent_used_problem
number.dh_app_pve_storage_percent_used_threshold
```

A non-Recorder overview may expose `used_gib`, `free_gib`, `total_gib` and a ready `summary` for the UI.

### 9.3 Physical disks

Keep separate recorded telemetry for temperature/wear and separate problem binaries for temperature/SMART. A non-Recorder overview may combine model/type/current temperature/wear/SMART health into a ready UI summary so Lovelace does not perform entity joins.

Detailed SMART diagnostics belong in a non-Recorder diagnostic entity or attributes, not on continuously recorded telemetry.

### 9.4 VM/LXC topology

The app owns topology composition. A non-Recorder entity may provide a ready display string/list for VM, LXC and PCI passthrough instead of Lovelace looping over all entities.

Existing per-guest state/shutdown evidence may remain where useful, but presentation joins belong in the app.

### 9.5 Shutdown history

Preserve the canonical app-owned shutdown history and clean/unclean/reason separation. UI summary/timeline formatting should move into app-provided presentation data instead of repeated Jinja calculations.

Do not change destructive UPS/FSD behavior as part of this simplification refactor.

---

## 10. UPS Discovery contract

Canonical prefix:

```text
dh_app_pve_ups_*
```

### 10.1 Primary telemetry

Initial core sensors include:

```text
sensor.dh_app_pve_ups_status
sensor.dh_app_pve_ups_battery_charge
sensor.dh_app_pve_ups_battery_runtime
sensor.dh_app_pve_ups_battery_voltage
sensor.dh_app_pve_ups_load
sensor.dh_app_pve_ups_input_voltage
sensor.dh_app_pve_ups_output_voltage
sensor.dh_app_pve_ups_nominal_real_power
sensor.dh_app_pve_ups_power
```

For current real power:

1. use NUT `ups.realpower` when available;
2. otherwise use `ups.realpower.nominal * ups.load / 100` as the documented fallback calculation.

Do not invent an app energy accumulator in this refactor unless a real UI/reporting requirement is confirmed later.

### 10.2 NUT status interpretation

Interpret standard NUT `ups.status` tokens and expose corresponding binary sensors:

| NUT token | Discovery suffix | Meaning |
|---|---|---|
| `OL` | `online` | online / utility present |
| `OB` | `on_battery` | on battery |
| `LB` | `low_battery` | low battery |
| `HB` | `high_battery` | high battery |
| `RB` | `replace_battery` | replace battery |
| `CHRG` | `charging` | charging |
| `DISCHRG` | `discharging` | discharging |
| `BYPASS` | `bypass` | bypass active |
| `CAL` | `calibration` | calibration/runtime test |
| `OFF` | `off` | UPS output/load is off |
| `OVER` | `overload` | overload |
| `TRIM` | `trim` | high input voltage / trim state |
| `BOOST` | `boost` | low input voltage / boost state |
| `FSD` | `forced_shutdown` | forced shutdown state |
| `ALARM` | `alarm` | alarm present |

Also expose NUT communication availability separately:

```text
binary_sensor.dh_app_pve_ups_available
```

Unknown future NUT status tokens must not break the parser.

### 10.3 UPS status sensor and Russian text

`sensor.dh_app_pve_ups_status` is a mandatory Recorder entity and is used by the UPS Logbook.

Keep its attributes intentionally tiny and stable. At minimum:

```text
raw_status
status_ru
```

`status_ru` is a human-readable Russian interpretation of the current token combination, for example:

```text
OL            -> Работает от сети
OB            -> Работает от батареи
CHRG          -> Заряжается
DISCHRG       -> Разряжается
LB            -> Низкий заряд
RB            -> Требуется замена батареи
BYPASS        -> Байпас
BOOST         -> Повышенное напряжение
TRIM          -> Пониженное напряжение
OVER          -> Перегрузка
FSD           -> Аварийное отключение
ALARM         -> Авария
CAL           -> Калибровка
OFF           -> Выход UPS отключён
```

For multiple tokens, compose a readable string, for example:

```text
raw_status: "OB DISCHRG"
status_ru: "Работает от батареи · Разряжается"

raw_status: "OL BOOST"
status_ru: "Работает от сети · Повышенное напряжение"
```

The status state itself and selected event binaries provide the chronological UPS picture in Recorder/Logbook. Charging/discharging Recorder noise should be assessed from real production data before expanding the whitelist unnecessarily.

### 10.4 UPS problems

Provide a non-Recorder aggregate presentation entity such as:

```text
sensor.dh_app_pve_ups_problems
```

Individual NUT/problem binaries remain the automation/logbook contract.

---

## 11. UPS controls and battery-test scheduler

Real controls remain controls:

```text
button.dh_app_pve_ups_refresh
button.dh_app_pve_ups_test_quick
button.dh_app_pve_ups_test_deep
button.dh_app_pve_ups_test_stop
switch.dh_app_pve_ups_beeper
```

Scheduled tests have per-test beeper configuration:

```text
number.dh_app_pve_ups_quick_test_interval_days
time.dh_app_pve_ups_quick_test_time
switch.dh_app_pve_ups_quick_test_beeper

number.dh_app_pve_ups_deep_test_interval_days
time.dh_app_pve_ups_deep_test_time
switch.dh_app_pve_ups_deep_test_beeper
```

Scheduled-test behavior:

```text
remember current physical beeper state
-> set beeper to the schedule's requested state
-> start the scheduled test
-> on passed/failed/stopped/other completion, restore original beeper state
```

Example requirement: a scheduled Deep test may run with beeper OFF without permanently changing the normal UPS beeper setting.

Manual Quick/Deep tests use the current physical beeper state and do not temporarily override it.

Support for scheduling a deep test does **not** make deep-discharge testing part of deployment validation.

Battery-test history may be exposed as a non-Recorder presentation/history entity.

---

## 12. HA notification model

The old packages are behavioral references only; their legacy entity names and template implementation are not retained.

### PVE

HA notifications react to app-owned state transitions:

```text
*_problem OFF -> ON  -> alert
*_problem ON -> OFF  -> recovery
SMART problem ON     -> critical notification
SMART still ON       -> HA may repeat hourly
CPU throttling ON/OFF -> alert/recovery
```

Notification repetition and delivery belong to HAOS, not the app.

PVE boot notification may still use the HAOS-only gate:

```text
binary_sensor.bs_global_system_boot_completed == ON
+ recent app-provided PVE boot information
-> notification
```

### UPS

HA reacts to app-provided UPS states, for example:

```text
on_battery OFF -> ON -> mains-lost notification
on_battery ON -> OFF -> mains-restored notification
LB/OVER/RB/FSD/ALARM -> appropriate notification
```

HA never initiates Proxmox shutdown. NUT/PVE remains the shutdown authority.

---

## 13. Publication diagnostics

Replace old global `quiet/normal/high/critical` publication semantics with the two-profile model.

A non-Recorder diagnostic entity may show overall/current domain state, for example:

```text
sensor.dh_app_pve_publication_profile
```

with compact attributes:

```text
cpu: NORMAL
memory: NORMAL
storage: NORMAL
disk: DETAIL
gpu: NORMAL
ups: NORMAL
```

Also keep a lightweight non-Recorder last-publication diagnostic if useful.

These are diagnostic entities, not control knobs.

---

## 14. Initial implementation order

The next implementation session should proceed in this order and use TDD:

1. **Source audit:** map every current collector/field to current source and target cheap source.
2. **PVE 8.x readers:** implement/test file/cache parsers before changing publication behavior.
3. **Remove normal heavy polling:** eliminate unnecessary `pvesh`, `qm`, `pct`, `pvesm`, QGA probes and repeated inventory commands where files/cache satisfy the requirement.
4. **Fixed scheduler:** implement `FAST=10s`, `UPS=10s`, `SLOW=1m`, `HEALTH=1h`, `STATIC=event`.
5. **Publication model:** domain-local `NORMAL=15m`, `DETAIL=5m`, averages, strict `>/<`, no hysteresis, immediate events.
6. **Discovery contract:** migrate names, thresholds, problem binaries, entity categories and UPS NUT status contract.
7. **Presentation layer:** move heavy Lovelace calculations/joins into non-Recorder app presentation data.
8. **HA package/UI:** replace broad Recorder globs with whitelist; simplify package to Recorder + notifications; simplify UI to display ready entities.
9. **Full CI and diff review.** Verify no hidden heavy fallback loops and no increased collection cadence under load.
10. **Home PVE deploy (`192.168.11.30`) and non-destructive validation.** User performs CLI deploy/validation from commands prepared in chat.
11. **Tune from real data.** Only after production evidence, adjust collection/publication intervals, profile thresholds or additional observability.

Do not begin UPS Trigger Policy v2 behavior changes as part of this refactor unless explicitly re-approved after the simplified runtime is validated.

---

## 15. Production validation questions

After deployment, collect real evidence for:

- `dh_pve_app` CPU/RSS under normal operation;
- whether file/cache readers eliminate the previous subprocess spikes;
- Recorder row/update rate with NORMAL 15m / DETAIL 5m;
- usefulness of 15m normal graphs and 5m detailed graphs;
- stability of average-based profile switching without hysteresis;
- whether `HEALTH=1h` makes VM/LXC/status or SMART visibility too stale in real use;
- whether UPS charging/discharging flags create excessive Logbook/Recorder noise;
- Manual Refresh latency and peak load;
- device-page readability with Configuration / Diagnostics grouping.

Tune only from those observations rather than adding speculative complexity.

## Non-goals for the first refactor release

- PVE 9 compatibility.
- automatic load-triggered deep diagnostics.
- adaptive collection cadence.
- custom arbitrary Home Assistant grouping beyond supported Discovery metadata.
- HA-side threshold computation.
- HA-side PVE shutdown decisions.
- destructive FSD/UPS-output/deep-discharge deployment testing.
- reimplementation of a large command-level observability framework before the simplified runtime is measured.
