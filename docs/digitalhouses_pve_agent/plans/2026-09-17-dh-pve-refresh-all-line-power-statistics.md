# DH PVE Refresh All and Line-Power Statistics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make either HA Refresh control perform one coherent full PVE+UPS refresh, and add app-owned monthly city-power availability statistics with 10-minute ONLINE and 10-second OFFLINE publication.

**Architecture:** Add an isolated `LinePowerStatisticsTracker` that owns monthly accounting/persistence from normalized NUT OL/OB/UNKNOWN state. Feed its snapshot into a dedicated UPS presentation group with its own publication cadence. Add a runtime-level full-refresh coordinator so either existing refresh MQTT button executes PVE/config first, then UPS/NUT and shutdown-derived recalculation, with one successful global refresh timestamp only after the complete sequence succeeds.

**Tech Stack:** Python 3, pytest, paho-mqtt, Home Assistant MQTT Discovery/Lovelace YAML, existing `StateStore`, grouped MQTT presentation runtime.

**Spec:** `docs/digitalhouses_pve_agent/specs/2026-09-17-dh-pve-refresh-all-line-power-statistics-design.md`

## Global Constraints

- Proxmox VE 8.x only.
- No migration/backfill from existing HA/Recorder statistics; tracking starts at the first trustworthy observation made by this feature.
- NUT status is authoritative: OL=ONLINE, OB=OFFLINE, unavailable/ambiguous=UNKNOWN.
- Input voltage must never be used as a city-power availability heuristic.
- Fixed UPS acquisition cadence remains 10 s.
- Monthly-statistics MQTT publication cadence is ONLINE=600 s, OFFLINE=10 s, transitions immediate.
- UNKNOWN time is excluded from availability denominator and never counted as outage time.
- Persist transitions/month boundaries, not every 10-second publication.
- Manual Refresh means Refresh All and bypasses scheduler/publication suppression.
- Full refresh dependency order: fresh PVE/config -> fresh UPS/NUT -> fresh shutdown-derived values -> publication/last_refresh.
- HA is presentation-only for monthly accounting; no availability arithmetic from Recorder/history.

---

## File Structure

- Create `dh_pve_app/app/line_power_statistics.py` — pure monthly accounting, month rollover, state persistence model, snapshot formatting metadata.
- Create `dh_pve_app/app/full_refresh.py` — small coordinator for full PVE+UPS refresh ordering and success semantics.
- Modify `dh_pve_app/app/ups_group_runtime.py` — observe NUT state through the tracker and publish the dedicated statistics group.
- Modify `dh_pve_app/app/presentation_ups.py` — route `line_power_statistics` on 600 s / 10 s cadence and immediate state changes.
- Modify `dh_pve_app/app/discovery_ups.py` and `dh_pve_app/app/discovery_ups_groups.py` — Discovery entities and group routing for current line power/month summary.
- Modify `dh_pve_app/app/main.py` — construct tracker/coordinator and intercept either refresh event before normal per-runtime event handling.
- Modify `dh_pve_app/app/mqtt_bridge.py` — make both existing refresh command topics request the same global refresh event while keeping entity IDs compatible.
- Modify `dh_pve_app/examples/dh_app_pve_ups_dashboard.yaml` — permanent 2x2 monthly statistics card, global Refresh label, current-line-power status, shutdown table wording/behavior.
- Add/modify tests under `dh_pve_app/tests/` for each contract below.

---

### Task 1: Pure line-power monthly tracker

**Files:**
- Create: `dh_pve_app/app/line_power_statistics.py`
- Create: `dh_pve_app/tests/test_line_power_statistics.py`

**Interfaces:**
- Produces `LinePowerState(str, Enum)` values `ONLINE`, `OFFLINE`, `UNKNOWN`.
- Produces `LinePowerStatisticsSnapshot` with `month_key`, `month_label_ru`, `tracking_since`, `partial_month`, `state`, `state_since`, `online_seconds`, `offline_seconds`, `unknown_seconds`, `outages_month`, `availability_percent`, `current_outage_started`, `last_failure`, `last_restore`, `last_outage_duration_seconds`, `estimated_restore`.
- Produces `LinePowerStatisticsTracker(store: StateStore, now_local: Callable[[], datetime])` with `observe(state: LinePowerState) -> bool` and `snapshot() -> LinePowerStatisticsSnapshot`.

- [ ] **Step 1: Write RED tests for first observation and no backfill**

```python
def test_first_online_observation_starts_partial_month_without_backfill(tmp_path):
    clock = Clock("2026-09-17T03:00:00+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(tmp_path / "line.json"), clock.now)

    assert tracker.observe(LinePowerState.ONLINE) is True
    snap = tracker.snapshot()

    assert snap.month_key == "2026-09"
    assert snap.partial_month is True
    assert snap.tracking_since == "2026-09-17T03:00:00+05:00"
    assert snap.online_seconds == 0
    assert snap.offline_seconds == 0
    assert snap.outages_month == 0
```

- [ ] **Step 2: Write RED tests for ONLINE/OFFLINE/UNKNOWN accounting**

```python
def test_unknown_is_excluded_from_availability_denominator(tmp_path):
    clock = Clock("2026-09-17T03:00:00+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(tmp_path / "line.json"), clock.now)
    tracker.observe(LinePowerState.ONLINE)
    clock.advance(seconds=100)
    tracker.observe(LinePowerState.UNKNOWN)
    clock.advance(seconds=50)
    tracker.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=100)

    snap = tracker.snapshot()
    assert snap.online_seconds == 100
    assert snap.unknown_seconds == 50
    assert snap.offline_seconds == 100
    assert snap.availability_percent == 50.0
    assert snap.outages_month == 1
```

- [ ] **Step 3: Write RED tests for outage close, restart, and estimated restore**

```python
def test_restart_from_open_outage_marks_estimated_restore(tmp_path):
    path = tmp_path / "line.json"
    clock = Clock("2026-09-17T03:00:00+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(path), clock.now)
    tracker.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=120)

    restarted = LinePowerStatisticsTracker(StateStore(path), clock.now)
    assert restarted.observe(LinePowerState.ONLINE) is True
    snap = restarted.snapshot()
    assert snap.last_outage_duration_seconds == 120
    assert snap.estimated_restore is True
```

- [ ] **Step 4: Write RED tests for local month rollover and cross-month outage**

```python
def test_cross_month_outage_carries_state_without_incrementing_new_month_count(tmp_path):
    clock = Clock("2026-09-30T23:59:50+05:00")
    tracker = LinePowerStatisticsTracker(StateStore(tmp_path / "line.json"), clock.now)
    tracker.observe(LinePowerState.OFFLINE)
    clock.advance(seconds=20)

    snap = tracker.snapshot()
    assert snap.month_key == "2026-10"
    assert snap.offline_seconds == 10
    assert snap.outages_month == 0
```

- [ ] **Step 5: Run tracker tests and verify RED**

Run: `pytest -q dh_pve_app/tests/test_line_power_statistics.py`
Expected: FAIL because tracker module/types do not exist.

- [ ] **Step 6: Implement minimal tracker**

Implement enum/dataclass/tracker using timezone-aware local `datetime`, `StateStore.load()/save()`, transition persistence, month-boundary splitting, Russian month labels, availability `online/(online+offline)*100`, and no HA/Recorder migration path.

Core state classifier contract used later:

```python
def line_power_state_from_snapshot(snapshot: UpsSnapshot | None, *, nut_available: bool) -> LinePowerState:
    if not nut_available or snapshot is None:
        return LinePowerState.UNKNOWN
    tokens = set(snapshot.status_tokens)
    if "OL" in tokens and "OB" not in tokens:
        return LinePowerState.ONLINE
    if "OB" in tokens and "OL" not in tokens:
        return LinePowerState.OFFLINE
    return LinePowerState.UNKNOWN
```

- [ ] **Step 7: Run tracker tests and verify GREEN**

Run: `pytest -q dh_pve_app/tests/test_line_power_statistics.py`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add dh_pve_app/app/line_power_statistics.py dh_pve_app/tests/test_line_power_statistics.py
git commit -m "feat(dh-pve): add line-power monthly tracker"
```

---

### Task 2: Dedicated statistics publication group

**Files:**
- Modify: `dh_pve_app/app/presentation_ups.py`
- Modify: `dh_pve_app/app/ups_group_runtime.py`
- Create: `dh_pve_app/tests/test_line_power_publication.py`
- Modify: `dh_pve_app/tests/test_ups_presentation.py`

**Interfaces:**
- Consumes `LinePowerStatisticsTracker.snapshot()`.
- Produces UPS group `line_power_statistics` with one coherent payload.
- Publication policy: ONLINE 600 s, OFFLINE 10 s, transition/manual/startup immediate, UNKNOWN transition immediate but no OFFLINE 10 s loop.

- [ ] **Step 1: Write RED publication-cadence tests**

```python
def test_online_statistics_publish_every_600_seconds():
    group = LinePowerStatisticsGroup()
    payload = stats_payload(state="online")
    assert group.should_publish(payload, now=0, force=True)
    assert not group.should_publish(payload, now=599)
    assert group.should_publish(payload, now=600)


def test_offline_statistics_publish_every_10_seconds():
    group = LinePowerStatisticsGroup()
    payload = stats_payload(state="offline")
    assert group.should_publish(payload, now=0, force=True)
    assert not group.should_publish(payload, now=9)
    assert group.should_publish(payload, now=10)
```

- [ ] **Step 2: Write RED immediate-transition/UNKNOWN tests**

```python
def test_line_power_transition_publishes_immediately():
    group = LinePowerStatisticsGroup()
    assert group.should_publish(stats_payload(state="online"), now=0, force=True)
    assert group.should_publish(stats_payload(state="offline"), now=1)
    assert group.should_publish(stats_payload(state="unknown"), now=2)
```

- [ ] **Step 3: Run publication tests and verify RED**

Run: `pytest -q dh_pve_app/tests/test_line_power_publication.py dh_pve_app/tests/test_ups_presentation.py`
Expected: FAIL because the group/payload integration does not exist.

- [ ] **Step 4: Implement publication group**

Add `LinePowerStatisticsGroup` to `presentation_ups.py` with explicit `ONLINE_INTERVAL_SECONDS = 600.0` and `OFFLINE_INTERVAL_SECONDS = 10.0`. Add `line_power_statistics` to `UpsPresentationRouter.route()` from payload field `line_power_statistics` without folding it into NORMAL/DETAIL telemetry.

In `AdaptiveUpsRuntime`, create/receive the tracker, observe every NUT result, attach `tracker.snapshot().as_payload()` to the UPS payload, and on NUT read failure observe UNKNOWN before routing.

- [ ] **Step 5: Verify failed MQTT publish does not duplicate outage count**

Add a fake bridge that fails the first `line_power_statistics` publish; assert the tracker transition count stays `1` after retry.

- [ ] **Step 6: Run focused tests GREEN**

Run: `pytest -q dh_pve_app/tests/test_line_power_publication.py dh_pve_app/tests/test_ups_presentation.py dh_pve_app/tests/test_ups_problems_runtime.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add dh_pve_app/app/presentation_ups.py dh_pve_app/app/ups_group_runtime.py dh_pve_app/tests/test_line_power_publication.py dh_pve_app/tests/test_ups_presentation.py
git commit -m "feat(dh-pve): publish adaptive line-power statistics"
```

---

### Task 3: MQTT Discovery entities for monthly statistics

**Files:**
- Modify: `dh_pve_app/app/discovery_ups.py`
- Modify: `dh_pve_app/app/discovery_ups_groups.py`
- Modify: `dh_pve_app/tests/test_ups_discovery.py`
- Modify: `dh_pve_app/tests/test_ups_discovery_groups.py`
- Modify: `dh_pve_app/tests/test_ups_ui_contract.py`

**Interfaces:**
- State topic group: `ups_state_group_topic(topics, "line_power_statistics")`.
- Entities:
  - `binary_sensor.dh_app_pve_ups_line_power`
  - `sensor.dh_app_pve_ups_line_power_online_month`
  - `sensor.dh_app_pve_ups_line_power_offline_month`
  - `sensor.dh_app_pve_ups_line_power_outages_month`
  - `sensor.dh_app_pve_ups_line_power_availability_month`
  - supporting current/last outage timestamp/duration sensors as specified.

- [ ] **Step 1: Write RED Discovery contract tests**

Assert exact canonical IDs, units (`s`, `%`), duration/timestamp device classes where applicable, and group state topic `line_power_statistics`.

- [ ] **Step 2: Run Discovery tests RED**

Run: `pytest -q dh_pve_app/tests/test_ups_discovery.py dh_pve_app/tests/test_ups_discovery_groups.py dh_pve_app/tests/test_ups_ui_contract.py`
Expected: FAIL because components are absent.

- [ ] **Step 3: Implement Discovery components**

Add static components even when the current UPS snapshot lacks optional numeric telemetry. `line_power` availability depends on App availability; its value template must preserve UNKNOWN instead of coercing missing NUT state to OFF. Monthly summary sensors consume the coherent statistics group and expose month metadata in attributes.

- [ ] **Step 4: Run Discovery tests GREEN**

Run: `pytest -q dh_pve_app/tests/test_ups_discovery.py dh_pve_app/tests/test_ups_discovery_groups.py dh_pve_app/tests/test_ups_ui_contract.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/discovery_ups.py dh_pve_app/app/discovery_ups_groups.py dh_pve_app/tests/test_ups_discovery.py dh_pve_app/tests/test_ups_discovery_groups.py dh_pve_app/tests/test_ups_ui_contract.py
git commit -m "feat(dh-pve): expose line-power monthly entities"
```

---

### Task 4: Global Refresh All coordinator

**Files:**
- Create: `dh_pve_app/app/full_refresh.py`
- Modify: `dh_pve_app/app/app.py`
- Modify: `dh_pve_app/app/runtime_problems.py`
- Modify: `dh_pve_app/app/mqtt_bridge.py`
- Modify: `dh_pve_app/app/main.py`
- Create: `dh_pve_app/tests/test_full_refresh.py`
- Modify: `dh_pve_app/tests/test_app_runtime.py`
- Modify: `dh_pve_app/tests/test_mqtt_bridge.py`
- Modify: `dh_pve_app/tests/test_shutdown_integration.py`

**Interfaces:**
- Produces `FullRefreshCoordinator.refresh() -> bool`.
- PVE runtime gets a two-phase manual-refresh API so collection/publication can use a candidate timestamp without committing global success early.
- Both MQTT refresh topics request the same global event.

- [ ] **Step 1: Write RED MQTT tests proving both buttons request one global refresh**

```python
def test_pve_and_ups_refresh_topics_request_global_refresh(events, topics, ups_topics):
    events.configure_ups(ups_topics)
    assert events.handle_message(topics.refresh, b"PRESS") is True
    assert events.full_refresh_requested.is_set()
    events.full_refresh_requested.clear()
    assert events.handle_message(ups_topics.refresh, b"PRESS") is True
    assert events.full_refresh_requested.is_set()
```

- [ ] **Step 2: Write RED coordinator ordering test**

```python
def test_full_refresh_orders_pve_before_ups_and_commits_timestamp_last():
    calls = []
    pve = FakePveRuntime(calls)
    ups = FakeUpsRuntime(calls)
    coordinator = FullRefreshCoordinator(pve=pve, ups=ups, now_iso=lambda: "2026-09-17T03:00:00+00:00")

    assert coordinator.refresh() is True
    assert calls == ["pve_prepare", "ups_refresh", "pve_commit"]
```

- [ ] **Step 3: Write RED failure test**

```python
def test_failed_ups_stage_does_not_commit_global_last_refresh():
    calls = []
    pve = FakePveRuntime(calls)
    ups = FakeUpsRuntime(calls, success=False)
    coordinator = FullRefreshCoordinator(pve=pve, ups=ups, now_iso=lambda: "2026-09-17T03:00:00+00:00")

    assert coordinator.refresh() is False
    assert "pve_commit" not in calls
```

- [ ] **Step 4: Write RED integration test for `200 -> 100` timeout visibility**

Use a mutable VM 110 config fixture. First collect timeout `200`, change fixture to `100`, trigger one full refresh, assert the guest entity payload/current guest budget and shutdown budget use `100` without advancing simulated SLOW scheduler time.

- [ ] **Step 5: Run full-refresh tests RED**

Run: `pytest -q dh_pve_app/tests/test_full_refresh.py dh_pve_app/tests/test_app_runtime.py dh_pve_app/tests/test_mqtt_bridge.py dh_pve_app/tests/test_shutdown_integration.py`
Expected: FAIL because `full_refresh_requested`/coordinator/two-phase PVE refresh do not exist.

- [ ] **Step 6: Implement two-phase PVE refresh**

Refactor the PVE runtime so the coordinator can perform a forced manual collection/publication with a candidate refresh timestamp but defer persistence/authoritative `last_refresh` commit until the UPS stage succeeds. Keep existing `manual_refresh()` behavior for direct unit callers by implementing it through prepare+commit.

Required methods:

```python
def prepare_manual_refresh(self, candidate_refresh: str) -> bool: ...
def commit_manual_refresh(self, candidate_refresh: str) -> bool: ...
def manual_refresh(self) -> bool:
    candidate = self.now_iso()
    return self.prepare_manual_refresh(candidate) and self.commit_manual_refresh(candidate)
```

- [ ] **Step 7: Implement coordinator and main-loop interception**

Create `FullRefreshCoordinator`. In `main.run()`, service `bridge.full_refresh_requested` before `runtime.process_events()`/`ups_runtime.process_events()`, clear legacy per-runtime refresh events, run coordinator once, and wake normally afterward.

- [ ] **Step 8: Ensure UPS shutdown budget is forced after fresh PVE config**

The coordinator calls `ups_runtime.manual_refresh()` only after PVE prepare succeeds. `ShutdownAwareUpsRuntime._collect(... manual_refresh=True)` already forces shutdown-budget refresh; retain that behavior.

- [ ] **Step 9: Run focused tests GREEN**

Run: `pytest -q dh_pve_app/tests/test_full_refresh.py dh_pve_app/tests/test_app_runtime.py dh_pve_app/tests/test_mqtt_bridge.py dh_pve_app/tests/test_shutdown_integration.py`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add dh_pve_app/app/full_refresh.py dh_pve_app/app/app.py dh_pve_app/app/runtime_problems.py dh_pve_app/app/mqtt_bridge.py dh_pve_app/app/main.py dh_pve_app/tests/test_full_refresh.py dh_pve_app/tests/test_app_runtime.py dh_pve_app/tests/test_mqtt_bridge.py dh_pve_app/tests/test_shutdown_integration.py
git commit -m "feat(dh-pve): make manual refresh global"
```

---

### Task 5: Wire tracker persistence into production runtime

**Files:**
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/app/shutdown_integration.py`
- Modify: `dh_pve_app/tests/test_shutdown_integration.py`
- Modify: `dh_pve_app/tests/test_main.py` if present, otherwise add coverage to the existing runtime-construction test module.

**Interfaces:**
- Production tracker store: `StateStore(state_dir / "line_power_statistics.json")`.
- Production local clock: existing timezone-aware `_now_local`.
- No migration source is accepted.

- [ ] **Step 1: Write RED construction test**

Assert `build_ups_runtime()` receives a tracker backed by `line_power_statistics.json` and that no HA/Recorder/migration dependency is present.

- [ ] **Step 2: Run RED**

Run the focused runtime-construction test.
Expected: FAIL because tracker is not wired.

- [ ] **Step 3: Wire production tracker**

Construct one `LinePowerStatisticsTracker` per selected UPS runtime and pass it to `ShutdownAwareUpsRuntime`/`AdaptiveUpsRuntime` through an explicit constructor argument.

- [ ] **Step 4: Run GREEN**

Run the focused construction/integration tests.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/main.py dh_pve_app/app/shutdown_integration.py dh_pve_app/tests
git commit -m "feat(dh-pve): persist line-power statistics on PVE"
```

---

### Task 6: Dashboard UX

**Files:**
- Modify: `dh_pve_app/examples/dh_app_pve_ups_dashboard.yaml`
- Modify: `scripts/validators/apps/dh_pve_app.py`
- Add/modify: dashboard validation test if the repo has one for this example.

**Interfaces:**
- Permanent current-state card: city power ONLINE/OFFLINE/UNKNOWN.
- Permanent 2x2 monthly block with app-provided values and month label.
- Refresh label: `Обновить все данные`.
- Shutdown table: current running guests only, first line current app-provided calculated guest shutdown time, columns `Настроено`, `Факт`, `От лимита`, `Результат`.

- [ ] **Step 1: Add validator assertions before YAML change**

Require canonical monthly entity IDs in the dashboard and reject availability arithmetic based on `states.sensor`/Recorder for this block.

- [ ] **Step 2: Run validator RED**

Run: `python scripts/validators/apps/dh_pve_app.py`
Expected: FAIL until the dashboard contains the new contract.

- [ ] **Step 3: Implement current-state + 2x2 monthly cards**

Use a heading whose text comes from app month metadata, then four 6-column Mushroom cards:

```text
Свет был        -> online_month seconds formatted as д. HH:MM:SS
Света не было   -> offline_month seconds formatted as д. HH:MM:SS
Отключений      -> outages_month
Доступность     -> availability_month %
```

Do not wrap the monthly block in a condition based on current line power.

- [ ] **Step 4: Update shutdown table UX**

Show only currently running VM/LXC rows. Calculate `От лимита` for display from last real duration/current configured timeout, not `last_shutdown_timeout_ratio`. Put the current app-provided guest shutdown budget before the table. Keep the Proxmox navigation hint for changing `Start/Shutdown order -> Shutdown timeout`.

- [ ] **Step 5: Run validator GREEN**

Run: `python scripts/validators/apps/dh_pve_app.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/examples/dh_app_pve_ups_dashboard.yaml scripts/validators/apps/dh_pve_app.py
git commit -m "feat(dh-pve): add monthly power statistics UI"
```

---

### Task 7: Full regression, docs, and final review

**Files:**
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`
- Review all files changed by Tasks 1-6.

- [ ] **Step 1: Run full dh_pve_app test suite**

Run: `pytest -q dh_pve_app/tests`
Expected: all tests PASS.

- [ ] **Step 2: Run app validator**

Run: `python scripts/validators/apps/dh_pve_app.py`
Expected: PASS.

- [ ] **Step 3: Update README/CHANGELOG**

Document Refresh All semantics, line-power source contract, monthly entities, ONLINE/OFFLINE publication profile, no backfill/migration, and first-month `partial_month` behavior.

- [ ] **Step 4: Final diff review**

Verify no code:
- changes UPS acquisition cadence;
- treats NUT unavailable as outage;
- writes line-power state every 10 s;
- derives city power from voltage;
- imports HA historical statistics;
- advances global `last_refresh` before full refresh success;
- reintroduces HA-side shutdown authority.

- [ ] **Step 5: Commit docs**

```bash
git add dh_pve_app/README.md dh_pve_app/CHANGELOG.md
git commit -m "docs(dh-pve): document refresh-all power statistics"
```

- [ ] **Step 6: Verify branch CI and exact HEAD**

Confirm GitHub Actions is green for the final commit before any production deploy. Production validation is non-destructive; no FSD, output-off, deep discharge, or new mains-unplug validation is required by this implementation plan.
