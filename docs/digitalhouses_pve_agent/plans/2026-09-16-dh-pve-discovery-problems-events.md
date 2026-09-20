# DH PVE Discovery, Problems and Diagnostic Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy `dh_pve_*` Home Assistant contract with canonical `dh_app_pve_*` / `dh_app_pve_ups_*` Discovery, move alert thresholds and problem evaluation into the App, publish self-contained diagnostic MQTT Events, and migrate retained Discovery safely and idempotently.

**Architecture:** Reuse the fixed acquisition and rolling-window foundation already implemented in Plan 1. `RuntimeSettings` owns persistent alert-threshold numbers; a pure `ProblemEngine` consumes valid raw samples through the existing `RollingAverage` primitive and produces current problem state plus transitions. A problem-aware runtime publishes each transition as a coherent retained-state bundle followed by a non-retained MQTT Event. Discovery schema migration is versioned and persisted only after tombstones plus the new schema publish succeed.

**Tech Stack:** Python 3.13, pytest, Paho MQTT 2.x, Home Assistant MQTT Device Discovery, Home Assistant MQTT Event, existing `StateStore`, existing fixed scheduler and presentation routers.

**Spec:** `docs/digitalhouses_pve_agent/specs/2026-09-15-dh-pve-simplified-runtime-haos-design.md`

## Global Constraints

- PVE 8.x only; Plan 1 fixed collection cadence remains unchanged.
- FAST remains 10 s, UPS 10 s, SLOW 60 s, HEALTH 3600 s, STATIC event-driven.
- NORMAL/DETAIL affect MQTT publication only; they never alter acquisition cadence.
- Alert/problem decision windows are FAST 60 s and SLOW 300 s over valid numeric samples only.
- Missing, invalid, NaN and infinite samples are excluded and are never converted to zero.
- Ordinary threshold transitions use strict semantics: average `>` threshold => active, average `<` threshold => recovered, equality => unchanged.
- Threshold changes cause immediate reevaluation using the current valid decision average.
- Canonical entity prefixes are `dh_app_pve_*` and `dh_app_pve_ups_*`.
- Legacy `digitalhouses_proxmox_*`, `dh_pve_*`, `dh_ups_*` and `myups_*` identities are migration input only, not the new contract.
- Runtime MQTT diagnostic events are `retain=false` and are published last after related retained state.
- `binary_sensor.bs_global_system_boot_completed` remains HAOS-only; the App must not depend on it.
- Do not scan dynamic HA entities. Aggregate problem payloads must contain enough active-problem information for a future HA startup reconciliation without wildcard scans.
- No HA-side threshold computation, topology composition or shutdown decision.
- No UPS Trigger Policy v2 mutation, FSD testing, mains unplug, UPS output-off or deep-discharge work in this plan.
- The old deleted Runtime Observability plan remains superseded; do not reintroduce command-level PERF/COLLECTORS/COMMANDS instrumentation.

### Alert threshold contract

Canonical defaults come from the frozen design. UI ranges/step are retained from the previous HA helper contract strictly as migration UX. `0` is no longer a sentinel for default; if selected, it is the explicit configured value.

| Key | Default | Min | Max | Step | Unit | Canonical entity |
|---|---:|---:|---:|---:|---|---|
| `storage_percent_used_threshold` | 80 | 0 | 98 | 1 | `%` | `number.dh_app_pve_storage_percent_used_threshold` |
| `cpu_temperature_threshold` | 90 | 0 | 110 | 1 | `°C` | `number.dh_app_pve_cpu_temperature_threshold` |
| `hdd_temperature_threshold` | 45 | 0 | 70 | 1 | `°C` | `number.dh_app_pve_hdd_temperature_threshold` |
| `ssd_temperature_threshold` | 75 | 0 | 90 | 1 | `°C` | `number.dh_app_pve_ssd_temperature_threshold` |
| `nvme_temperature_threshold` | 80 | 0 | 110 | 1 | `°C` | `number.dh_app_pve_nvme_temperature_threshold` |
| `gpu_temperature_threshold` | 85 | 0 | 110 | 1 | `°C` | `number.dh_app_pve_gpu_temperature_threshold` |

### Problem/event contract

Initial PVE problems:

```text
CPU temperature            FAST 60 s average -> cpu_temperature_threshold
storage percent used       SLOW 300 s average -> storage_percent_used_threshold, per storage
HDD/SSD/NVMe temperature   SLOW 300 s average -> type-specific threshold, per disk
GPU temperature            SLOW 300 s average -> gpu_temperature_threshold, per GPU
CPU throttling             immediate discrete
SMART failed               immediate when HEALTH refresh detects smart_passed == false
```

`ProblemTransition.event_type` is exactly `problem_started`, `problem_recovered`, or `problem_updated`. Threshold edits that change details while the problem remains active emit `problem_updated`; a threshold edit that crosses the state boundary emits started/recovered.

Each event payload contains:

```text
schema_version=1
event_type
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

For every transition the publish order is:

```text
1. problem decision metric payload
2. effective threshold retained state
3. problem binary retained state
4. aggregate retained state
5. aggregate/presentation attributes retained state
6. diagnostic event LAST, retain=false
```

---

### Task 1: Restore runtime settings as app-owned alert thresholds

**Files:**
- Modify: `dh_pve_app/app/runtime_settings.py`
- Modify: `dh_pve_app/app/discovery.py`
- Modify: `dh_pve_app/tests/test_runtime_settings.py`
- Modify: `dh_pve_app/tests/test_discovery.py`

**Interfaces:**
- Produces: `SETTING_SPECS` containing only the six alert-threshold keys above.
- Produces: `RuntimeSettings.apply(key, raw_value) -> float` with finite/range/step validation.
- Existing consumers: `MqttEvents.handle_message()`, `DhPveRuntime.publish_settings()`, persisted `runtime_settings` in runtime state.

- [ ] **Step 1: Write RED settings tests.** Assert exact defaults, exact canonical entity IDs, accepted boundary values, rejected out-of-range values, rejected off-step values, NaN/Inf rejection, and that legacy poll keys remain ignored during persisted-state load.
- [ ] **Step 2: Run `PYTHONPATH=. python -m pytest tests/test_runtime_settings.py -q` and verify RED.**
- [ ] **Step 3: Implement generic numeric validation.** Parse with `float`, require `math.isfinite`, enforce inclusive min/max and step alignment relative to `minimum`; keep `LEGACY_SETTING_KEYS` non-authoritative.
- [ ] **Step 4: Add Discovery number contract tests.** Each component is `platform: number`, `entity_category: config`, uses the table range/step/unit, canonical `default_entity_id`, and existing retained setting state/command topics.
- [ ] **Step 5: Run settings/discovery tests GREEN and commit with `feat(dh-pve): own alert thresholds in runtime settings`.**

---

### Task 2: Add pure PVE problem engine and aggregate model

**Files:**
- Create: `dh_pve_app/app/problems.py`
- Create: `dh_pve_app/tests/test_problems.py`
- Reuse: `dh_pve_app/app/runtime_windows.py`

**Interfaces:**
- Produces `ProblemState(problem_id, category, severity, object_id, object_name, metric, active, value, average, threshold, summary, details)`.
- Produces `ProblemTransition(event_type, previous, current)`.
- Produces `ProblemAggregate(count, severity, summary, active)` where `active` is a stable sorted tuple/list of compact problem dictionaries.
- Produces `PveProblemEngine.observe(now, subsystem_states, thresholds) -> tuple[ProblemTransition, ...]`.
- Produces `PveProblemEngine.reevaluate_threshold(key, value) -> tuple[ProblemTransition, ...]` using the last valid decision averages without inventing samples.

- [ ] **Step 1: Write RED strict-threshold tests.** FAST CPU samples prove `>`, `<`, equality-unchanged and 60-second rolling average. Invalid samples do not become zero or transition state.
- [ ] **Step 2: Write RED SLOW isolation tests.** Separate storage/disk/GPU objects have independent 300-second `RollingAverage` instances; one hot disk does not activate another.
- [ ] **Step 3: Write RED discrete tests.** CPU throttling and SMART failure transition immediately; repeated identical states produce no duplicate transition.
- [ ] **Step 4: Write RED threshold-edit tests.** Changing a threshold immediately reuses the current valid average; crossing boundary starts/recovers, changed threshold while still active yields `problem_updated`, and equality preserves state.
- [ ] **Step 5: Implement `problems.py` using existing `RollingAverage`; do not create a second averaging implementation.** Disk threshold key is selected from normalized `disk_type` (`HDD`, `SSD`, `NVMe`; unknown disks use SSD threshold until a canonical type is available rather than inventing a seventh control).
- [ ] **Step 6: Add aggregate tests.** Count is exact; highest severity is deterministic; compact active records include IDs/names/category/metric/summary and are sufficient for future startup reconciliation without HA wildcard scans.
- [ ] **Step 7: Run `tests/test_problems.py tests/test_runtime_windows.py` GREEN and commit `feat(dh-pve): add app-owned problem engine`.**

---

### Task 3: Add diagnostic event schema and MQTT non-retained transport

**Files:**
- Create: `dh_pve_app/app/diagnostic_events.py`
- Create: `dh_pve_app/tests/test_diagnostic_events.py`
- Modify: `dh_pve_app/app/topics.py`
- Modify: `dh_pve_app/app/mqtt_bridge.py`
- Modify: `dh_pve_app/tests/test_mqtt_transport.py`

**Interfaces:**
- Produces `DiagnosticEvent.from_transition(transition, *, active_problem_count) -> DiagnosticEvent`.
- Produces `DiagnosticEvent.as_payload() -> dict[str, object]` with schema version 1 and exact fields from the global contract.
- Extend `Topics` with `diagnostic_event` and `UpsTopics` with `diagnostic_event`.
- Extend runtime bridge transport with `publish_diagnostic_event(payload) -> bool` and `publish_ups_diagnostic_event(payload) -> bool`.

- [ ] **Step 1: Write RED schema tests** for started/recovered/updated payloads and nullable numeric fields for discrete problems.
- [ ] **Step 2: Write RED transport test** proving diagnostic event publishes JSON with QoS 1 and `retain=False`; retained state publishers remain `retain=True`.
- [ ] **Step 3: Implement event dataclass/serialization and event topics** under the existing raw MQTT base: PVE `<base>/event/diagnostic`, UPS `<base>/ups/event/diagnostic`.
- [ ] **Step 4: Implement bridge publishers without changing incoming command subscriptions.**
- [ ] **Step 5: Run event/transport tests GREEN and commit `feat(dh-pve): add diagnostic MQTT event transport`.**

---

### Task 4: Integrate coherent PVE problem-transition publication bundles

**Files:**
- Create: `dh_pve_app/app/runtime_problems.py`
- Create: `dh_pve_app/tests/test_problem_runtime.py`
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/tests/test_main_contract.py`

**Interfaces:**
- `ProblemAwareRuntime` subclasses `DynamicDiscoveryRuntime` and owns one `PveProblemEngine`.
- Problem state topics are retained under the current raw base:
  - `<base>/problems/<problem_id>/metric`
  - `<base>/problems/<problem_id>/state`
  - `<base>/problems/aggregate`
  - `<base>/problems/presentation`
- Extend bridge with typed retained publishers for those four topic classes rather than arbitrary caller-supplied MQTT topics.
- Threshold state continues to use existing retained `settings/<key>/state` publisher.

- [ ] **Step 1: Write RED runtime test with a recording fake bridge.** Drive CPU samples across the 60-second decision window and assert exact publish order: metric -> threshold -> binary -> aggregate -> presentation -> event.
- [ ] **Step 2: Add RED test proving the event is omitted when any required retained publish before it fails.** Failed state publish is retried later; a diagnostic event must never claim a transition whose retained state bundle did not complete.
- [ ] **Step 3: Add RED threshold-update test.** MQTT number command updates/persists the value, immediately reevaluates current problem state, and emits the same ordered bundle when it changes the problem.
- [ ] **Step 4: Implement `ProblemAwareRuntime`.** Feed only newly collected subsystem names to `PveProblemEngine`, preserve existing scheduler intervals, and keep regular presentation publication independent.
- [ ] **Step 5: Persist threshold settings through the existing runtime state store only after a validated update.** Do not add a second threshold state file.
- [ ] **Step 6: Wire `build_runtime()` to `ProblemAwareRuntime`; assert scheduler intervals are unchanged before/after problem transitions and threshold edits.
- [ ] **Step 7: Run runtime/main focused tests GREEN and commit `feat(dh-pve): publish coherent problem transitions`.**

---

### Task 5: Build canonical PVE Discovery components

**Files:**
- Modify: `dh_pve_app/app/topics.py`
- Modify: `dh_pve_app/app/discovery.py`
- Modify: `dh_pve_app/app/discovery_metrics.py`
- Modify: `dh_pve_app/app/discovery_groups.py`
- Modify: `dh_pve_app/tests/test_discovery.py`
- Modify: `dh_pve_app/tests/test_discovery_groups.py`
- Modify: `dh_pve_app/tests/test_full_discovery.py`

**Interfaces:**
- PVE device ID: `dh_app_pve_<instance_id>`.
- Device Discovery topic: `<discovery_prefix>/device/dh_app_pve_<instance_id>/config`.
- All PVE `unique_id` values derive from the canonical device ID.
- Canonical telemetry IDs include `sensor.dh_app_pve_cpu_usage`, `sensor.dh_app_pve_cpu_temperature`, `sensor.dh_app_pve_cpu_frequency`, `sensor.dh_app_pve_memory_usage`, `sensor.dh_app_pve_swap_usage`, per-storage `..._percent_used`, per-disk temperature/wear, per-GPU temperature/transcoding and per-fan RPM.
- Problem binary IDs are `binary_sensor.dh_app_pve_<problem-object>_problem` using stable object slugs.
- Aggregate sensor is `sensor.dh_app_pve_problems`.
- Event entity is `event.dh_app_pve_diagnostic` with `platform: event`, state topic `<base>/event/diagnostic`, `event_types: [problem_started, problem_recovered, problem_updated]`, diagnostic category, and no Recorder requirement.

- [ ] **Step 1: Write RED identity tests** for device ID, discovery topic, representative telemetry IDs and absence of new `dh_pve_*` default IDs.
- [ ] **Step 2: Add RED problem Discovery tests.** Dynamic storage/disk/GPU inventory creates matching problem binaries; CPU threshold/throttling problems are fixed components; all use `device_class: problem` and `entity_category: diagnostic`.
- [ ] **Step 3: Add RED aggregate/event Discovery tests.** Aggregate state reads count from the aggregate retained topic and compact details from the presentation topic; Event follows current Home Assistant MQTT Event device-discovery contract (`platform: event`, JSON `event_type`, explicit event_types).
- [ ] **Step 4: Implement canonical naming and components without changing raw collection cadence or source code.**
- [ ] **Step 5: Run PVE Discovery suites GREEN and commit `refactor(dh-pve): publish canonical PVE discovery contract`.**

---

### Task 6: Build canonical UPS identity, aggregate and diagnostic event boundary

**Files:**
- Modify: `dh_pve_app/app/topics.py`
- Modify: `dh_pve_app/app/discovery_ups.py`
- Modify: `dh_pve_app/app/discovery_ups_groups.py`
- Modify: `dh_pve_app/app/ups_group_runtime.py`
- Modify: `dh_pve_app/tests/test_ups_discovery.py`
- Modify: `dh_pve_app/tests/test_ups_group_runtime.py`

**Interfaces:**
- UPS device ID: `dh_app_pve_ups_<instance_id>`.
- UPS Discovery topic: `<discovery_prefix>/device/dh_app_pve_ups_<instance_id>/config`.
- Canonical entity IDs use `dh_app_pve_ups_*`.
- Aggregate sensor: `sensor.dh_app_pve_ups_problems`.
- Event entity: `event.dh_app_pve_ups_diagnostic` on `<base>/ups/event/diagnostic` with the same schema version/event types as PVE.
- Existing UPS problem interpretation remains authoritative; this task does not change Trigger Policy or NUT shutdown behavior.

- [ ] **Step 1: Write RED canonical UPS identity tests.**
- [ ] **Step 2: Write RED aggregate tests using existing UPS problem fields (`problems_count`, `problems_severity`, `problems`, `problems_details`).** Aggregate payload must be self-contained for future startup reconciliation.
- [ ] **Step 3: Write RED transition-event tests.** A change in the active UPS problem set emits started/recovered/updated after retained status/aggregate/presentation publishes; unchanged polls emit no duplicate event.
- [ ] **Step 4: Implement canonical UPS Discovery/transition boundary while preserving current UPS collection and control behavior.**
- [ ] **Step 5: Run UPS Discovery/runtime tests GREEN and commit `refactor(dh-pve): publish canonical UPS diagnostics contract`.**

---

### Task 7: Replace ad-hoc cleanup with versioned retained Discovery migration

**Files:**
- Create: `dh_pve_app/app/discovery_migration.py`
- Create: `dh_pve_app/tests/test_discovery_migration.py`
- Modify: `dh_pve_app/app/runtime_dynamic.py`
- Modify: `dh_pve_app/app/ups_group_runtime.py`
- Modify: `dh_pve_app/app/mqtt_bridge.py`
- Modify: `dh_pve_app/app/main.py`

**Interfaces:**
- Current `DISCOVERY_SCHEMA_VERSION = 2` for this canonical identity migration.
- Persistent state file: `/var/lib/dh_pve_app/discovery_schema.json`, via existing `StateStore`, containing `{"schema_version": 2}` only after successful migration/new schema publish.
- `DiscoveryMigrationPlan` contains exact owned retained topics to tombstone for PVE and UPS.
- Manifest includes at minimum previous device-discovery topics for `dh_pve_<instance>`, `dh_pve_ups_<instance>`, `dh_ups_<instance>`, and the retired setting-number cleanup owned by this App. Known legacy monolithic state topics are tombstoned only when owned by this App.

- [ ] **Step 1: Write RED migration-plan tests.** Exact old topic list is deterministic from `MqttConfig`, identity and Discovery prefix; canonical new topics are never included in tombstones.
- [ ] **Step 2: Write RED success test.** Order is tombstones -> new PVE Discovery -> new UPS Discovery (when enabled) -> persist schema version.
- [ ] **Step 3: Write RED interrupted migration tests.** Failure on any tombstone or new Discovery publish does not persist version; next startup repeats safely and converges.
- [ ] **Step 4: Write RED idempotency test.** Once schema 2 is persisted, startup skips migration tombstones but still republishes current retained Discovery normally.
- [ ] **Step 5: Implement migration coordinator and remove `_legacy_discovery_cleanup_done` / one-off UPS cleanup as authoritative migration mechanisms.** Keep only compatibility helpers used by the coordinator.
- [ ] **Step 6: Run migration + runtime startup/reconnect tests GREEN and commit `refactor(dh-pve): version discovery migration`.**

---

### Task 8: Simplify HA package/dashboard to the new ready-state contract

**Files:**
- Modify: `dh_pve_app/examples/packages/dh_app_pve_package.yaml`
- Modify: `dh_pve_app/examples/dh_pve_dashboard.yaml`
- Modify: `dh_pve_app/tests/test_ha_package_contract.py`
- Modify: `dh_pve_app/tests/test_dashboard_contract.py`

**Interfaces:**
- HA package has no `input_number` threshold helpers and no threshold-calculation templates.
- Recorder uses explicit entity whitelist only; no `sensor.dh_app_pve_*` or `binary_sensor.dh_app_pve_*` globs.
- Recorded PVE list contains useful numeric telemetry from the frozen design; dynamic per-object rows are generated in the example package only where exact inventory-specific IDs cannot be known statically, and are documented for site generation rather than broad glob recording.
- `sensor.dh_app_pve_ups_status` is explicitly included in Recorder and Logbook; useful UPS charge/runtime/load/voltage telemetry is explicitly listed.
- Dashboard consumes `sensor.dh_app_pve_problems` and canonical problem binaries/numbers instead of scanning `states.sensor`, `states.binary_sensor`, or legacy HA threshold helpers.
- This task does **not** add notification delivery automations. Later notification work consumes native Event payloads and aggregate startup reconciliation.

- [ ] **Step 1: Rewrite package/dashboard contract tests RED.** Assert no `entity_globs`, no `input_number`, no `states.sensor`/`states.binary_sensor` wildcard problem scans, no `dh_proxmox_` or `dh_pve_` entity IDs, and presence of canonical aggregate/threshold entities.
- [ ] **Step 2: Replace package with explicit Recorder/Logbook whitelist and comments describing site-specific expansion for dynamic inventory.**
- [ ] **Step 3: Replace dashboard problem-summary calculation with the app aggregate and ready problem entities; keep display-only formatting in HA.**
- [ ] **Step 4: Run package/dashboard tests GREEN and commit `refactor(dh-pve): simplify HA contract for app-owned problems`.**

---

### Task 9: Plan 2 integration and boundary verification

**Files:**
- Modify only files required by failing integration tests and documentation.
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`
- Modify: `docs/digitalhouses_pve_agent/plans/2026-09-15-dh-pve-ups-trigger-policy-v2.md` only to replace the stale deleted-observability dependency with this completed Plan 2 + canonical spec dependency; do not implement Trigger Policy yet.

**Interfaces:**
- Delivers the Discovery/problem/event boundary required before UPS Trigger Policy v2.

- [ ] **Step 1: Run focused suites:** `tests/test_runtime_settings.py tests/test_runtime_windows.py tests/test_problems.py tests/test_diagnostic_events.py tests/test_problem_runtime.py tests/test_discovery.py tests/test_discovery_groups.py tests/test_full_discovery.py tests/test_ups_discovery.py tests/test_ups_group_runtime.py tests/test_discovery_migration.py tests/test_mqtt_transport.py tests/test_ha_package_contract.py tests/test_dashboard_contract.py`.
- [ ] **Step 2: Run full `PYTHONPATH=. python -m pytest -q`.**
- [ ] **Step 3: Source-contract scan.** Production source must contain no new HA-side threshold logic, no active legacy entity prefixes in canonical Discovery builders, no runtime event publisher with `retain=True`, and no threshold edit that mutates scheduler intervals.
- [ ] **Step 4: Verify migration sequence and event-last ordering from tests, not comments.**
- [ ] **Step 5: Update README/CHANGELOG with canonical entity prefixes, threshold defaults, strict threshold semantics, event schema, retained/non-retained distinction and migration behavior.
- [ ] **Step 6: Update the stale dependency paragraph in `2026-09-15-dh-pve-ups-trigger-policy-v2.md` to depend on the frozen simplified-runtime spec, completed runtime-foundation plan and this Plan 2. Do not change Trigger Policy behavior.
- [ ] **Step 7: Run repository validator/full GitHub Actions and review final diff before declaring Plan 2 complete.**

## Plan boundary

After this plan is GREEN, do not merge UPS Trigger Policy implementation into the same review. The next phase may implement the already approved UPS telemetry/status/charger improvements and UPS Trigger Policy v2, using this plan's canonical Discovery identity, app-owned problem/event contract and migration state as dependencies.
