# DH PVE Simplified Runtime, MQTT, HAOS and UPS Trigger Policy v2 Design

Date: 2026-09-15
Status: canonical design — freeze candidate; production code must not change until this document is reviewed and frozen
Target runtime: Proxmox VE 8.x
Branch at design time: `design/dh-pve-observability-ups-trigger-v2`

## Authority and supersession

This document is the canonical architecture for the next `dh_pve_app` development cycle.

It supersedes the deleted Runtime Observability design/plan and supersedes older UPS policy documents wherever they conflict with this document. Older UPS documents remain historical implementation input only.

The previous plan to preserve heavy polling and add an instrumented subprocess runner plus 60-second `COMMANDS` / `COLLECTORS` / `PERF` summaries is not the target architecture. The first objective is to remove unnecessary work by using cheap PVE 8.x local sources.

The previous statement that UPS Trigger Policy v2 is postponed is cancelled. **UPS Trigger Policy v2 is part of this development cycle**, after the simplified source/runtime foundation and UPS telemetry improvements are in place.

## Core principles

1. **PVE 8.x only.** Internal PVE 8.x file/cache formats may be used deliberately and must be fixture-tested.
2. **Files/cache first.** Prefer local reads over subprocesses.
3. **Fixed collection cadence.** System load never causes faster acquisition.
4. **Adaptive publication only.** NORMAL/DETAIL changes MQTT publication cadence, never acquisition cadence or diagnostic depth.
5. **HAOS is a light client.** The app owns acquisition, parsing, averages, calculations, thresholds, problems, topology, presentation and NUT interpretation.
6. **PVE/NUT is the only shutdown authority.** HAOS configures and displays policy; it never decides or commits host shutdown.
7. **Recorder is explicit.** Useful time-series telemetry is whitelisted; rich presentation/events are excluded.
8. **Meaningful transitions are immediate.** They do not wait for 5/15-minute telemetry publication.
9. **No destructive validation.** No casual FSD, UPS output-off, mains unplug, deep discharge, HA-side shutdown or arbitrary shell/upscmd over MQTT.

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

Candidate PVE 8.x sources include:

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

Every internal PVE structure consumed by the app must have an explicit parser contract and fixtures from supported PVE 8.x data.

### 1.2 No automatic heavy fallback loop

The following is forbidden:

```text
file/cache read failed
  -> silently use pvesh/qm/pct/pvesm every poll forever
```

If a supported source becomes unreadable or unparsable, expose that subsystem as unavailable/problem and log a transition. A subprocess/API fallback may exist only when explicitly designed for that field and must not turn source failure into permanent high-load polling.

### 1.3 pmxcfs and STATIC correctness

`/etc/pve` is pmxcfs/FUSE. Filesystem notification such as inotify is **not** a correctness mechanism. It may only be an optimization.

STATIC/configuration data is refreshed on:

```text
startup
+ detected /etc/pve/.version change
+ reliable local event when available (optimization only)
+ Manual Refresh
```

`/etc/pve/.version` is checked on every SLOW cycle. A version change triggers reread of relevant STATIC/configuration data.

STATIC examples:

- VM/LXC configuration;
- startup/shutdown order and timeout configuration;
- PCI passthrough topology;
- hardware inventory;
- PVE/kernel version;
- board/RAM inventory.

---

## 2. Fixed collection cadence

Collection cadence is an internal app contract and is not user-configurable from HAOS.

| Class | Interval | Responsibility |
|---|---:|---|
| `FAST` | 10 s | CPU usage, CPU temperature, CPU frequency, RAM, Swap, fans |
| `UPS` | 10 s | NUT runtime state, battery/runtime/load/voltages/status/charger data |
| `SLOW` | 1 min | storage percent used, disk temperature, GPU/transcoding, VM/LXC runtime status, host load, light runtime diagnostics, `/etc/pve/.version` check |
| `HEALTH` | 1 h | full SMART/health, wear, SMART counters and genuinely heavy health diagnostics |
| `STATIC` | event | startup/version-change/reliable-event/manual-refresh configuration and inventory |

Collection **never** accelerates because CPU, memory, disk, GPU or UPS state becomes busy/critical.

### 2.1 Manual Refresh

Manual Refresh requests one complete current snapshot:

```text
STATIC
FAST
SLOW
HEALTH
UPS
```

Potentially expensive HEALTH operations run sequentially, not as a parallel burst.

A Manual Refresh also recalculates shutdown-policy derived values from current Proxmox configuration, current guest runtime state and persisted shutdown history.

### 2.2 Remove poll controls

Legacy MQTT controls for collector/poll intervals are removed. Collection cadence is not part of the HA configuration surface.

### 2.3 Fan RPM acquisition and physical-presence confirmation

Fan RPM acquisition remains a zero-subprocess FAST path.

Canonical source:

```text
/sys/class/hwmon/hwmon*/fan*_input
```

The raw hwmon collector reports every readable `fan*_input` channel exactly as Linux exposes it. Raw observation and physical-fan inventory are separate concepts: a Super I/O driver may export unused tachometer inputs that permanently read `0 RPM`.

Stable fan identity is derived from:

```text
hwmon chip name
+ resolved underlying device identity
+ fan channel/index
```

The volatile `hwmonN` number is not part of stable identity. `fan*_label`, when present, is display metadata only.

A newly observed channel starts as an unconfirmed candidate. It becomes confirmed only after **two consecutive valid FAST observations with RPM > 0**. A zero or invalid/unreadable observation before confirmation resets the positive-observation debounce. No arbitrary minimum RPM threshold such as 100/500 RPM is used.

Confirmed physical presence is persisted by stable fan ID. Persistence semantics are:

- confirmation survives App restart;
- persistence is updated only when confirmed inventory changes, never every FAST cycle;
- persistence alone does not synthesize a current fan entity if the corresponding hwmon channel is absent from the current Linux source;
- a confirmed channel remains a real fan when its current valid reading is `0 RPM`; fan-stop is valid telemetry, not grounds for deleting or hiding the entity.

Exposure rules:

```text
unconfirmed + RPM == 0
  -> observe internally
  -> no RPM MQTT Discovery entity

unconfirmed + two consecutive RPM > 0 observations
  -> confirm persistently
  -> expose RPM entity

confirmed + RPM > 0
  -> publish normal RPM telemetry

confirmed + RPM == 0
  -> publish 0 RPM; entity remains present

confirmed + invalid/unreadable
  -> entity remains part of confirmed inventory; current measurement is unavailable

persisted confirmed + current hwmon channel absent
  -> do not synthesize RPM telemetry from persistence alone
  -> expose source/detection diagnostics as applicable
```

The following are not fan-RPM acquisition sources:

- `sensors`/libsensors subprocess output;
- `/sys/class/thermal/cooling_device*`;
- `pwm*` presence or values;
- vendor utilities, EC/raw-I/O probing or hardware-control commands.

`pwm*` may exist for an unconnected tachometer channel and therefore is not physical-presence evidence.

Fan summary semantics are based on confirmed current fan channels, not raw exported hwmon inputs:

```text
detected          = confirmed_count > 0
count             = confirmed_count
candidate_count   = current exported fan*_input channels
unconfirmed_count = current candidate_count - current confirmed_count
```

These summary values are diagnostic/presentation data and are not Recorder telemetry. Confirmed RPM entities remain explicit Recorder candidates.

---

## 3. Decision averages and MQTT publication

Collection and publication are independent.

```text
NORMAL = every 15 min
DETAIL = every 5 min
EVENTS / PROBLEM TRANSITIONS = immediately
```

### 3.1 Decision windows

Decision averages are rolling windows used for publication-profile and ordinary alert/problem decisions:

```text
FAST metrics -> rolling 60 s
SLOW metrics -> rolling 5 min
HEALTH/discrete state -> no rolling average unless explicitly designed for a specific metric
```

After app restart a window starts empty and is calculated from available valid samples only.

Missing/invalid samples:

- are excluded;
- are never converted to zero;
- do not cause a state transition when no valid samples exist.

Strict comparison semantics for ordinary averaged alert/profile thresholds:

```text
average > threshold  -> ON / DETAIL
average < threshold  -> OFF / NORMAL
average == threshold -> unchanged
```

No `>=` / `<=` transition semantics and no initial hysteresis layer for this ordinary threshold model.

UPS shutdown safety predicates are a separate contract defined in section 12; they use current valid NUT telemetry and explicit `<=` guards, not rolling decision averages.

### 3.2 Publication averages

Published averaged telemetry uses the publication period for its domain:

```text
DETAIL -> 5 min publication average
NORMAL -> 15 min publication average
```

Profile-decision thresholds are internal app defaults, not HA controls. Alert thresholds are separate MQTT `number` configuration owned by the app.

### 3.3 Domain-local DETAIL

DETAIL is selected independently per domain, for example:

```text
cpu
memory
storage
disk
gpu
cooling
ups
```

A domain entering DETAIL changes only that domain's MQTT publication cadence.

A profile transition must never:

- increase collection frequency;
- run extra SMART;
- trigger `pvesh`, `qm`, `pct`, `pvesm` or guest exec;
- launch automatic deep diagnostics;
- cause recursive load-driven collection.

### 3.4 Immediate discrete state

Meaningful discrete changes publish immediately, independent of NORMAL/DETAIL telemetry cadence. Examples include:

- UPS OL/OB/LB/FSD/ALARM changes;
- alert problem transitions;
- SMART problem transition after HEALTH detects it;
- CPU throttling transition;
- VM/LXC runtime transition when SLOW refreshes it;
- supported data-source failure/recovery;
- publication-profile transition.

---

## 4. Home Assistant responsibility boundary

### 4.1 App owns

`dh_pve_app` owns:

- acquisition and parsing;
- decision/publication averages;
- derived calculations;
- publication profiles;
- alert-threshold defaults/persistence/validation;
- threshold comparison and problem states;
- aggregates and presentation summaries;
- VM/LXC/PCI topology composition;
- NUT/UPS interpretation;
- shutdown history/evidence;
- shutdown-budget calculation;
- UPS Trigger Policy v2 active/draft state and validation.

### 4.2 HAOS owns

HAOS owns:

- display/layout;
- explicit Recorder whitelist;
- notification delivery/repeat policy;
- site-specific notification gates;
- user interaction with MQTT Discovery configuration controls.

`binary_sensor.bs_global_system_boot_completed` remains **HAOS-only**. Its site meaning is that HAOS is successfully booted and HA-side dependencies such as MQTT and Zigbee are ready for notification automations.

Do **not** add startup reconciliation that scans dynamic `binary_sensor.*_problem` entities. Do **not** add wildcard state scanning as an application contract.

### 4.3 Keep business logic out of HA templates

The target HA package/UI must not repeatedly:

- scan all `states.sensor` / `states.binary_sensor`;
- join dynamic related entities by attributes;
- calculate thresholds or problems;
- calculate storage used from other fields;
- build VM/LXC/PCI topology;
- reconstruct shutdown-policy math;
- re-read state entities to construct a transition notification.

The app publishes ready numeric state, problem state, aggregates and presentation objects.

---

## 5. MQTT Discovery naming and migration

Canonical prefixes:

```text
PVE: dh_app_pve_*
UPS: dh_app_pve_ups_*
```

Legacy `digitalhouses_proxmox_*`, `dh_pve_*` and `myups_*` identifiers are not preserved as the new contract.

### 5.1 Discovery schema migration

Discovery migration is explicit and idempotent.

The app maintains a `discovery_schema_version` and a versioned manifest of legacy retained Discovery topics owned by previous schemas.

When migration is required:

1. load the old-topic manifest;
2. publish retained empty payload tombstones for owned legacy Discovery configs;
3. tombstone known legacy retained state topics where required by the old schema;
4. publish the new Discovery schema;
5. persist the successful discovery schema version only after the migration/publish sequence completes.

Repeating the same migration must be safe. An interrupted migration must converge on the next start rather than leave permanent old+new duplicate entities.

HA package/UI changes switch to new entity IDs only after the corresponding Discovery migration is implemented.

---

## 6. Home Assistant device-page grouping

### Main telemetry

Normal telemetry/presentation entities have no `entity_category` unless they are purely diagnostic/configuration objects.

### Configuration

Use:

```text
entity_category: config
```

for:

- alert threshold MQTT numbers;
- battery-test schedules;
- scheduled-test beeper settings;
- approved UPS Trigger Policy v2 draft controls.

### Diagnostics/problems

Use:

```text
entity_category: diagnostic
device_class: problem
```

for problem binaries where appropriate.

Low-level debug entities may additionally use:

```text
enabled_by_default: false
```

### Actions

Real actions remain normal controls, including Refresh, battery-test buttons, Apply Policy and the physical UPS beeper switch.

---

## 7. Recorder and Logbook contract

Recorder uses an explicit whitelist only. Broad patterns such as these are forbidden:

```text
sensor.dh_app_pve_*
binary_sensor.dh_app_pve_*
```

### 7.1 Recorded PVE telemetry

Useful numeric history includes:

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

Recorded telemetry has minimal dynamic attributes.

### 7.2 Recorded UPS telemetry

Record useful UPS status/telemetry required for long-term graphs and incident reconstruction. At minimum `sensor.dh_app_pve_ups_status` is mandatory in Recorder and Logbook.

Numeric UPS telemetry such as charge, runtime, load and relevant voltages/power is explicitly whitelisted where useful.

### 7.3 Not Recorder

The following are excluded from Recorder by default:

- rich presentation/summary entities;
- topology objects;
- policy descriptions/history lists;
- publication diagnostics;
- MQTT Event entities.

---

## 8. Alert thresholds, problem state and diagnostic events

### 8.1 Threshold pair model

Replace HA `input_number` alert helpers with app-owned MQTT Discovery `number` entities.

Initial threshold controls/defaults:

```text
storage percent used  80 %
CPU temperature       90 C
HDD temperature       45 C
SSD temperature       75 C
NVMe temperature      80 C
GPU temperature       85 C
```

Canonical examples:

```text
number.dh_app_pve_cpu_temperature_threshold
binary_sensor.dh_app_pve_cpu_temperature_problem

number.dh_app_pve_storage_percent_used_threshold
binary_sensor.dh_app_pve_storage_<id>_percent_used_problem

number.dh_app_pve_nvme_temperature_threshold
binary_sensor.dh_app_pve_disk_<id>_temperature_problem
```

The app validates, persists and republishes the effective threshold. HA does not use `0 = default` and does not initialize defaults at startup.

When either the relevant decision metric/average **or the threshold** changes, the app immediately reevaluates the problem binary.

Problem binary semantics:

```text
OFF = OK
ON  = problem currently active
```

Problem binaries are current-state/UI contracts. They are **not** the dynamic notification transport.

### 8.2 Aggregates

Provide non-Recorder aggregate presentation entities such as:

```text
sensor.dh_app_pve_problems
sensor.dh_app_pve_ups_problems
```

State is active problem count. Compact category/severity/summary information may be attributes. HA must not rescan all entities to calculate these aggregates.

### 8.3 Coherent problem-transition publication bundle

MQTT does not provide a multi-topic transaction, so do not call this atomic. For each problem transition, publish in this order:

```text
1. related metric/current decision data
2. effective threshold
3. problem binary
4. aggregate problem state
5. related presentation state
6. diagnostic event LAST
```

The event is published last so the HA notification automation can trust its payload rather than rereading a partially updated set of entities.

### 8.4 Native MQTT Event boundary

Use native MQTT Event entities:

```text
event.dh_app_pve_diagnostic
event.dh_app_pve_ups_diagnostic
```

Runtime event messages are `retain=false`.

Problem event schema:

```text
schema_version: 1
event_type: problem_started | problem_recovered | problem_updated
category
severity
object_id
object_name
metric
value
average
threshold
summary
details
active_problem_count
```

Fields that are not applicable to a discrete problem may be null/absent according to the schema contract; HA must not infer them by rereading entities.

Default HA notifications:

```text
problem_started   -> notify
problem_recovered -> notify
problem_updated   -> do not notify by default
```

HA notifications use the event payload directly. They do not reread metric/problem/aggregate entities to reconstruct the event.

Event entities are excluded from Recorder.

---

## 9. PVE presentation contract

Presentation entities are non-Recorder by default.

### 9.1 System overview

Provide `sensor.dh_app_pve_system` with an app-formatted summary in this order:

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

### 9.2 Storage and disks

Canonical storage naming is **percent used**:

```text
sensor.dh_app_pve_storage_<id>_percent_used
binary_sensor.dh_app_pve_storage_<id>_percent_used_problem
number.dh_app_pve_storage_percent_used_threshold
```

Temperature/wear remain separate recorded telemetry. SMART and temperature problems remain separate problem state. Rich disk/storage UI summaries are app-provided presentation data.

### 9.3 VM/LXC/PCI topology

The app owns topology composition. Lovelace does not build it by looping over all entities.

Per-guest current state and shutdown evidence may remain separate where useful, but joins/summary formatting belong in the app.

### 9.4 Fan presentation

Only confirmed current fan channels receive MQTT Discovery RPM entities.

Canonical RPM entity contract:

```text
sensor.dh_app_pve_fan_<stable-id>_rpm
```

RPM telemetry uses `state_class: measurement` and `rpm` units and is eligible for the explicit Recorder whitelist. A valid `0 RPM` on a confirmed fan is published as zero and does not remove the entity.

The fan summary is diagnostic/non-Recorder presentation. It reports confirmed fan count and may include raw candidate/unconfirmed counts so users can distinguish:

- no Linux fan source;
- exported but unconfirmed tachometer channels;
- confirmed physical fans.

Dynamic Discovery may add a fan RPM entity when an unconfirmed channel becomes confirmed; App restart is not required for that transition.

Fan component removal follows the Home Assistant MQTT Device Discovery update contract only when the App has an authoritative removal decision independent of live fan-presence inference. A removal transaction first publishes a retained Device Discovery update containing an empty component config with its `platform`, then publishes the final retained payload with that component omitted.

The live unconfirmed candidate set is never an authoritative removal source. A channel that is still inside the two-sample debounce, reports `0 RPM`, is temporarily unreadable, or has not yet been confirmed is simply omitted from normal fan RPM Discovery. The App must not tombstone such a channel merely because it is currently unconfirmed, because `0 RPM` and debounce state do not prove physical absence.

Raw candidate IDs may remain internal diagnostic/inventory metadata, but they must not by themselves trigger MQTT component deletion. Candidate IDs are not RPM entities, are not part of Recorder, and are not published in the fan summary group.

### 9.5 Shutdown history

Preserve app-owned shutdown history and the distinction between:

- shutdown reason;
- clean/unclean fact;
- per-guest shutdown duration/result;
- total guest shutdown duration;
- host shutdown timing where evidence exists.

This history is also input evidence for shutdown-budget calculation as defined below.

---

## 10. UPS Discovery and NUT interpretation

Canonical UPS prefix:

```text
dh_app_pve_ups_*
```

### 10.1 Primary telemetry

Core sensors include:

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

Current real power:

1. use NUT `ups.realpower` when available;
2. otherwise calculate `ups.realpower.nominal * ups.load / 100`.

Do not add an app energy accumulator without a separate reporting requirement.

### 10.2 NUT status tokens

Interpret at least:

| Token | Discovery suffix | Meaning |
|---|---|---|
| `OL` | `online` | utility present |
| `OB` | `on_battery` | on battery |
| `LB` | `low_battery` | native Low Battery |
| `HB` | `high_battery` | high battery |
| `RB` | `replace_battery` | replace battery |
| `CHRG` | `charging` | charging fallback flag |
| `DISCHRG` | `discharging` | discharging fallback flag |
| `BYPASS` | `bypass` | bypass active |
| `CAL` | `calibration` | battery calibration/test |
| `OFF` | `off` | UPS output/load off |
| `OVER` | `overload` | overload |
| `TRIM` | `trim` | correction of high input voltage |
| `BOOST` | `boost` | correction of low input voltage |
| `FSD` | `forced_shutdown` | forced-shutdown state |
| `ALARM` | `alarm` | alarm present |

Unknown future tokens must not break the parser. Preserve raw tokens for diagnostics.

Expose NUT communication availability separately:

```text
binary_sensor.dh_app_pve_ups_available
```

### 10.3 Charger state priority

For charging/discharging interpretation:

```text
1. battery.charger.status when available/valid
2. CHRG / DISCHRG tokens from ups.status as fallback
```

### 10.4 Status sensor and Russian text

`sensor.dh_app_pve_ups_status` is mandatory Recorder + Logbook state.

Keep attributes small and stable, at least:

```text
raw_status
status_ru
```

Canonical wording includes:

```text
OL       -> Работает от сети
OB       -> Работает от батареи
CHRG     -> Заряжается
DISCHRG  -> Разряжается
LB       -> Низкий заряд
RB       -> Требуется замена батареи
BYPASS   -> Байпас
BOOST    -> Коррекция пониженного входного напряжения
TRIM     -> Коррекция повышенного входного напряжения
OVER     -> Перегрузка
FSD      -> Аварийное отключение
ALARM    -> Авария
CAL      -> Калибровка
OFF      -> Выход UPS отключён
```

Example:

```text
raw_status: "OB DISCHRG"
status_ru: "Работает от батареи · Разряжается"

raw_status: "OL BOOST"
status_ru: "Работает от сети · Коррекция пониженного входного напряжения"
```

---

## 11. UPS controls and battery-test scheduler

Supported control surface:

```text
button.dh_app_pve_ups_refresh
button.dh_app_pve_ups_test_quick
button.dh_app_pve_ups_test_deep
button.dh_app_pve_ups_test_stop
switch.dh_app_pve_ups_beeper
```

Scheduled Quick and Deep tests each have independent configuration:

```text
number.dh_app_pve_ups_quick_test_interval_days
time.dh_app_pve_ups_quick_test_time
switch.dh_app_pve_ups_quick_test_beeper

number.dh_app_pve_ups_deep_test_interval_days
time.dh_app_pve_ups_deep_test_time
switch.dh_app_pve_ups_deep_test_beeper
```

Scheduled test transaction:

```text
save current physical beeper state
-> set requested scheduled beeper state
-> start requested test
-> always restore original beeper state on pass/fail/stop/other completion
```

The restore path must execute even when the test command/result path fails after the temporary beeper change.

Manual Quick/Deep tests use the current physical beeper state and do not temporarily override it.

Deep-test support does not make deep-discharge live validation acceptable.

Battery-test history remains app-owned and may be presented through a non-Recorder history entity.

---

## 12. UPS Trigger Policy v2

UPS Trigger Policy v2 is in scope for this development cycle.

HAOS only configures/displays the policy. The decision loop and shutdown commitment run locally on PVE/NUT and do not depend on HAOS, MQTT availability or HA automations.

### 12.1 Software trigger evaluation

Software shutdown guards use the **current valid NUT sample** from the fixed UPS collection path. They do not use the 60-second/5-minute rolling averages defined for ordinary telemetry/problem decisions.

Software triggers are evaluated only while the UPS is confirmed On Battery (`OB`). A low charge while utility power is present is not by itself a host-shutdown command.

Trigger A — charge guard:

```text
OB
AND valid battery.charge
AND battery.charge <= active configured shutdown battery-charge threshold
```

Trigger B — runtime guard:

```text
OB
AND valid battery.runtime
AND battery.runtime <= shutdown_budget_seconds + active reserve_seconds
```

The `<=` comparisons above are deliberate safety predicates and are not the ordinary alert/profile comparison semantics from section 3.

The first satisfied software trigger commits shutdown.

Missing/invalid charge/runtime is never converted to zero and never satisfies that software trigger. Data-source failure is exposed diagnostically. Native Low Battery remains the independent emergency path.

### 12.2 Native Low Battery emergency path

UPS/NUT native `LB` remains an independent emergency shutdown path.

The app must not:

- enable `ignorelb`;
- synthesize `LB` from estimated runtime or charge;
- rewrite `battery.charge.low` / `battery.runtime.low` merely to implement Trigger A/B;
- override native LB merely to implement Trigger A/B;
- delay or cancel an UPS-reported LB shutdown.

Conceptually:

```text
software charge guard
OR software runtime-budget guard
OR native UPS/NUT Low Battery emergency
-> local shutdown commitment
```

### 12.3 Commitment semantics

Before commitment, restored utility cancels only transient software trigger evaluation because `OB` is no longer true.

Once the local NUT/PVE shutdown commitment/FSD path has been entered, the sequence is irreversible. Utility restoration does not cancel committed shutdown.

No MQTT command may directly expose FSD, `upsmon -c fsd`, load-off, shutdown instant commands, arbitrary `upscmd`, arbitrary shell, or arbitrary NUT configuration text.

### 12.4 Policy configuration surface

Trigger Policy v2 replaces the old product-level `on_battery_delay` timer as the normal software trigger model.

User-facing draft trigger values are:

```text
number.dh_app_pve_ups_shutdown_battery_charge_threshold   # percent
number.dh_app_pve_ups_shutdown_runtime_reserve            # user-facing time, normalized internally to seconds
```

Power-restore delay remains a separate policy/power-cycle setting where supported:

```text
number.dh_app_pve_ups_power_restore_delay
```

It is not a shutdown-trigger condition.

Exact default values/ranges are implementation configuration, not architectural constants, but they must be explicit, bounded, backend-validated, documented and covered by tests. HA min/max metadata is convenience only and never replaces app validation.

---

## 13. Shutdown budget and reserve

`shutdown_budget_seconds` is a derived read-only safety value. It is not a user slider and must not be a guessed constant.

The user-configurable `reserve_seconds` is separate additional safety headroom. Trigger B compares runtime against:

```text
runtime_guard_threshold_seconds = shutdown_budget_seconds + reserve_seconds
```

### 13.1 Current Proxmox configuration component

Calculate a current Proxmox guest shutdown ceiling from the guests that would require shutdown, using current effective PVE settings:

- guest `startup` order;
- per-guest effective `down` timeout, including PVE fallback when absent;
- current shutdown worker concurrency (`max_workers` / effective PVE behavior);
- shutdown groups processed in reverse startup order;
- guests within a group scheduled according to the effective worker concurrency.

Expose this component as:

```text
configured_guest_shutdown_budget_seconds
```

The source audit must confirm the exact PVE 8.x semantics and parser fixtures before this calculation is rewritten.

### 13.2 Historical evidence component

Use bounded persisted shutdown history as evidence, not as an optimistic replacement for configuration safety.

For comparable clean historical shutdowns, derive at least:

```text
observed_guest_shutdown_budget_seconds
observed_host_tail_seconds
```

`observed_guest_shutdown_budget_seconds` comes from the real guest shutdown interval/evidence. `observed_host_tail_seconds` is the real interval after guests are stopped until host clean shutdown evidence, where timestamps permit it.

A history sample used for budget calculation must be structurally valid and comparable to the relevant current shutdown topology/configuration. The app persists enough configuration/topology fingerprint/revision with future shutdown history to determine comparability. Older non-comparable history remains visible for diagnostics but does not lower safety assumptions.

History must **never reduce** the configured guest ceiling. Effective guest budget is conservative:

```text
effective_guest_budget = max(
    configured_guest_shutdown_budget_seconds,
    valid comparable observed_guest_shutdown_budget_seconds
)
```

This allows actual evidence to increase the safety estimate if real shutdown behavior was slower than configuration math, while a previously fast shutdown can never make the next runtime guard less safe.

### 13.3 Full shutdown budget

The runtime guard covers the time until the PVE host reaches a safe clean shutdown/power-off handoff. It is not the same as the later UPS output-off/restart timing.

Use the applicable sequential pre-handoff components:

- current NUT secondary synchronization allowance (`HOSTSYNC`) when applicable;
- NUT `FINALDELAY` before local `SHUTDOWNCMD`;
- `effective_guest_budget`;
- host-finalization/tail allowance after guests stop, including service/filesystem/unmount work reflected by valid evidence.

Canonical calculation:

```text
shutdown_budget_seconds =
    hostsync_budget_seconds
    + finaldelay_seconds
    + effective_guest_budget_seconds
    + host_tail_budget_seconds
```

When there are no relevant NUT secondaries, the effective HOSTSYNC budget component is zero rather than blindly adding the configured maximum.

For host-finalization/tail:

- use the maximum valid comparable observed host tail when it is larger;
- keep a conservative internal fallback floor when no valid history exists;
- expose the chosen component and its source (`observed` or `fallback`) diagnostically.

The internal fallback is not a HA slider and cannot be silently zero.

`ups.delay.shutdown` / UPS output-off delay and output-restore delay remain important power-cycle diagnostics/configuration, but are **not added to Trigger B's shutdown budget merely because they happen later in the UPS power-cycle sequence**. NUT invokes the driver shutdown sequence as the final system-shutdown stage after the host has reached the safe handoff path. If future production evidence shows a particular driver/platform needs a pre-handoff allowance, that requires an explicit design revision rather than silently padding the budget.

Expose enough read-only detail for HA to explain the result, for example:

```text
configured_guest_shutdown_budget_seconds
observed_guest_shutdown_budget_seconds
effective_guest_shutdown_budget_seconds
hostsync_seconds
hostsync_budget_seconds
finaldelay_seconds
observed_host_tail_seconds
host_tail_budget_seconds
shutdown_budget_seconds
reserve_seconds
runtime_guard_threshold_seconds
ups_poweroff_delay_seconds
ups_restart_delay_seconds
budget_evidence_status
```

### 13.4 Recalculation

Recalculate when relevant inputs change, including:

- relevant STATIC/PVE configuration change detected through `.version`;
- VM/LXC runtime membership/state relevant to shutdown changes;
- new shutdown-history evidence is persisted;
- successful policy Apply changes a relevant setting;
- Manual Refresh.

User workflow after changing Proxmox shutdown settings:

```text
change PVE settings
-> return to HAOS
-> press Refresh
-> app rereads current PVE configuration/history
-> app publishes the new budget and its components
```

### 13.5 Budget unavailable

If a mandatory budget component cannot be established safely, Trigger B is unavailable rather than using zero or a guessed optimistic value. Publish a policy/readiness diagnostic problem. Trigger A and native `LB` remain independent according to their own valid inputs.

---

## 14. UPS policy draft/apply transaction

HA configuration is not applied immediately.

### 14.1 Active vs draft

Maintain separate models:

```text
active policy = last successfully validated/applied/verified policy
draft policy  = current user edits in HAOS
```

Changing a number only changes draft state and marks `Pending changes`. It must not alter active production behavior.

The HA UI shows a pending/config block with explicit Apply/Confirm. After successful Apply, draft and active converge and the pending block disappears; the normal active/config view remains.

### 14.2 Apply transaction

Explicit Apply/Confirm performs one transaction:

1. snapshot the immutable draft;
2. read current host/NUT/PVE facts required for validation;
3. validate values and cross-field safety;
4. calculate derived policy/budget values;
5. back up every managed file/state object that will change;
6. write target state atomically where applicable;
7. perform only the controlled reload/restart actions required by the changed settings;
8. reread effective configuration/runtime state;
9. verify effective state matches the target policy;
10. persist the new active policy only after successful verification;
11. publish synchronized active/draft state and derived values.

No host-side write occurs before pre-write validation passes.

### 14.3 Rollback

If write/reload/restart/reread/verification fails:

- restore all modified managed files/state from the transaction backup;
- restore/reload the previous effective service configuration as required;
- verify rollback where possible;
- keep the previous active policy authoritative;
- republish draft controls from the active policy or otherwise clearly return the UI to the effective state;
- publish a sanitized failure result with no credentials.

A partially applied policy is never published as active.

### 14.4 Config-change event

After successful application, publish an UPS diagnostic config-change event **after** effective state has been verified and published.

Use the same UPS Event entity with schema version 1 and a distinct non-problem event type:

```text
event.dh_app_pve_ups_diagnostic
schema_version: 1
event_type: config_changed
category: policy
severity: info
object_id: ups_trigger_policy
summary
details
old_values
new_values
active_problem_count
```

The associated notification must show the meaningful **OLD -> NEW** values. Failed Apply/rollback is not reported as a successful config change.

This Event entity remains excluded from Recorder.

---

## 15. HA notification model

The old packages are behavioral references only. Their legacy names/template architecture are not retained.

### 15.1 Diagnostic notifications

Dynamic problem notifications consume `event.dh_app_pve_diagnostic` or `event.dh_app_pve_ups_diagnostic` payloads directly.

The HAOS-only readiness gate may suppress delivery until:

```text
binary_sensor.bs_global_system_boot_completed == ON
```

Do not compensate for a missed runtime event by wildcard scanning all dynamic problem binaries at HA startup. Current state remains visible through problem binaries/aggregates; the notification event is intentionally `retain=false`.

### 15.2 Repeats

Repeat policy belongs to HAOS. For example, HA may periodically repeat selected still-active critical problems such as SMART, but this is separate from app transition-event production.

### 15.3 PVE boot notification

PVE boot notification may use:

```text
bs_global_system_boot_completed == ON
+ app-provided recent PVE boot information
```

HA never initiates Proxmox shutdown.

---

## 16. Publication diagnostics

Use the two-profile model rather than legacy global quiet/normal/high/critical publication semantics.

A non-Recorder diagnostic may expose domain state:

```text
sensor.dh_app_pve_publication_profile
```

Example attributes:

```text
cpu: NORMAL
memory: NORMAL
storage: NORMAL
disk: DETAIL
gpu: NORMAL
ups: NORMAL
```

Keep a lightweight non-Recorder last-publication timestamp/diagnostic so HA can show when the app last published useful state.

These are diagnostics, not control knobs.

---

## 17. Storage/unmount shutdown technical debt

NFS/CIFS/SMB storage backed by TrueNAS, another VM or an external NAS can materially lengthen real host shutdown if the provider disappears before PVE unmount/storage teardown completes.

Therefore guest shutdown history alone is not guaranteed to represent total host shutdown time.

Preserve this as explicit technical debt/diagnostic work:

- identify PVE storage/provider dependencies;
- identify configurations where a storage provider is a guest on the same host;
- warn when shutdown ordering may make mounts unavailable too early;
- use observed host-tail evidence to detect unexpectedly long post-guest shutdown;
- do not silently assume guest budget equals total host budget.

Do not add speculative automatic storage rewrites in this development cycle.

---

## 18. Source audit contract

After this design is frozen and before production refactoring, perform a field-by-field source audit.

For every current field record:

```text
CURRENT FIELD
-> CURRENT SOURCE
-> CURRENT COST
-> TARGET CHEAP SOURCE
-> parser/fixture contract
-> subprocess remains? yes/no
-> cadence class FAST/SLOW/HEALTH/STATIC/UPS
-> Recorder? yes/no
-> problem/event relation
```

Audit at least:

- CPU usage/frequency/temperature;
- RAM/Swap;
- thermal/fans;
- host load/runtime facts;
- VM/LXC runtime;
- VM/LXC configuration/startup/shutdown topology;
- storage;
- disk temperature;
- SMART/wear/counters;
- GPU/transcoding;
- PCI passthrough topology;
- PVE/kernel/hardware inventory;
- UPS/NUT telemetry;
- shutdown history and shutdown-budget inputs.

No production reader rewrite begins before this audit establishes the target source/parser contract.

---

## 19. Implementation order after design freeze

Use TDD and proceed in this order:

1. source audit;
2. PVE 8.x file/cache readers and fixtures;
3. remove unnecessary regular heavy polling;
4. fixed scheduler (`FAST=10s`, `UPS=10s`, `SLOW=1m`, `HEALTH=1h`, `STATIC=event`);
5. decision and publication averages;
6. domain-local NORMAL/DETAIL publication;
7. new Discovery naming and schema foundation;
8. MQTT threshold numbers and problem binaries;
9. aggregates/presentation layer;
10. native MQTT Event transition boundary;
11. Discovery tombstone migration;
12. UPS status/charger/power improvements;
13. scheduled UPS tests and beeper restore;
14. UPS Trigger Policy v2 and shutdown-budget engine;
15. HA package simplification;
16. UI simplification and policy pending/active UX;
17. explicit Recorder whitelist;
18. notification automations using Event payloads;
19. full CI;
20. final diff review;
21. deploy exact reviewed SHA to home PVE `192.168.11.30`;
22. non-destructive production validation;
23. tune only from real production evidence.

---

## 20. Production validation and safety gate

Initial production validation collects evidence for:

- `dh_pve_app` CPU/RSS under normal operation;
- whether file/cache readers remove previous subprocess spikes;
- Recorder update rate with NORMAL 15m / DETAIL 5m;
- usefulness of 15m normal and 5m detail graphs;
- average/profile stability;
- VM/LXC SLOW=1m visibility;
- Manual Refresh latency/peak load;
- shutdown-budget calculation and evidence visibility;
- UPS event/logbook noise;
- device-page readability;
- policy draft/apply/rollback behavior without committing real shutdown.

The following are **not** casual validation steps:

```text
FSD
upsmon -c fsd
UPS output-off/load-off
mains unplug
deep battery discharge
HA-side host shutdown
arbitrary shell/upscmd over MQTT
```

Live UPS shutdown commissioning is a separately reviewed gate. Supporting a safe production path in code does not authorize destructive testing during ordinary deployment validation.

---

## 21. Freeze invariants

Before production code starts, this design freezes these architectural invariants:

```text
PVE 8.x files/cache first
fixed acquisition cadence
.version checked every SLOW cycle
no permanent heavy fallback loop
FAST decision window 60 s
SLOW decision window 5 min
missing/invalid != zero
fan RPM source is sysfs hwmon only; FAST fan acquisition has zero subprocesses
raw hwmon fan channel != confirmed physical fan
fan confirmation requires two consecutive valid RPM > 0 observations
confirmed fan presence is persisted by stable chip/device/channel identity
confirmed fan 0 RPM remains valid telemetry and does not remove the entity
unconfirmed zero-RPM fan channels are not exposed through MQTT Discovery
NORMAL 15m / DETAIL 5m publication only
DETAIL is per-domain publication only
HAOS is a light client
PVE/NUT is shutdown authority
MQTT number + problem binary current-state model
native MQTT Event is dynamic notification boundary
event published last in coherent transition bundle
explicit Recorder whitelist
UPS status is Recorder + Logbook
battery.charger.status preferred over CHRG/DISCHRG fallback
BOOST/TRIM wording follows electrical meaning
scheduled test beeper always restored
UPS software shutdown guards use current valid NUT telemetry, not rolling averages
Trigger A OR Trigger B OR native LB
ignorelb forbidden
Trigger A/B do not rewrite native battery low thresholds
shutdown budget derived from current PVE config + conservative historical evidence
history never lowers configured guest ceiling
shutdown budget ends at safe host handoff; UPS output-off/restart delays remain separate diagnostics
policy controls are draft until explicit transactional Apply
successful policy change event includes OLD -> NEW
Discovery migration uses versioned manifest + retained tombstones and is idempotent
NFS/CIFS/SMB unmount delay remains explicit shutdown-budget technical debt
no destructive validation in ordinary CI/deploy
```

Any future change to one of these invariants requires an explicit design revision before implementation.

---

## 22. 2026-09-24 production UPS incident amendment

This section is canonical for the production defects exposed by the 2026-09-24 mains-loss incident and supersedes older wording where it conflicts.

### 22.1 Line-power history

`binary_sensor.dh_app_pve_ups_line_power` is a first-class incident-reconstruction signal. It is explicitly whitelisted in both Recorder and Logbook together with `sensor.dh_app_pve_ups_status`.

The App remains the source of truth for line-power statistics; HA Recorder history is an additional operator-facing timeline, not the source for monthly statistics.

### 22.2 Startup reconciliation freshness

Startup reconciliation must never treat a retained problem aggregate from a previous PVE/App boot as fresh current evidence.

When HAOS becomes boot-ready, retained current-state entities may already exist while the PVE host and NUT driver are still recovering. HA therefore waits for evidence of a publication from the current App process before evaluating retained problem aggregates.

The canonical freshness relation is:

```text
fresh publication timestamp >= current agent_started timestamp
```

Use the PVE and UPS last-publication diagnostics for their respective reconciliation paths. If freshness cannot be established within a bounded timeout, reconciliation is skipped rather than sending a stale alert. No fixed sleep is a correctness mechanism.

If HAOS restarts while the App process remains continuously running, a retained publication newer than that same `agent_started` remains valid.

### 22.3 Notification presentation

Machine Events remain localization-free. HA locale packages own all human-facing `title` and `message` rendering.

For every supported live event type, the locale package must emit a non-empty title and message. Empty `DH PVE |` delivery is a contract failure, not a valid fallback.

UPS startup problem presentation maps stable machine `problem_id` values to localized operator text. It must not depend on legacy `summary` fields that are absent from schema-v2 retained problem objects.

### 22.4 Shutdown-history evidence boundaries

Shutdown history must preserve the difference between:

```text
shutdown requested
guest shutdown operation started
guest shutdown operation completed
all guests stopped
host entered final shutdown/power-off handoff
next boot
```

A log line such as `System is powering down` is evidence that shutdown has started; it is not by itself proof that the host reached a clean final handoff.

A guest completion timestamp is valid only for the matching shutdown transaction and only when it is not earlier than that transaction's start timestamp. Starting a newer shutdown transaction for the same guest resets stale completion/result fields from earlier operations in the same boot. Once an explicit host-shutdown-start marker is observed, unrelated guest operations from earlier in the same boot are outside the final shutdown-history scope.

Negative durations are invalid evidence and must remain unknown; they are never clamped to zero.

If the previous boot journal ends before a strong clean-shutdown marker, `shutdown_clean` must not be reported as true. Incomplete guest operations remain `unknown`/incomplete and must not be converted to successful zero-second shutdowns.

Only structurally valid, comparable, clean shutdown evidence may contribute observed timing to the shutdown-budget engine.

### 22.5 UPS telemetry plausibility

Raw NUT telemetry remains factual even when the device reports suspicious values. The App must not silently replace a reported `ups.load = 0` or recompute a different `battery.runtime` merely because the pair appears implausible.

A future diagnostic may flag sustained suspicious telemetry, but any such diagnostic is separate from the recorded raw/averaged measurement and from shutdown-trigger inputs.

