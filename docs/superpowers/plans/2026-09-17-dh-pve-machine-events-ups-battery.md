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

- `dh_pve_app/app/problems.py` — machine-only problem state; no generated prose.
- `dh_pve_app/app/diagnostic_events.py` — schema-v2 generic problem event serialization.
- `dh_pve_app/app/runtime_problems.py` — pass event timestamp and publish structured aggregates.
- `dh_pve_app/app/ups_health.py` — UPS problem observations become IDs/severity/facts only.
- `dh_pve_app/app/ups_problems.py` — machine-only retained UPS problem state; identify status-derived problem IDs whose notification transport is `ups_status_changed`.
- `dh_pve_app/app/ups_nut.py` — parse raw `battery.charger.status`, normalized status/charger fields and canonical compatibility booleans.
- `dh_pve_app/app/ups_runtime.py` — remove `_human_status()`/text problem fields and publish canonical machine state.
- `dh_pve_app/app/presentation_ups.py` — route canonical UPS status/charger machine fields; remove text problem payload fields.
- `dh_pve_app/app/ups_group_runtime.py` — integrate status/battery semantic trackers and retry-safe event outbox after retained-state publication.
- `dh_pve_app/app/shutdown_integration.py` — schema-v2 `config_changed` and `shutdown_committed` event creation.
- `dh_pve_app/app/discovery_ups.py` / `dh_pve_app/app/discovery_ups_groups.py` — canonical status/charger entities and expanded Event types.
- `dh_pve_app/app/discovery_groups.py` — schema-v2 generic diagnostic Event metadata where required.
- `dh_pve_app/app/main.py` — construct/persist semantic event state under `/var/lib/dh_pve_app` if runtime injection is needed.
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

### New/expanded tests

- `dh_pve_app/tests/test_machine_event_outbox.py`
- `dh_pve_app/tests/test_ups_semantics.py`
- `dh_pve_app/tests/test_ups_status_events.py`
- `dh_pve_app/tests/test_ups_battery_events.py`
- modify existing `test_diagnostic_events.py`, `test_problems.py`, `test_problem_runtime.py`, `test_ups_problems.py`, `test_ups_problem_runtime_v2.py`, `test_ups_runtime.py`, `test_canonical_ups_discovery.py`, `test_ups_policy_transaction_v2.py`, `test_ups_trigger.py` and validator tests as required.
- add `dh_pve_app/tests/test_ha_notification_machine_events.py` for static HA package migration guarantees.

---

### Task 1: Deploy HA-first v1/v2 notification compatibility in repository examples

**Files:**
- Modify: `dh_pve_app/examples/packages/dh_app_pve_notification_package.yaml`
- Modify: `dh_pve_app/examples/packages/locales/ru/dh_app_pve_notification_package.yaml`
- Create: `dh_pve_app/tests/test_ha_notification_machine_events.py`

**Interfaces:**
- Consumes: current HA MQTT Event attributes from schema v1 and future schema v2 fields from the approved spec.
- Produces: one localized `dh_app_pve_notification` event per incoming user-visible machine event, with no dependency on Python-generated prose for v2.
- Migration invariant: schema v1 and v2 are accepted by the HA package; app never dual-publishes v1+v2.

- [ ] **Step 1: Write failing static contract tests for both locale packages**

Add tests that read both YAML files as text and require the new v2 event types plus schema-aware handling:

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


def test_notification_packages_do_not_require_v2_summary_details():
    for path in PACKAGES:
        text = path.read_text(encoding="utf-8")
        assert "current_status" in text
        assert "crossed_thresholds" in text
        assert "current_charge_percent" in text
```

- [ ] **Step 2: Run RED**

Run:

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ha_notification_machine_events.py -q
```

Expected: FAIL because the current packages only understand v1 problem/config events.

- [ ] **Step 3: Extend HA event triggers and schema-aware templates**

For `event.dh_app_pve_ups_diagnostic`, include:

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

At the top of each action template derive:

```jinja2
{% set schema = trigger.to_state.attributes.schema_version | int(1) %}
{% set kind = trigger.to_state.attributes.event_type %}
```

Keep the existing schema-v1 `summary/details/value/average/threshold` path only under `schema == 1`. For schema v2, use `previous`, `current`, previous/current status lists and structured numeric fields directly.

Russian exact semantic examples to encode in HA, not Python:

```text
on_battery entered       -> 🔋⚠️ UPS: городское питание отсутствует
on_battery -> online     -> 🔋✅ UPS: городское питание восстановлено
battery milestone        -> 🔋⚠️ UPS: заряд батареи <current>%
fully charged            -> 🔋✅ UPS: батарея заряжена
shutdown_committed       -> 🔋🛑 UPS: начато аварийное выключение
config_changed           -> 🔋⚙️ Конфигурация UPS Trigger изменена
```

English package gets equivalent English wording. Preserve the HA-only boot-completed gate and the reusable downstream `dh_app_pve_notification` event.

- [ ] **Step 4: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ha_notification_machine_events.py -q
```

Expected: PASS.

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
- Modify: `dh_pve_app/tests/test_problems.py`
- Modify: `dh_pve_app/tests/test_diagnostic_events.py`
- Modify: `dh_pve_app/tests/test_problem_runtime.py`

**Interfaces:**
- `ProblemState` keeps: `problem_id, category, severity, object_id, object_name, metric, active, value, average, threshold`.
- `ProblemState` no longer stores `summary` or `details`.
- `DiagnosticEvent.from_transition(transition, *, active_problem_count: int, observed_at: str) -> DiagnosticEvent`.
- `DiagnosticEvent.as_payload()` emits schema version 2, `problem_id`, machine metadata, `previous`, `current`, and `active_problem_count`.

- [ ] **Step 1: Rewrite tests first for the exact v2 payload**

Representative assertion:

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

Also test timezone-naive `observed_at` is rejected and first inactive observation emits no transition.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_problems.py \
  dh_pve_app/tests/test_diagnostic_events.py \
  dh_pve_app/tests/test_problem_runtime.py -q
```

Expected: FAIL on v1 fields/schema.

- [ ] **Step 3: Remove generated prose from `ProblemState` and event serialization**

Use a single helper in `diagnostic_events.py`:

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

Validate `observed_at` with `datetime.fromisoformat()` and require timezone awareness. Set `SCHEMA_VERSION = 2`.

- [ ] **Step 4: Update runtime callers to pass `self.now_iso()`**

In both normal and UPS problem event creation, the call shape must become:

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
  dh_pve_app/tests/test_problem_runtime.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/problems.py dh_pve_app/app/diagnostic_events.py \
  dh_pve_app/app/runtime_problems.py dh_pve_app/tests/test_problems.py \
  dh_pve_app/tests/test_diagnostic_events.py dh_pve_app/tests/test_problem_runtime.py
git commit -m "refactor(dh-pve): make problem events machine-only v2"
```

---

### Task 3: Remove prose from retained problem aggregates and UPS problem observations

**Files:**
- Modify: `dh_pve_app/app/ups_health.py`
- Modify: `dh_pve_app/app/ups_problems.py`
- Modify: `dh_pve_app/app/ups_runtime.py`
- Modify: `dh_pve_app/app/presentation_ups.py`
- Modify: `dh_pve_app/app/runtime_problems.py`
- Modify: `dh_pve_app/tests/test_ups_problems.py`
- Modify: `dh_pve_app/tests/test_ups_problem_runtime_v2.py`
- Modify: `dh_pve_app/tests/test_ups_runtime.py`

**Interfaces:**
- `UpsProblemObservation(problem_id, active, severity)` plus factual fields only if required; no message/label.
- Problem aggregate shape: `count`, `severity`, `active: list[dict]` where each item is structured machine data.
- Define `STATUS_DERIVED_UPS_PROBLEM_IDS = frozenset({"on_battery", "low_battery", "overload", "replace_battery", "bypass"})` for later notification de-duplication.

- [ ] **Step 1: Write RED assertions that retained payloads contain no prose fields**

Require active entries such as:

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

And assert `summary`, `details`, localized message strings and `problems_details` are absent from grouped retained state.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_problems.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py \
  dh_pve_app/tests/test_ups_runtime.py -q
```

- [ ] **Step 3: Simplify observations/aggregates**

Remove `message` and `label` from `UpsProblemObservation`; construct `ProblemState` directly from IDs/severity/active values. Remove aggregate `summary` generation from both generic and UPS engines. Replace old UPS `_problem_fields()` text output with structured/count/severity machine fields only.

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
  dh_pve_app/app/runtime_problems.py dh_pve_app/tests/test_ups_problems.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py dh_pve_app/tests/test_ups_runtime.py
git commit -m "refactor(dh-pve): make retained problem state structured"
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

def normalize_ups_status(status_tokens: tuple[str, ...]) -> tuple[str, ...]: ...

def primary_ups_status(status_set: tuple[str, ...]) -> str: ...

def resolve_charger_status(
    *,
    direct_status: str | None,
    status_tokens: tuple[str, ...],
    line_power: bool,
) -> str: ...
```

`UpsSnapshot` adds:

```python
normalized_status: tuple[str, ...]
primary_status: str
battery_charger_status_raw: str | None
battery_charger_status: str
```

Compatibility fields `charging` and `discharging` are derived from canonical charger status.

- [ ] **Step 1: Write normalization RED tests**

Tests must cover:

```python
assert normalize_ups_status(("OL", "BOOST", "CHRG")) == ("online", "boost")
assert normalize_ups_status(("OB", "DISCHRG", "LB")) == ("on_battery", "low_battery")
assert normalize_ups_status(("OL", "FUTURE_TOKEN")) == ("online",)

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
  dh_pve_app/tests/test_ups_semantics.py \
  dh_pve_app/tests/test_ups_nut.py -q
```

- [ ] **Step 3: Implement the pure resolver and parser fields**

Canonical NUT token mapping:

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

Do not map `CHRG`/`DISCHRG` into `normalized_status`; they are charger fallback evidence only.

- [ ] **Step 4: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_semantics.py \
  dh_pve_app/tests/test_ups_nut.py -q
```

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/ups_semantics.py dh_pve_app/app/ups_nut.py \
  dh_pve_app/tests/test_ups_semantics.py dh_pve_app/tests/test_ups_nut.py
git commit -m "feat(dh-pve): normalize UPS and charger machine state"
```

---

### Task 5: Publish canonical UPS status and charger status through MQTT Discovery/UI state

**Files:**
- Modify: `dh_pve_app/app/ups_runtime.py`
- Modify: `dh_pve_app/app/presentation_ups.py`
- Modify: `dh_pve_app/app/discovery_ups.py`
- Modify: `dh_pve_app/app/discovery_ups_groups.py`
- Modify: `dh_pve_app/tests/test_canonical_ups_discovery.py`
- Modify: `dh_pve_app/tests/test_ups_runtime.py`

**Interfaces:**
- `sensor.dh_app_pve_ups_status` state is `primary_status` machine enum.
- Attributes/state group include `status_set` and `raw_status_tokens`.
- New `sensor.dh_app_pve_ups_battery_charger_status` state is one of `charging|discharging|floating|resting|idle|unknown`.
- Existing charging/discharging binaries remain compatible but derive from canonical charger status; unknown must not be published as false certainty.

- [ ] **Step 1: Write RED Discovery/runtime tests**

Require:

```python
assert components["battery_charger_status"]["default_entity_id"] == (
    "sensor.dh_app_pve_ups_battery_charger_status"
)
assert "battery_charger_status" in components["battery_charger_status"]["value_template"]
```

And runtime payload:

```python
assert payload["status"] == "online"
assert payload["status_set"] == ["online", "boost"]
assert payload["raw_status_tokens"] == ["OL", "BOOST", "CHRG"]
assert payload["battery_charger_status"] == "charging"
assert "status_ru" not in payload
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_canonical_ups_discovery.py \
  dh_pve_app/tests/test_ups_runtime.py -q
```

- [ ] **Step 3: Replace `_human_status()` with machine fields and add charger Discovery**

Delete `_human_status()` from `ups_runtime.py`. Use parsed `snapshot.primary_status`, `snapshot.normalized_status`, raw tokens and charger status. Ensure Discovery templates never reference `status_ru`.

- [ ] **Step 4: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_canonical_ups_discovery.py \
  dh_pve_app/tests/test_ups_runtime.py -q
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

- `enqueue()` is idempotent by key and persists before returning.
- `acknowledge()` removes only after MQTT publish succeeds.
- Persisted shape is versioned, e.g. `{"schema_version": 1, "pending": [...]}`.

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

- [ ] **Step 3: Implement minimal versioned persisted outbox**

Reject empty keys and non-dict payloads; do not add retry timers or background threads.

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

### Task 7: Add UPS previous/current status-change events and suppress duplicate status problem events

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
    ) -> dict[str, object] | None: ...
```

First observation establishes baseline and returns `None`. A changed canonical set returns:

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

Status-derived retained binary problems still update, but their `problem_started/problem_recovered` diagnostic Event is suppressed; `ups_status_changed` is the notification transport for those facts.

- [ ] **Step 1: Write RED transition tests**

Cover OL->OB, OB->OL, BOOST enter/exit, unchanged status, first observation and raw-token preservation.

- [ ] **Step 2: Write RED duplicate-notification test**

For an OB transition, assert the runtime publishes the retained `on_battery` problem state but emits exactly one semantic notification event and it is `ups_status_changed`, not a second `problem_started` for `on_battery`.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_status_events.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py -q
```

- [ ] **Step 4: Implement tracker and runtime filtering**

Use `STATUS_DERIVED_UPS_PROBLEM_IDS` from `ups_problems.py`. Do not suppress generic events for `nut_unavailable` or app-specific diagnostic failures.

Queue `ups_status_changed` into the persisted outbox only after retained UPS state/problem publication succeeds.

- [ ] **Step 5: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_status_events.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py -q
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

Persist at least `session_active`, `session_started_at`, `last_observed_charge_percent`, `emitted_thresholds`. Returned tuple entries are `(event_key, payload)` suitable for `MachineEventOutbox.enqueue()`.

- [ ] **Step 1: Write RED crossing tests**

Exact required cases:

```python
94 -> 87 on battery => crossed_thresholds [90]
94 -> 67 on battery => one event, crossed_thresholds [90, 80, 70]
91 -> 90             => [90]
89 -> 87             => no duplicate 90
87 -> 92 charging/up => no event
94 -> 87 while OL    => no event
```

- [ ] **Step 2: Write RED restart tests**

Persist a session after 90 was emitted, reconstruct the tracker from the same `StateStore`, then move from 87 -> 79 and assert only `[80]` is emitted. Startup already at 67 with no persisted crossing evidence establishes baseline and emits nothing.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ups_battery_events.py -q
```

- [ ] **Step 4: Implement transition/checkpoint persistence**

Generate payload:

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

Persist emitted thresholds when the semantic event is created; delivery retry is handled by the outbox, not by recreating the milestone.

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

### Task 9: Add fully-charged cycle detection to the battery tracker

**Files:**
- Modify: `dh_pve_app/app/ups_battery_events.py`
- Modify: `dh_pve_app/tests/test_ups_battery_events.py`

**Interfaces:**

Extend tracker with:

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

Persist cycle state so one charge cycle produces at most one `battery_fully_charged` event.

- [ ] **Step 1: Add RED direct charger-status tests**

Required:

```text
charging -> floating => one event
charging -> resting  => one event
charging -> floating -> resting => one event total
startup resting/floating/100% => no event
fully charged may emit at 98%
```

- [ ] **Step 2: Add RED legacy fallback tests**

With no direct `battery.charger.status`:

```text
OL+CHRG -> OL(no CHRG/DISCHRG) sample 1 -> no event
same stable OL sample 2                  -> one event
one-sample CHRG disappearance then CHRG  -> no event
```

Direct charger status must win over conflicting legacy token evidence.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ups_battery_events.py -q
```

- [ ] **Step 4: Implement cycle latch and fallback confirmation**

Use at least two consecutive 10-second fallback idle samples. Payload:

```python
{
    "schema_version": 2,
    "event_type": "battery_fully_charged",
    "observed_at": observed_at,
    "previous_charge_percent": previous_charge,
    "current_charge_percent": current_charge,
    "previous_charger_status": "charging",
    "current_charger_status": current_status,
    "detection_source": "charger_status",  # or legacy_status_fallback
}
```

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

### Task 10: Integrate semantic-event outbox, battery tracker and retry ordering into UPS runtime

**Files:**
- Modify: `dh_pve_app/app/ups_group_runtime.py`
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/tests/test_ups_problem_runtime_v2.py`
- Modify/Create: `dh_pve_app/tests/test_ups_semantic_runtime.py`

**Interfaces:**
- Dedicated state files under the UPS state directory:
  - `ups_machine_event_outbox.json`
  - `ups_battery_events.json`
- Runtime flush order:

```text
1. flush previously pending machine events; stop observation if transport still fails
2. read fresh NUT snapshot
3. publish retained UPS state groups
4. publish retained problem state/aggregate
5. update status/battery semantic trackers and enqueue new events
6. flush machine-event outbox in queue order
```

- [ ] **Step 1: Write RED end-to-end runtime tests**

Test one OB transition with charge 87 from previous 94 and assert retained state precedes event publication. Then simulate `publish_ups_diagnostic_event` failing once; verify the event remains pending and is retried before a later snapshot is observed.

- [ ] **Step 2: Write RED no-double-count tests**

After a failed milestone Event publish, rerun runtime processing and assert no second semantic milestone is created; only the pending outbox event is retried.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_semantic_runtime.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py -q
```

- [ ] **Step 4: Integrate stores/trackers and flush helper**

Add runtime helper:

```python
def _flush_machine_event_outbox(self) -> bool:
    for pending in self.machine_event_outbox.pending():
        if not self.bridge.publish_ups_diagnostic_event(pending.payload):
            return False
        self.machine_event_outbox.acknowledge(pending.key)
    return True
```

Do not add a separate thread or timer.

- [ ] **Step 5: Run GREEN**

```bash
PYTHONPATH=dh_pve_app python -m pytest \
  dh_pve_app/tests/test_ups_semantic_runtime.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_group_runtime.py dh_pve_app/app/main.py \
  dh_pve_app/tests/test_ups_semantic_runtime.py \
  dh_pve_app/tests/test_ups_problem_runtime_v2.py
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
- Internal safety controller/executor reason strings may remain `charge_guard` / `runtime_guard` to avoid changing the fixed helper ACL.
- Public event reason mapping is stable:

```python
_PUBLIC_SHUTDOWN_REASON = {
    "charge_guard": "charge_threshold",
    "runtime_guard": "runtime_threshold",
}
```

- `shutdown_committed` is enqueued only after the fixed local shutdown helper returns successfully and the controller's commit latch is true.
- `config_changed` v2 carries only machine OLD/NEW/revision data.

- [ ] **Step 1: Write RED `shutdown_committed` tests**

Assert exact fields:

```python
{
    "schema_version": 2,
    "event_type": "shutdown_committed",
    "observed_at": "...+05:00",
    "reason": "runtime_threshold",
    "battery_charge_percent": 43.0,
    "battery_runtime_seconds": 390.0,
    "shutdown_budget_seconds": 220,
    "runtime_reserve_seconds": 180,
    "runtime_guard_threshold_seconds": 400,
}
```

Assert exactly one event after repeated evaluations; helper failure produces no committed event; NUT FSD alone produces no `shutdown_committed`.

- [ ] **Step 2: Write RED `config_changed` v2 tests**

Require:

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

- [ ] **Step 4: Implement v2 event creation without altering shutdown authority**

Do not change Trigger A/B safety predicates, native LB behavior, helper path or allowed helper commands. Only add structured event data after successful commitment and convert successful config-change event payloads.

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

### Task 12: Expand MQTT Event Discovery, migrate removed localized fields and update standard UPS UI

**Files:**
- Modify: `dh_pve_app/app/discovery_ups_groups.py`
- Modify: `dh_pve_app/app/discovery_groups.py`
- Modify: Discovery schema/version state file in the existing Discovery migration implementation if current code requires a bump.
- Modify: `dh_pve_app/examples/dh_app_pve_ups_dashboard.yaml`
- Modify: `dh_pve_app/tests/test_canonical_ups_discovery.py`
- Modify: `scripts/validators/apps/dh_pve_app.py`

**Interfaces:**
- UPS Event entity allowed types:

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

- Discovery no longer references `status_ru`, `summary`, `details` or old UPS text problem fields.
- Standard dashboard charger status reads only `sensor.dh_app_pve_ups_battery_charger_status` and localizes in HA Jinja/UI.

- [ ] **Step 1: Write RED Discovery/validator assertions**

Require exact event type list and charger entity. Add validator checks that Python Event serializers do not publish prohibited presentation keys.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_canonical_ups_discovery.py -q
python scripts/validate.py
```

Expected: at least the new contract checks fail before implementation.

- [ ] **Step 3: Update Discovery and dashboard**

Dashboard mapping example:

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

Choose icon/icon color in HAOS from the same machine state; do not add localized status to Python payload.

If Event Discovery metadata requires schema migration, increment the existing Discovery schema once and preserve the existing idempotent manifest/tombstone pattern; do not invent a parallel migration mechanism.

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

### Task 13: Complete HA localized v2 presentation and remove v2 dependency on app prose

**Files:**
- Modify: `dh_pve_app/examples/packages/dh_app_pve_notification_package.yaml`
- Modify: `dh_pve_app/examples/packages/locales/ru/dh_app_pve_notification_package.yaml`
- Modify: `dh_pve_app/tests/test_ha_notification_machine_events.py`

**Interfaces:**
- v1 fallback remains temporary.
- v2 path must derive all user wording from machine fields.
- HA may use source-native `object_name`, IDs and numerical values but never expect `summary/details` in v2.

- [ ] **Step 1: Strengthen tests to reject v2 prose-field reads**

Add static assertions that v2 branches do not access `trigger.to_state.attributes.summary` or `.details`; any such reference must be confined to explicit schema-v1 fallback blocks.

- [ ] **Step 2: Add exact v2 mappings for user-visible UPS events**

Russian rules at minimum:

```text
current contains on_battery, previous did not -> городское питание отсутствует
previous contains on_battery, current contains online -> городское питание восстановлено
boost entered/exited -> локализованное BOOST сообщение
trim entered/exited -> локализованное TRIM сообщение
bypass entered/exited -> локализованное bypass сообщение
overload entered/exited -> локализованное overload сообщение
low_battery entered/exited -> локализованное low-battery сообщение
replace_battery entered -> локализованное replace-battery сообщение
battery_discharge_level_crossed -> current charge + crossed levels
battery_fully_charged -> current charge when available
shutdown_committed -> reason + runtime/charge/budget/reserve
config_changed -> OLD -> NEW values/revisions
```

Generic PVE problem v2 messages use `metric/current.value/current.average/current.threshold` and category/object metadata.

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
- Modify: validator/repository contract tests that pin the app version.

**Interfaces:**
- Release target: `0.5.0`.
- README documents machine-event v2, charger status entity, battery milestone semantics, fully-charged semantics and HA-owned localization.
- CHANGELOG explicitly notes breaking Event schema v2 and HA-first upgrade order.

- [ ] **Step 1: Update docs/version tests first where version is pinned**

Expected version:

```text
0.5.0
```

- [ ] **Step 2: Update README/CHANGELOG/VERSION**

README must include these exact operational points:

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

- [ ] **Step 5: Audit public event payloads for prohibited prose keys**

Run:

```bash
grep -RInE '"(title|message|summary|details|recovery_message|status_ru|emoji)"\s*:' \
  dh_pve_app/app || true
```

Review every hit. Allowed hits are internal/non-event state only if explicitly justified; no MQTT Event payload builder may contain these user-presentation keys.

Also search localized prose in UPS event production:

```bash
grep -RInE 'Работа от батареи|состояние нормализовалось|UPS Trigger Policy изменена|No active UPS problems|problem active' \
  dh_pve_app/app || true
```

Expected: no user-facing event/presentation generation remains in app code; Russian operational journal errors/logs are allowed.

- [ ] **Step 6: Final diff review**

Verify specifically:

```text
- no shutdown predicate/helper ACL changed accidentally
- no new collection cadence or timer introduced
- Event QoS remains 1 / retain=false
- retained state publishes before transition events
- v1 HA compatibility exists before app v2 deployment
- no duplicate status-derived problem notification events
- milestone/fully-charged state survives restart
- failed Event publish is retried from outbox
- FSD remains distinct from shutdown_committed
- standard dashboard charger status is HA-localized
```

- [ ] **Step 7: Commit release metadata**

```bash
git add dh_pve_app/VERSION dh_pve_app/README.md dh_pve_app/CHANGELOG.md \
  scripts/validators/apps/dh_pve_app.py
git commit -m "docs(dh-pve): release 0.5.0 machine events"
```

---

## Deployment / Production Verification Gate

Do not deploy before full CI is green and the final diff is reviewed.

Production order must be:

```text
1. Deploy HAOS notification package that accepts schema v1 + v2.
2. Reload/restart HA Core and verify package loads with no template errors.
3. Deploy exact reviewed dh_pve_app 0.5.0 SHA to home PVE 192.168.11.30.
4. Verify Discovery contains new charger-status sensor and expanded UPS Event types.
5. Use non-destructive state/event evidence only.
6. Verify ordinary OL/current charger state and retained machine payloads.
7. Verify config_changed v2 through a safe policy Apply only if a real configuration change is intended.
8. Do not unplug mains, force FSD, deep-discharge the UPS or trigger real shutdown merely to test notifications.
```

For battery/status transition behavior that cannot be observed naturally, use unit/integration fixtures and synthetic runtime tests rather than destructive production actions.

## Plan Self-Review Checklist

- Spec sections 3-5 (machine-only problem events/aggregates): Tasks 2-3.
- Spec sections 6-8 (UPS status + charger semantics/UI): Tasks 4-5, 7, 12.
- Spec section 9 (discharge milestones): Tasks 8, 10.
- Spec section 10 (fully charged): Tasks 9-10.
- Spec sections 11-12 (shutdown/config events): Task 11.
- Spec sections 13-15 (HA ownership, Event surface, migration): Tasks 1, 12-13.
- Spec section 17 test contract: distributed across Tasks 1-14.
- Spec section 18 retry semantics: Tasks 6, 10-11.
- No production task authorizes destructive UPS validation.
