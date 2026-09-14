# DH PVE Adaptive MQTT / Recorder v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace monolithic delta-based PVE/UPS MQTT state publication with resource-local adaptive averaging and independent retained state groups while preserving raw collectors and UPS/shutdown safety logic.

**Architecture:** Add a small presentation engine that owns rolling decision windows, profile hysteresis, publication buckets and duplicate suppression. Runtime code feeds raw collector samples into resource-local groups; discovery routes existing HA entities to the smallest matching retained state topic. Continuous numeric values are averaged, while discrete/change/event/static data bypass averaging.

**Tech Stack:** Python 3.13, pytest, paho-mqtt, Home Assistant MQTT Device Discovery, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-14-dh-pve-adaptive-mqtt-recorder-v2-design.md`

## Global Constraints

- Keep raw collectors and internal raw application logic unchanged.
- Critical HA average window defaults to 30 s; high 60 s; normal 600 s; quiet 3600 s.
- `decision_window` is independent from `average_window`.
- CPU throttling is immediate CPU-critical.
- Resource profiles are independent: CPU/RAM/each disk/each GPU/UPS do not accelerate unrelated groups.
- Manual Refresh publishes factual current values for all groups without resetting decision history/buckets.
- Broad Recorder `dh_pve_*` globs must remain safe without per-entity exclusions.
- Existing UPS shutdown policy/history/safety behavior must remain green.
- TDD: every production behavior begins with a failing test.

---

### Task 1: Adaptive presentation core

**Files:**
- Create: `dh_pve_app/app/presentation.py`
- Create: `dh_pve_app/tests/test_presentation.py`

**Interfaces:**
- `PublicationProfile(str, Enum)`: `quiet`, `normal`, `high`, `critical`.
- `ProfileWindows(critical=30.0, high=60.0, normal=600.0, quiet=3600.0)`.
- `ThresholdSelector` with enter/exit thresholds and fixed `decision_window_seconds`.
- `AdaptiveGroup.observe(now, continuous, discrete, force=False, manual=False) -> GroupDecision`.
- `GroupDecision(publish, profile, reason, values, profile_changed)`.

- [ ] **Step 1: Write failing tests** for rolling averages, critical=30 s, hysteresis, immediate discrete trigger, duplicate suppression and manual snapshot preserving bucket state.
- [ ] **Step 2: Run `PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_presentation.py -q` and verify RED.**
- [ ] **Step 3: Implement the minimal engine** using timestamped deques for decision samples and per-bucket samples. Numeric bucket output is arithmetic mean of samples; ordinary bucket close may suppress identical rounded values. Manual output uses current values and does not reset rolling/bucket history.
- [ ] **Step 4: Run the focused tests and verify GREEN.**
- [ ] **Step 5: Commit `feat(dh-pve): add adaptive presentation engine`.**

### Task 2: Resource profile policy

**Files:**
- Create: `dh_pve_app/app/presentation_policy.py`
- Create: `dh_pve_app/tests/test_presentation_policy.py`
- Modify: `dh_pve_app/app/disk_health.py`

**Interfaces:**
- `ResourcePolicy.profile_for_cpu(...)`.
- `ResourcePolicy.profile_for_memory(...)`.
- `ResourcePolicy.profile_for_disk(disk_type, ...)`.
- `ResourcePolicy.profile_for_gpu(...)`.
- `ResourcePolicy.profile_for_ups(...)`.
- `disk_temperature_limits(disk_type) -> tuple[float, float]` shared with disk health.

- [ ] **Step 1: Write failing policy tests** proving CPU load/temp/throttling, RAM 70-90% normal behavior, per-disk thresholds, GPU independence and UPS discrete escalation.
- [ ] **Step 2: Run focused tests and verify RED.**
- [ ] **Step 3: Implement policy constants/hysteresis only; keep values centralized and easy to tune.**
- [ ] **Step 4: Run focused tests and existing disk-health tests; verify GREEN.**
- [ ] **Step 5: Commit `feat(dh-pve): add resource-local publication profiles`.**

### Task 3: MQTT group topics and bridge

**Files:**
- Modify: `dh_pve_app/app/topics.py`
- Modify: `dh_pve_app/app/mqtt_bridge.py`
- Create/modify: `dh_pve_app/tests/test_topics.py`
- Modify: `dh_pve_app/tests/test_mqtt_bridge.py` or nearest bridge contract test.

**Interfaces:**
- `state_group_topic(topics, group: str) -> str`.
- `ups_state_group_topic(topics, group: str) -> str`.
- `MqttBridge.publish_state_group(group, payload)`.
- `MqttBridge.publish_ups_state_group(group, payload)`.

- [ ] **Step 1: Write failing tests** for stable group topic paths and retained QoS1 group publication.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement sanitized group topic helpers and bridge methods while keeping legacy methods temporarily for migration/reconnect compatibility.**
- [ ] **Step 4: Verify GREEN.**
- [ ] **Step 5: Commit `feat(dh-pve): add independent MQTT state groups`.**

### Task 4: PVE presentation router and runtime integration

**Files:**
- Create: `dh_pve_app/app/presentation_pve.py`
- Modify: `dh_pve_app/app/app.py`
- Modify: `dh_pve_app/app/runtime_dynamic.py`
- Modify: `dh_pve_app/app/main.py`
- Create: `dh_pve_app/tests/test_pve_presentation.py`
- Modify: `dh_pve_app/tests/test_app_runtime.py`
- Modify: `dh_pve_app/tests/test_runtime_dynamic.py`

**Interfaces:**
- `PvePresentationRouter.observe_subsystem(name, state, now, manual=False, force=False) -> tuple[Publication, ...]`.
- `Publication(group, payload, reason, profile)`.
- groups: `host`, `cpu`, `memory`, per-storage, per-disk `telemetry/status`, per-GPU `telemetry/status`, `fans`, guest/status/topology/shutdown/collector/diagnostics.

- [ ] **Step 1: Write failing tests** that CPU critical only publishes CPU, a hot disk only publishes that disk telemetry, discrete SMART/status changes bypass averaging, and manual Refresh emits all current groups.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement partial payload builders preserving current `value_json.subsystems...` shape, but include only data needed by each group. Continuous fields are replaced with averaged values before publication.**
- [ ] **Step 4: Replace `DhPveRuntime.run_collection()` whole-state publication with router publications; keep internal `_subsystems` raw. On successful publication update diagnostics metadata.**
- [ ] **Step 5: Make reconnect republish retained group snapshots instead of one monolithic state.**
- [ ] **Step 6: Run runtime tests and verify GREEN.**
- [ ] **Step 7: Commit `feat(dh-pve): route PVE state through adaptive groups`.**

### Task 5: Discovery routing and Recorder-safe attributes

**Files:**
- Create: `dh_pve_app/app/discovery_groups.py`
- Modify: `dh_pve_app/app/shutdown_discovery.py`
- Modify: `dh_pve_app/app/discovery_ups.py` / `shutdown_discovery.py` UPS builder as needed
- Modify: `dh_pve_app/app/discovery_metrics.py`
- Modify: `dh_pve_app/tests/test_full_discovery.py`
- Modify: `dh_pve_app/tests/test_discovery_polish.py`

**Interfaces:**
- `route_pve_discovery_groups(payload, topics) -> payload`.
- `route_ups_discovery_groups(payload, topics) -> payload`.

- [ ] **Step 1: Write failing discovery tests** proving CPU entities use CPU group, RAM uses memory, one disk temperature uses its telemetry group, disk health/counters use status group, GPU owner vs telemetry split, and unrelated entities do not share state topics where that would cause cross-updates.
- [ ] **Step 2: Add failing tests** asserting continuous-sensor attributes do not include volatile `used_gib`/storage status/raw numeric duplicates.
- [ ] **Step 3: Verify RED.**
- [ ] **Step 4: Implement discovery post-routing without changing existing entity IDs/unique IDs.**
- [ ] **Step 5: Remove volatile numeric attributes from RAM/storage continuous entities; keep stable metadata such as total capacity/type where useful.**
- [ ] **Step 6: Add discovery for `sensor.dh_pve_app_profile` and `sensor.dh_pve_last_publication` on diagnostics group.**
- [ ] **Step 7: Verify discovery tests GREEN.**
- [ ] **Step 8: Commit `feat(dh-pve): route discovery to recorder-safe groups`.**

### Task 6: UPS adaptive group integration

**Files:**
- Create: `dh_pve_app/app/presentation_ups.py`
- Modify: `dh_pve_app/app/ups_runtime.py`
- Modify: `dh_pve_app/app/shutdown_integration.py` only if required for payload extension compatibility
- Modify: `dh_pve_app/tests/test_ups_runtime.py`
- Replace/update: `dh_pve_app/tests/test_ups_adaptive_publish.py`

**Interfaces:**
- UPS groups: `telemetry`, `status`, `config`, `tests`, `diagnostics`.
- Telemetry uses adaptive averages; status/config/tests use immediate/change-only semantics.

- [ ] **Step 1: Write failing tests** for on-battery immediate high, low-battery/overload critical, numeric telemetry averaging, and independence from PVE profiles.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement UPS presentation router preserving raw `UpsSnapshot` for safety/business logic.**
- [ ] **Step 4: Replace monolithic UPS publication with group publication; reconnect republishes retained groups.**
- [ ] **Step 5: Verify UPS policy/shutdown/test scheduling suites remain GREEN.**
- [ ] **Step 6: Commit `feat(dh-pve): adapt UPS MQTT presentation`.**

### Task 7: Remove legacy publication-delta controls and simplify HA package

**Files:**
- Modify: `dh_pve_app/app/runtime_settings.py`
- Modify: `dh_pve_app/app/discovery.py`
- Modify: `dh_pve_app/examples/packages/dh_app_pve_package.yaml`
- Modify: `dh_pve_app/tests/test_runtime_settings.py` or relevant settings tests
- Modify: `dh_pve_app/tests/test_ha_package_contract.py`

**Interfaces:**
- Keep only supported raw collection interval settings.
- Legacy `*_publish_delta` discovery components receive tombstones during migration.

- [ ] **Step 1: Write failing tests** that delta controls are absent from desired discovery/settings and package no longer depends on publication helpers.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Remove delta settings from runtime settings and discovery; add explicit legacy component tombstones/cleanup version.**
- [ ] **Step 4: Audit six HA `input_number` thresholds. Retain only if used by independent notification logic; otherwise remove them and startup default automation.**
- [ ] **Step 5: Keep broad Recorder include globs unchanged.**
- [ ] **Step 6: Verify package/settings tests GREEN.**
- [ ] **Step 7: Commit `refactor(dh-pve): remove legacy MQTT delta controls`.**

### Task 8: Documentation, migration and full verification

**Files:**
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`
- Modify: `dh_pve_app/VERSION` only if release policy requires a version bump for deploy
- Modify/add tests if contract review exposes a gap.

- [ ] **Step 1: Document profiles, windows, decision windows, manual Refresh semantics, diagnostics and tuning parameters.**
- [ ] **Step 2: Document legacy delta-control removal and HA migration.**
- [ ] **Step 3: Run focused DH PVE suite:** `PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q`.
- [ ] **Step 4: Run compile check:** `python -m compileall -q dh_pve_app/app dh_pve_app/tests`.
- [ ] **Step 5: Run installer/systemd validation through repository CI.**
- [ ] **Step 6: Review PR diff for unrelated changes, raw-data leakage in continuous attributes, and accidental UPS safety changes.**
- [ ] **Step 7: Commit docs/migration updates.**

### Task 9: Home PVE deploy preflight

**Target:** `192.168.11.30`

- [ ] **Step 1: Before deploy capture current service/config/version/runtime state and copy current installed app as rollback backup.**
- [ ] **Step 2: Deploy the reviewed branch using the repository installer/update path; do not alter NUT shutdown policy.**
- [ ] **Step 3: Restart `dh_pve_app.service` and inspect journal for collection/MQTT/discovery errors.**
- [ ] **Step 4: Verify HA device/entity continuity, `app_profile`, `last_publication`, Refresh-all behavior and UPS telemetry/status groups.**
- [ ] **Step 5: Verify Recorder rows no longer churn from unrelated group publication.**
- [ ] **Step 6: Keep tuning at defaults initially; adjust only policy parameters after enough real history exists.**
