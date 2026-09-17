# DH PVE Machine Events, UPS Status and Battery Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `dh_pve_app` from app-generated notification prose to schema-v2 machine events, add canonical UPS/charger semantics, discharge milestones, fully-charged detection and structured shutdown/config events, while moving all user-facing notification wording into HAOS locale packages.

**Architecture:** Keep acquisition, normalization, thresholds, problem decisions, UPS interpretation and shutdown authority in `dh_pve_app`. Publish only structured machine state/events over MQTT; use a small persisted event outbox for retry-safe UPS semantic events. HAOS locale packages consume v1 and v2 during migration, then format localized text/emoji without rereading unrelated entities.

**Tech Stack:** Python 3, NUT/upsc, Paho MQTT, Home Assistant MQTT Device Discovery/Event entities, YAML/Jinja HA packages, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-17-dh-pve-machine-events-ups-battery-design.md`

## Global Constraints

- Target runtime is Proxmox VE 8.x.
- UPS acquisition remains fixed at 10 seconds; this feature must not add a faster collection loop.
- `dh_pve_app` owns machine facts, normalization, thresholds, problem decisions and shutdown authority.
- HAOS owns language, labels, notification title/body, emoji, delivery/gating/repeat policy and which machine events are user-visible.
- New public machine-event payloads use `schema_version: 2`.
- MQTT Event messages remain QoS 1 and `retain=false`.
- Transition events carry previous + current state whenever authoritative.
- App event payloads must not contain `title`, `message`, `summary`, `details`, `recovery_message`, `status_ru`, localized notification prose or emoji.
- Internal journal/service logs may remain human-readable Russian.
- Raw NUT status tokens remain available diagnostically.
- `battery.charger.status` is preferred over CHRG/DISCHRG fallback.
- Battery discharge notification milestones are fixed at 90, 80, 70, 60, 50, 40, 30, 20 and 10 percent and are not user shutdown thresholds.
- `battery_fully_charged` means observed charge-cycle completion; 100% is not required.
- Native NUT FSD is distinct from the app's `shutdown_committed` event.
- No destructive validation: no casual FSD, mains unplug, UPS output-off, deep discharge or HA-side host shutdown.
- Migration order is HA-first compatibility -> app schema v2 -> production verification -> later v1 compatibility cleanup.
- Target release for this breaking event-contract change is `0.5.0`.

---

## File Structure / Responsibility Map

### Existing files to modify

- `dh_pve_app/app/problems.py` — machine-only problem state and aggregate; no generated prose.
- `dh_pve_app/app/diagnostic_events.py` — schema-v2 generic problem event serialization.
- `dh_pve_app/app/runtime_problems.py` — pass event timestamp and publish structured aggregates.
- `dh_pve_app/app/ups_health.py` — UPS problem observations become IDs/severity/facts only.
- `dh_pve_app/app/ups_problems.py` — machine-only retained UPS problem state; identify status-derived problem IDs whose notification transport is `ups_status_changed`.
- `dh_pve_app/app/ups_nut.py` — parse raw `battery.charger.status`, normalized status/charger fields and canonical compatibility booleans.
- `dh_pve_app/app/ups_runtime.py` — remove `_human_status()`/text problem fields and publish canonical machine state.
- `dh_pve_app/app/presentation_ups.py` — route canonical UPS status/charger machine fields; remove text problem payload fields.
- `dh_pve_app/app/ups_group_runtime.py` — schema-v2 problem events plus status/battery semantic trackers and retry-safe event outbox after retained-state publication.
- `dh_pve_app/app/shutdown_integration.py` — schema-v2 `config_changed` and `shutdown_committed` event creation.
- `dh_pve_app/app/discovery_ups.py` / `dh_pve_app/app/discovery_ups_groups.py` — canonical status/charger entities and expanded Event types.
- `dh_pve_app/app/discovery_groups.py` — generic diagnostic Event metadata.
- `dh_pve_app/app/main.py` — construct explicit UPS semantic state stores and inject them into the runtime.
- `dh_pve_app/examples/packages/dh_app_pve_notification_package.yaml` — English HA presentation, v1+v2 migration compatibility.
- `dh_pve_app/examples/packages/locales/ru/dh_app_pve_notification_package.yaml` — Russian HA presentation, v1+v2 migration compatibility.
- `dh_pve_app/examples/dh_app_pve_ups_dashboard.yaml` — expose canonical charger status in standard UPS UI.
- `scripts/validators/apps/dh_pve_app.py` — enforce machine-only event contract and new Discovery/HA package requirements.
- `dh_pve_app/README.md`, `dh_pve_app/CHANGELOG.md`, `dh_pve_app/VERSION` — document and release as 0.5.0.

### New focused files

- `dh_pve_app/app/ups_semantics.py` — pure status-token normalization and charger-state resolution; no MQTT or persistence.
- `dh_pve_app/app/machine_event_outbox.py` — tiny persisted idempotent outbox for retryable UPS semantic events.
- `dh_pve_app/app/ups_status_events.py` — previous/current canonical UPS status transition tracker.
- `dh_pve_app/app/ups_battery_events.py` — persistent discharge session, milestone crossing and fully-charged cycle tracker.

### New tests

- `dh_pve_app/tests/test_machine_event_outbox.py`
- `dh_pve_app/tests/test_ups_semantics.py`
- `dh_pve_app/tests/test_ups_status_events.py`
- `dh_pve_app/tests/test_ups_battery_events.py`
- `dh_pve_app/tests/test_ups_semantic_runtime.py`
- `dh_pve_app/tests/test_ha_notification_machine_events.py`

---

### Task 1: Prepare HA-first v1/v2 notification compatibility

**Files:**
- Modify: `dh_pve_app/examples/packages/dh_app_pve_notification_package.yaml`
- Modify: `dh_pve_app/examples/packages/locales/ru/dh_app_pve_notification_package.yaml`
- Create: `dh_pve_app/tests/test_ha_notification_machine_events.py`

**Interfaces:**
- Consumes current schema-v1 Event attributes and future schema-v2 machine fields.
- Produces one localized `dh_app_pve_notification` event per incoming user-visible machine event.
- Schema-v1 fallback remains until a later cleanup release; app never dual-publishes v1 and v2.

- [ ] **Step 1: Write failing static contract tests for both locale packages**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    ROOT / "examples/packages/dh_app_pve_notification_package.yaml",
    ROOT / "examples/packages/locales/ru/dh_app_pve_notification_package.yaml",
)


def test_notification_packages_accept_machine_event_v2_types():
    required = {
        "ups_status_changed",
        "battery_discharge_level_crossed",
        "battery_fully_charged",
        "shutdown_committed",
        "config_changed",
    }
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        assert "schema_version" in text
        for event_type in required:
            assert event_type in text


def test_notification_packages_have_v2_machine_fields():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        assert "previous_status" in text
        assert "current_status" in text
        assert "crossed_thresholds" in text
        assert "current_charge_percent" in text
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ha_notification_machine_events.py -q
```

Expected: FAIL because the packages currently understand only v1 problem/config events.

- [ ] **Step 3: Extend HA triggers and add schema-aware branches**

For `event.dh_app_pve_ups_diagnostic` include:

```yaml
event_type:
  - problem_started
  - problem_updated
  - problem_recovered
  - config_changed
  - ups_status_changed
  - battery_discharge_level_crossed
  - battery_fully_charged
  - shutdown_committed
```

Use:

```jinja2
{% set schema = trigger.to_state.attributes.schema_version | int(1) %}
{% set kind = trigger.to_state.attributes.event_type %}
```

Keep `summary/details/value/average/threshold` only inside the schema-v1 fallback. Schema v2 reads `previous/current`, previous/current status lists and structured numeric fields directly.

Russian HA wording to encode here, not in Python:

```text
on_battery entered       -> 🔋⚠️ UPS: городское питание отсутствует
on_battery -> online     -> 🔋✅ UPS: городское питание восстановлено
battery milestone        -> 🔋⚠️ UPS: заряд батареи <current>%
fully charged            -> 🔋✅ UPS: батарея заряжена
shutdown_committed       -> 🔋🛑 UPS: начато аварийное выключение
config_changed           -> 🔋⚙️ Конфигурация UPS Trigger изменена
```

Preserve `binary_sensor.bs_global_system_boot_completed` as the HA-only notification gate and keep `dh_app_pve_notification` as the reusable downstream event.

- [ ] **Step 4: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ha_notification_machine_events.py -q
```

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/examples/packages/dh_app_pve_notification_package.yaml \
  dh_pve_app/examples/packages/locales/ru/dh_app_pve_notification_package.yaml \
  dh_pve_app/tests/test_ha_notification_machine_events.py
git commit -m "feat(dh-pve): prepare HA notifications for machine event v2"
```

---

### Task 2: Convert generic problem state/events to schema-v2 machine semantics

**Files:**
- Modify: `dh_pve_app/app/problems.py`
- Modify: `dh_pve_app/app/diagnostic_events.py`
- Modify: `dh_pve_app/app/runtime_problems.py`
- Modify: `dh_pve_app/app/ups_group_runtime.py`
- Modify: `dh_pve_app/tests/test_problems.py`
- Modify: `dh_pve_app/tests/test_diagnostic_events.py`
- Modify: `dh_pve_app/tests/test_problem_runtime.py`
- Modify: `dh_pve_app/tests/test_ups_problem_runtime_v2.py`

**Interfaces:**
- `ProblemState` keeps `problem_id, category, severity, object_id, object_name, metric, active, value, average, threshold` and removes `summary/details`.
- `ProblemAggregate` keeps `count, severity, active` and removes generated summary prose.
- `DiagnosticEvent.from_transition(transition, *, active_problem_count: int, observed_at: str) -> DiagnosticEvent`.
- `DiagnosticEvent.as_payload()` emits schema version 2, problem metadata, `previous`, `current`, timestamp and `active_problem_count`.

- [ ] **Step 1: Rewrite tests first for exact v2 payload**

```python
payload = DiagnosticEvent.from_transition(
    transition,
    active_problem_count=1,
    observed_at="2026-09-17T06:00:00+05:00",
).as_payload()

assert payload == {
    "schema_version": 2,
    "event_type": "problem_started",
    "observed_at": "2026-09-17T06:00:00+05:00",
    "problem_id": "cpu_temperature",
    "category": "cpu",
    "severity": "warning",
    "object_id": "cpu",
    "object_name": "CPU",
    "metric": "temperature_c",
    "previous": {
        "active": False,
        "value": 76.0,
        "average": 75.4,
        "threshold": 80.0,
    },
    "current": {
        "active": True,
        "value": 84.0,
        "average": 81.2,
        "threshold": 80.0,
    },
    "active_problem_count": 1,
}
assert not ({"title", "message", "summary", "details", "status_ru"} & payload.keys())
```

Also test timezone-naive `observed_at` rejection and first inactive observation producing no transition.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_problems.py \
  dh_pve_app/tests/test_diagnostic_events.py \
  dh_pve_app/tests/test_problem_runtime.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py -q
```

- [ ] **Step 3: Remove generated prose from problem state and event serialization**

Use one serializer helper:

```python
def _transition_state(state: ProblemState | None) -> dict[str, object] | None:
    if state is None:
        return None
    return {
        "active": state.active,
        "value": state.value,
        "average": state.average,
        "threshold": state.threshold,
    }
```

Set `SCHEMA_VERSION = 2`. Validate `observed_at` with `datetime.fromisoformat()` and require timezone awareness.

- [ ] **Step 4: Update both PVE and UPS runtime callers**

Use exactly:

```python
event = DiagnosticEvent.from_transition(
    transition,
    active_problem_count=aggregate.count,
    observed_at=self.now_iso(),
)
```

- [ ] **Step 5: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_problems.py \
  dh_pve_app/tests/test_diagnostic_events.py \
  dh_pve_app/tests/test_problem_runtime.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/problems.py dh_pve_app/app/diagnostic_events.py \
  dh_pve_app/app/runtime_problems.py dh_pve_app/app/ups_group_runtime.py \
  dh_pve_app/tests/test_problems.py dh_pve_app/tests/test_diagnostic_events.py \
  dh_pve_app/tests/test_problem_runtime.py dh_pve_app/tests/test_ups_problem_runtime_v2.py
git commit -m "refactor(dh-pve): make problem events machine-only v2"
```

---

### Task 3: Remove prose from retained UPS problem observations/presentation

**Files:**
- Modify: `dh_pve_app/app/ups_health.py`
- Modify: `dh_pve_app/app/ups_problems.py`
- Modify: `dh_pve_app/app/ups_runtime.py`
- Modify: `dh_pve_app/app/presentation_ups.py`
- Modify: `dh_pve_app/tests/test_ups_problems.py`
- Modify: `dh_pve_app/tests/test_ups_problem_runtime_v2.py`
- Modify: `dh_pve_app/tests/test_ups_runtime.py`

**Interfaces:**
- `UpsProblemObservation` contains `problem_id, active, severity`; no `message` or `label`.
- Retained aggregate shape is `count`, `severity`, `active: list[dict]` with structured machine fields.
- Define `STATUS_DERIVED_UPS_PROBLEM_IDS = frozenset({"on_battery", "low_battery", "overload", "replace_battery", "bypass"})` for Task 7 de-duplication.

- [ ] **Step 1: Write RED assertions that retained UPS payloads contain no prose fields**

Representative active entry:

```python
assert aggregate.active[0] == {
    "problem_id": "on_battery",
    "category": "ups",
    "severity": "warning",
    "object_id": "ups",
    "object_name": "ups",
    "metric": "on_battery",
    "value": True,
    "average": None,
    "threshold": None,
}
```

Assert `summary`, `details`, localized messages and `problems_details` are absent from retained machine state.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_problems.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py \
  dh_pve_app/tests/test_ups_runtime.py -q
```

- [ ] **Step 3: Simplify observations and retained state**

Remove `message/label` from `UpsProblemObservation`; construct `ProblemState` from IDs/severity/factual values only. Remove `problems` text lists and `problems_details` from `ups_runtime.py` / `presentation_ups.py` machine payloads.

- [ ] **Step 4: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_problems.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py \
  dh_pve_app/tests/test_ups_runtime.py -q
```

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/ups_health.py dh_pve_app/app/ups_problems.py \
  dh_pve_app/app/ups_runtime.py dh_pve_app/app/presentation_ups.py \
  dh_pve_app/tests/test_ups_problems.py dh_pve_app/tests/test_ups_problem_runtime_v2.py \
  dh_pve_app/tests/test_ups_runtime.py
git commit -m "refactor(dh-pve): make UPS problem state machine-only"
```

---

### Task 4: Add pure canonical UPS and charger semantics

**Files:**
- Create: `dh_pve_app/app/ups_semantics.py`
- Modify: `dh_pve_app/app/ups_nut.py`
- Create: `dh_pve_app/tests/test_ups_semantics.py`
- Modify: `dh_pve_app/tests/test_ups_nut.py`

**Interfaces:**

```python
CANONICAL_STATUS_ORDER: tuple[str, ...]
PRIMARY_STATUS_PRECEDENCE: tuple[str, ...]

def normalize_ups_status(status_tokens: tuple[str, ...]) -> tuple[str, ...]: ...
def primary_ups_status(status_set: tuple[str, ...]) -> str: ...
def resolve_charger_status(
    *,
    direct_status: str | None,
    status_tokens: tuple[str, ...],
    line_power: bool,
) -> str: ...
```

Use this exact primary precedence:

```python
PRIMARY_STATUS_PRECEDENCE = (
    "forced_shutdown",
    "alarm",
    "overload",
    "replace_battery",
    "low_battery",
    "bypass",
    "calibration",
    "output_off",
    "on_battery",
    "boost",
    "trim",
    "high_battery",
    "online",
)
```

`UpsSnapshot` adds `normalized_status`, `primary_status`, `battery_charger_status_raw`, `battery_charger_status`. Compatibility booleans `charging/discharging` are derived from canonical charger status.

- [ ] **Step 1: Write normalization RED tests**

```python
assert normalize_ups_status(("OL", "BOOST", "CHRG")) == ("online", "boost")
assert normalize_ups_status(("OB", "DISCHRG", "LB")) == ("on_battery", "low_battery")
assert normalize_ups_status(("OL", "FUTURE_TOKEN")) == ("online",)
assert primary_ups_status(("online", "boost")) == "boost"

assert resolve_charger_status(
    direct_status="floating",
    status_tokens=("OL", "CHRG"),
    line_power=True,
) == "floating"
assert resolve_charger_status(
    direct_status=None,
    status_tokens=("OL", "CHRG"),
    line_power=True,
) == "charging"
assert resolve_charger_status(
    direct_status=None,
    status_tokens=("OL",),
    line_power=True,
) == "idle"
assert resolve_charger_status(
    direct_status="vendor-weird",
    status_tokens=("OL", "CHRG"),
    line_power=True,
) == "unknown"
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_semantics.py dh_pve_app/tests/test_ups_nut.py -q
```

- [ ] **Step 3: Implement pure resolver and parser fields**

```python
_STATUS_MAP = {
    "OL": "online",
    "OB": "on_battery",
    "LB": "low_battery",
    "HB": "high_battery",
    "RB": "replace_battery",
    "BYPASS": "bypass",
    "CAL": "calibration",
    "OFF": "output_off",
    "OVER": "overload",
    "TRIM": "trim",
    "BOOST": "boost",
    "FSD": "forced_shutdown",
    "ALARM": "alarm",
}
```

Do not map CHRG/DISCHRG into `normalized_status`; preserve them only in raw tokens and charger fallback evidence.

- [ ] **Step 4: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_semantics.py dh_pve_app/tests/test_ups_nut.py -q
```

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/ups_semantics.py dh_pve_app/app/ups_nut.py \
  dh_pve_app/tests/test_ups_semantics.py dh_pve_app/tests/test_ups_nut.py
git commit -m "feat(dh-pve): normalize UPS and charger machine state"
```

---

### Task 5: Publish canonical UPS status and charger state through MQTT Discovery

**Files:**
- Modify: `dh_pve_app/app/ups_runtime.py`
- Modify: `dh_pve_app/app/presentation_ups.py`
- Modify: `dh_pve_app/app/discovery_ups.py`
- Modify: `dh_pve_app/app/discovery_ups_groups.py`
- Modify: `dh_pve_app/tests/test_canonical_ups_discovery.py`
- Modify: `dh_pve_app/tests/test_ups_runtime.py`

**Interfaces:**
- `sensor.dh_app_pve_ups_status` state is `snapshot.primary_status`.
- Machine state includes `status_set` and `raw_status_tokens`.
- New `sensor.dh_app_pve_ups_battery_charger_status` is `charging|discharging|floating|resting|idle|unknown`.
- Existing charging/discharging binaries derive from canonical charger status; `unknown` must not be converted to a certain OFF state.

- [ ] **Step 1: Write RED Discovery/runtime tests**

```python
assert components["battery_charger_status"]["default_entity_id"] == (
    "sensor.dh_app_pve_ups_battery_charger_status"
)
assert "battery_charger_status" in components["battery_charger_status"]["value_template"]

assert payload["status"] == "boost"
assert payload["status_set"] == ["online", "boost"]
assert payload["raw_status_tokens"] == ["OL", "BOOST", "CHRG"]
assert payload["battery_charger_status"] == "charging"
assert "status_ru" not in payload
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_canonical_ups_discovery.py dh_pve_app/tests/test_ups_runtime.py -q
```

- [ ] **Step 3: Delete `_human_status()` and publish machine fields**

Use `snapshot.primary_status`, `snapshot.normalized_status`, raw tokens and canonical charger status. Remove Discovery references to `status_ru`.

- [ ] **Step 4: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_canonical_ups_discovery.py dh_pve_app/tests/test_ups_runtime.py -q
```

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/ups_runtime.py dh_pve_app/app/presentation_ups.py \
  dh_pve_app/app/discovery_ups.py dh_pve_app/app/discovery_ups_groups.py \
  dh_pve_app/tests/test_canonical_ups_discovery.py dh_pve_app/tests/test_ups_runtime.py
git commit -m "feat(dh-pve): expose canonical UPS charger state"
```

---

### Task 6: Add persisted machine-event outbox

**Files:**
- Create: `dh_pve_app/app/machine_event_outbox.py`
- Create: `dh_pve_app/tests/test_machine_event_outbox.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class PendingMachineEvent:
    key: str
    payload: dict[str, object]

class MachineEventOutbox:
    def __init__(self, state_store: StateStore) -> None: ...
    def enqueue(self, key: str, payload: dict[str, object]) -> bool: ...
    def pending(self) -> tuple[PendingMachineEvent, ...]: ...
    def acknowledge(self, key: str) -> None: ...
```

`enqueue()` is idempotent by key and persists before returning. `acknowledge()` removes only after MQTT publish succeeds. Persisted shape is `{"schema_version": 1, "pending": [...]}`.

- [ ] **Step 1: Write RED persistence/idempotency tests**

```python
outbox.enqueue("status:1", {"event_type": "ups_status_changed"})
outbox.enqueue("status:1", {"event_type": "ups_status_changed"})
assert [item.key for item in outbox.pending()] == ["status:1"]

reloaded = MachineEventOutbox(store)
assert reloaded.pending()[0].payload["event_type"] == "ups_status_changed"
reloaded.acknowledge("status:1")
assert reloaded.pending() == ()
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_machine_event_outbox.py -q
```

- [ ] **Step 3: Implement minimal versioned outbox**

Reject empty keys and non-dict payloads. Do not add worker threads or retry timers.

- [ ] **Step 4: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_machine_event_outbox.py -q
```

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/machine_event_outbox.py dh_pve_app/tests/test_machine_event_outbox.py
git commit -m "feat(dh-pve): add persisted machine event outbox"
```

---

### Task 7: Add UPS previous/current status-change events and suppress duplicate problem events

**Files:**
- Create: `dh_pve_app/app/ups_status_events.py`
- Modify: `dh_pve_app/app/ups_group_runtime.py`
- Modify: `dh_pve_app/app/ups_problems.py`
- Create: `dh_pve_app/tests/test_ups_status_events.py`
- Modify: `dh_pve_app/tests/test_ups_problem_runtime_v2.py`

**Interfaces:**

```python
@dataclass
class UpsStatusEventTracker:
    previous_status: tuple[str, ...] | None = None
    previous_raw_status: tuple[str, ...] | None = None

    def observe(
        self,
        *,
        current_status: tuple[str, ...],
        current_raw_status: tuple[str, ...],
        observed_at: str,
    ) -> tuple[str, dict[str, object]] | None: ...
```

First observation establishes baseline and returns `None`. A change returns `(event_key, payload)` where payload is:

```python
{
    "schema_version": 2,
    "event_type": "ups_status_changed",
    "observed_at": observed_at,
    "previous_status": [...],
    "current_status": [...],
    "previous_raw_status": [...],
    "current_raw_status": [...],
}
```

- [ ] **Step 1: Write RED transition tests**

Cover OL->OB, OB->OL, BOOST enter/exit, unchanged status, first observation and raw-token preservation.

- [ ] **Step 2: Write RED duplicate-notification test**

For OB transition, retained `on_battery` problem binary must update, but diagnostic Event transport must contain `ups_status_changed` only; no parallel `problem_started` for `on_battery`.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_status_events.py dh_pve_app/tests/test_ups_problem_runtime_v2.py -q
```

- [ ] **Step 4: Implement tracker and status-derived problem filtering**

Use `STATUS_DERIVED_UPS_PROBLEM_IDS`. Do not suppress `nut_unavailable` or app-specific diagnostic events. Enqueue the returned status event only after retained UPS state/problem publication succeeds.

- [ ] **Step 5: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_status_events.py dh_pve_app/tests/test_ups_problem_runtime_v2.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_status_events.py dh_pve_app/app/ups_group_runtime.py \
  dh_pve_app/app/ups_problems.py dh_pve_app/tests/test_ups_status_events.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py
git commit -m "feat(dh-pve): emit UPS status transition events"
```

---

### Task 8: Add persistent discharge milestone events

**Files:**
- Create: `dh_pve_app/app/ups_battery_events.py`
- Create: `dh_pve_app/tests/test_ups_battery_events.py`

**Interfaces:**

```python
DISCHARGE_THRESHOLDS = (90, 80, 70, 60, 50, 40, 30, 20, 10)

class UpsBatteryEventTracker:
    def __init__(self, state_store: StateStore) -> None: ...
    def observe_discharge(
        self,
        *,
        on_battery: bool,
        charge_percent: float | None,
        observed_at: str,
    ) -> tuple[tuple[str, dict[str, object]], ...]: ...
```

Persist `session_active`, `session_started_at`, `last_observed_charge_percent`, `emitted_thresholds`. Returned entries are `(event_key, payload)` for the outbox.

- [ ] **Step 1: Write RED crossing tests**

```text
94 -> 87 on battery => [90]
94 -> 67 on battery => one event with [90, 80, 70]
91 -> 90             => [90]
89 -> 87             => no duplicate 90
87 -> 92             => no discharge milestone
94 -> 87 while OL    => no event
```

- [ ] **Step 2: Write RED restart tests**

After persisted 90 milestone, reload tracker and move 87 -> 79; only `[80]` is emitted. Startup already at 67 with no persisted crossing evidence establishes baseline and emits nothing.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ups_battery_events.py -q
```

- [ ] **Step 4: Implement transition/checkpoint persistence**

Payload:

```python
{
    "schema_version": 2,
    "event_type": "battery_discharge_level_crossed",
    "observed_at": observed_at,
    "previous_charge_percent": previous,
    "current_charge_percent": current,
    "crossed_thresholds": crossed,
}
```

Persist emitted thresholds when semantic event creation succeeds; MQTT delivery retry belongs to the outbox.

- [ ] **Step 5: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ups_battery_events.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_battery_events.py dh_pve_app/tests/test_ups_battery_events.py
git commit -m "feat(dh-pve): add UPS discharge milestone events"
```

---

### Task 9: Add fully-charged charge-cycle detection

**Files:**
- Modify: `dh_pve_app/app/ups_battery_events.py`
- Modify: `dh_pve_app/tests/test_ups_battery_events.py`

**Interfaces:**

```python
def observe_charge_cycle(
    self,
    *,
    charger_status: str,
    charge_percent: float | None,
    line_power: bool,
    raw_status_tokens: tuple[str, ...],
    observed_at: str,
) -> tuple[tuple[str, dict[str, object]], ...]: ...
```

Persist cycle state so one observed charging cycle emits at most one `battery_fully_charged` event.

- [ ] **Step 1: Add RED direct-status tests**

```text
charging -> floating => one event
charging -> resting  => one event
charging -> floating -> resting => one event total
startup resting/floating/100% => no event
fully charged may emit at 98%
```

- [ ] **Step 2: Add RED legacy fallback tests**

```text
OL+CHRG -> OL(no CHRG/DISCHRG) sample 1 -> no event
same stable OL sample 2                  -> one event
one-sample CHRG disappearance then CHRG  -> no event
```

Direct `battery.charger.status` wins over conflicting CHRG/DISCHRG evidence.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ups_battery_events.py -q
```

- [ ] **Step 4: Implement cycle latch and two-sample fallback confirmation**

Payload:

```python
{
    "schema_version": 2,
    "event_type": "battery_fully_charged",
    "observed_at": observed_at,
    "previous_charge_percent": previous_charge,
    "current_charge_percent": current_charge,
    "previous_charger_status": "charging",
    "current_charger_status": current_status,
    "detection_source": "charger_status",
}
```

Fallback uses `detection_source="legacy_status_fallback"`.

- [ ] **Step 5: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ups_battery_events.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_battery_events.py dh_pve_app/tests/test_ups_battery_events.py
git commit -m "feat(dh-pve): detect completed UPS charge cycles"
```

---

### Task 10: Integrate outbox/status/battery trackers into UPS runtime

**Files:**
- Modify: `dh_pve_app/app/ups_group_runtime.py`
- Modify: `dh_pve_app/app/main.py`
- Create: `dh_pve_app/tests/test_ups_semantic_runtime.py`
- Modify: `dh_pve_app/tests/test_ups_problem_runtime_v2.py`

**Interfaces:**
- `AdaptiveUpsRuntime.__init__` accepts `machine_event_outbox: MachineEventOutbox` and `battery_event_tracker: UpsBatteryEventTracker`.
- `UpsStatusEventTracker` remains in-memory; pending delivery survives restart in the persisted outbox.
- `build_ups_runtime()` constructs exactly:

```python
machine_event_outbox=MachineEventOutbox(
    StateStore(state_dir / "ups_machine_event_outbox.json")
),
battery_event_tracker=UpsBatteryEventTracker(
    StateStore(state_dir / "ups_battery_events.json")
),
```

- Runtime ordering:

```text
1. flush old outbox; stop if MQTT still fails
2. read NUT
3. publish retained UPS groups
4. publish retained problem state/aggregate
5. update status/battery semantic trackers and enqueue events
6. flush outbox in order
```

- [ ] **Step 1: Write RED end-to-end ordering test**

Drive a status transition and battery threshold crossing. Assert retained state calls precede semantic Event calls.

- [ ] **Step 2: Write RED retry/no-double-count test**

Fail `publish_ups_diagnostic_event` once. Assert outbox keeps the event; next runtime pass retries it before observing another NUT snapshot; no second milestone is created.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_semantic_runtime.py dh_pve_app/tests/test_ups_problem_runtime_v2.py -q
```

- [ ] **Step 4: Implement outbox flush helper**

```python
def _flush_machine_event_outbox(self) -> bool:
    for pending in self.machine_event_outbox.pending():
        if not self.bridge.publish_ups_diagnostic_event(pending.payload):
            return False
        self.machine_event_outbox.acknowledge(pending.key)
    return True
```

Do not add a background worker or new scheduling cadence.

- [ ] **Step 5: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_semantic_runtime.py dh_pve_app/tests/test_ups_problem_runtime_v2.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_group_runtime.py dh_pve_app/app/main.py \
  dh_pve_app/tests/test_ups_semantic_runtime.py dh_pve_app/tests/test_ups_problem_runtime_v2.py
git commit -m "feat(dh-pve): integrate retry-safe UPS semantic events"
```

---

### Task 11: Convert shutdown commitment and policy config-change events to machine v2

**Files:**
- Modify: `dh_pve_app/app/shutdown_integration.py`
- Modify: `dh_pve_app/tests/test_ups_policy_transaction_v2.py`
- Modify: `dh_pve_app/tests/test_ups_trigger.py`
- Modify: `dh_pve_app/tests/test_ups_semantic_runtime.py`

**Interfaces:**
- Internal executor reason strings stay `charge_guard` / `runtime_guard`; fixed helper ACL is unchanged.
- Public event reason map:

```python
_PUBLIC_SHUTDOWN_REASON = {
    "charge_guard": "charge_threshold",
    "runtime_guard": "runtime_threshold",
}
```

- `shutdown_committed` is enqueued only after fixed local helper success and controller commit latch.
- `config_changed` v2 contains OLD/NEW/revision only; no prose.

- [ ] **Step 1: Write RED shutdown-commit tests**

```python
assert event == {
    "schema_version": 2,
    "event_type": "shutdown_committed",
    "observed_at": observed_at,
    "reason": "runtime_threshold",
    "battery_charge_percent": 43.0,
    "battery_runtime_seconds": 390.0,
    "shutdown_budget_seconds": 220,
    "runtime_reserve_seconds": 180,
    "runtime_guard_threshold_seconds": 400,
}
```

Repeated evaluation emits once. Helper failure emits none. NUT FSD alone emits no `shutdown_committed`.

- [ ] **Step 2: Write RED config-change v2 tests**

```python
assert event["schema_version"] == 2
assert event["event_type"] == "config_changed"
assert event["old_values"] == old_values
assert event["new_values"] == new_values
assert event["previous_revision"] == 3
assert event["current_revision"] == 4
assert "summary" not in event
assert "details" not in event
```

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_policy_transaction_v2.py \
  dh_pve_app/tests/test_ups_trigger.py \
  dh_pve_app/tests/test_ups_semantic_runtime.py -q
```

- [ ] **Step 4: Implement v2 events without changing safety behavior**

After successful software shutdown helper return, record history, enqueue `shutdown_committed`, and immediately attempt synchronous outbox flush while the process is still alive. Do not alter Trigger A/B predicates, native LB behavior, helper path or allowed helper commands.

- [ ] **Step 5: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_policy_transaction_v2.py \
  dh_pve_app/tests/test_ups_trigger.py \
  dh_pve_app/tests/test_ups_semantic_runtime.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/shutdown_integration.py \
  dh_pve_app/tests/test_ups_policy_transaction_v2.py \
  dh_pve_app/tests/test_ups_trigger.py dh_pve_app/tests/test_ups_semantic_runtime.py
git commit -m "feat(dh-pve): emit structured shutdown and policy events"
```

---

### Task 12: Expand Event Discovery and update standard UPS charger UI

**Files:**
- Modify: `dh_pve_app/app/discovery_ups_groups.py`
- Modify: `dh_pve_app/app/discovery_groups.py`
- Modify: `dh_pve_app/examples/dh_app_pve_ups_dashboard.yaml`
- Modify: `dh_pve_app/tests/test_canonical_ups_discovery.py`
- Modify: `scripts/validators/apps/dh_pve_app.py`

**Interfaces:**
- UPS Event allowed types are exactly:

```text
problem_started
problem_recovered
problem_updated
config_changed
ups_status_changed
battery_discharge_level_crossed
battery_fully_charged
shutdown_committed
```

- Generic PVE Event remains `problem_started/problem_recovered/problem_updated` but its payload schema is v2.
- Discovery no longer references `status_ru`, `summary`, `details` or old UPS text problem fields.
- Standard dashboard charger UI reads only `sensor.dh_app_pve_ups_battery_charger_status` and localizes in HA.
- Current 0.4.0 branch has no separate Discovery schema-version store in runtime code. Do not introduce a new migration subsystem solely for this change: startup/reconnect already republishes retained canonical Device Discovery to the same topics, replacing `event_types` and templates idempotently.

- [ ] **Step 1: Write RED Discovery/validator assertions**

Require exact UPS Event type list, charger entity and absence of removed localized fields.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_canonical_ups_discovery.py -q
python scripts/validate.py
```

- [ ] **Step 3: Update Discovery and dashboard**

Dashboard text mapping:

```jinja2
{% set s = states('sensor.dh_app_pve_ups_battery_charger_status') %}
{% set labels = {
  'charging': 'Заряжается',
  'floating': 'Поддержание заряда',
  'resting': 'Заряжена',
  'idle': 'Ожидание',
  'discharging': 'Разряжается',
  'unknown': 'Неизвестно',
  'unavailable': 'Недоступно'
} %}
{{ labels.get(s, s) }}
```

Choose icon/icon color in HAOS from the same machine state.

- [ ] **Step 4: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_canonical_ups_discovery.py -q
python scripts/validate.py
```

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/discovery_ups_groups.py dh_pve_app/app/discovery_groups.py \
  dh_pve_app/examples/dh_app_pve_ups_dashboard.yaml \
  dh_pve_app/tests/test_canonical_ups_discovery.py scripts/validators/apps/dh_pve_app.py
git commit -m "feat(dh-pve): publish machine event discovery v2"
```

---

### Task 13: Finish localized v2 HA presentation and enforce no v2 prose dependency

**Files:**
- Modify: `dh_pve_app/examples/packages/dh_app_pve_notification_package.yaml`
- Modify: `dh_pve_app/examples/packages/locales/ru/dh_app_pve_notification_package.yaml`
- Modify: `dh_pve_app/tests/test_ha_notification_machine_events.py`

**Interfaces:**
- v1 fallback remains temporary.
- v2 formatting derives entirely from machine fields.

- [ ] **Step 1: Strengthen tests around schema branches**

Assert v2 branches use `previous/current`, status lists, thresholds and charge/runtime fields. `summary/details` references may exist only in explicit schema-v1 fallback sections.

- [ ] **Step 2: Implement all v2 user-visible mappings**

At minimum cover localized enter/exit messages for `on_battery`, `boost`, `trim`, `bypass`, `overload`, `low_battery`, `replace_battery`, plus discharge milestones, fully charged, shutdown committed and config changed. Generic PVE problem v2 messages use `metric`, `current.value`, `current.average`, `current.threshold` and object/category metadata.

- [ ] **Step 3: Run HA package tests**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ha_notification_machine_events.py -q
```

- [ ] **Step 4: Commit**

```bash
git add dh_pve_app/examples/packages/dh_app_pve_notification_package.yaml \
  dh_pve_app/examples/packages/locales/ru/dh_app_pve_notification_package.yaml \
  dh_pve_app/tests/test_ha_notification_machine_events.py
git commit -m "feat(dh-pve): localize machine event notifications in HA"
```

---

### Task 14: Release docs/version and full verification

**Files:**
- Modify: `dh_pve_app/VERSION`
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`
- Modify: `scripts/validators/apps/dh_pve_app.py`

**Interfaces:**
- Release target is `0.5.0`.
- README documents schema-v2 machine events, charger entity, battery milestones, fully-charged semantics and HA-owned localization.
- CHANGELOG states breaking Event schema v2 and HA-first upgrade order.

- [ ] **Step 1: Set release version and validator contract to 0.5.0**

```text
0.5.0
```

- [ ] **Step 2: Update README/CHANGELOG**

README must state:

```text
App events contain machine semantics only.
HA locale packages own notification wording.
Install/update HA v1+v2-compatible notification package before deploying app 0.5.0.
battery_fully_charged does not require battery.charge == 100.
CHRG/DISCHRG are charger fallback evidence; battery.charger.status has priority.
```

- [ ] **Step 3: Run targeted machine-event suite**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_diagnostic_events.py \
  dh_pve_app/tests/test_problems.py \
  dh_pve_app/tests/test_problem_runtime.py \
  dh_pve_app/tests/test_ups_semantics.py \
  dh_pve_app/tests/test_ups_status_events.py \
  dh_pve_app/tests/test_ups_battery_events.py \
  dh_pve_app/tests/test_machine_event_outbox.py \
  dh_pve_app/tests/test_ups_semantic_runtime.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py \
  dh_pve_app/tests/test_canonical_ups_discovery.py \
  dh_pve_app/tests/test_ups_policy_transaction_v2.py \
  dh_pve_app/tests/test_ha_notification_machine_events.py -q
```

Expected: PASS, zero failures.

- [ ] **Step 4: Run full repository verification**

```bash
python -m compileall -q dh_pve_app/app dh_pve_app/tests
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q
python scripts/validate.py
bash -n dh_pve_app/install.sh
```

Expected: all commands exit 0.

- [ ] **Step 5: Audit event builders for prohibited presentation fields**

```bash
grep -RInE '"(title|message|summary|details|recovery_message|status_ru|emoji)"\s*:' \
  dh_pve_app/app || true
```

Review every hit. Generic non-event presentation may remain only where it is not notification protocol; MQTT Event builders may not contain these keys.

```bash
grep -RInE 'Работа от батареи|состояние нормализовалось|UPS Trigger Policy изменена|No active UPS problems|problem active' \
  dh_pve_app/app || true
```

Expected: no user-facing event/notification prose generation remains; Russian operational journal log/error text is allowed.

- [ ] **Step 6: Final diff review**

Verify:

```text
shutdown predicates/helper ACL unchanged
no faster collector/timer added
Event QoS=1 and retain=false unchanged
retained state precedes transition events
HA v1+v2 compatibility exists before app v2 deployment
status-derived problem notification events are not duplicated
milestone/fully-charged state survives restart
failed semantic Event publish retries from outbox
FSD remains distinct from shutdown_committed
charger UI localization is HA-owned
```

- [ ] **Step 7: Commit release metadata**

```bash
git add dh_pve_app/VERSION dh_pve_app/README.md dh_pve_app/CHANGELOG.md \
  scripts/validators/apps/dh_pve_app.py
git commit -m "docs(dh-pve): release 0.5.0 machine events"
```

---

## Deployment / Production Verification Gate

Do not deploy before full CI is green and final diff review is complete.

Production order:

```text
1. Deploy HAOS notification package that accepts schema v1 + v2.
2. Restart/reload HA Core and verify no package/template errors.
3. Deploy exact reviewed dh_pve_app 0.5.0 SHA to home PVE 192.168.11.30.
4. Verify new charger-status entity and expanded UPS Event metadata.
5. Verify ordinary OL/current charger retained machine payloads.
6. Verify config_changed v2 only through a safe policy Apply when a real config change is intended.
7. Do not unplug mains, force FSD, deep-discharge the UPS or trigger real shutdown merely for notification testing.
```

Use fixtures/synthetic runtime tests for transitions that cannot be observed naturally without destructive action.

## Plan Self-Review Checklist

- Spec sections 3-5: Tasks 2-3.
- Spec sections 6-8: Tasks 4-5, 7, 12.
- Spec section 9: Tasks 8, 10.
- Spec section 10: Tasks 9-10.
- Spec sections 11-12: Task 11.
- Spec sections 13-15: Tasks 1, 12-13.
- Spec section 17: covered by Tasks 1-14 tests.
- Spec section 18: Tasks 6, 10-11.
- No production task authorizes destructive UPS validation.
