# DH PVE UPS Trigger Policy v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed ONBATT/upssched timer with a safe two-path shutdown trigger (`native OB+LB` OR confirmed runtime guard), add transactional UPS trigger configuration from Home Assistant, and preserve NUT/Proxmox as the shutdown authority.

**Architecture:** The long-running App remains read-only for `/etc/nut` and evaluates only the runtime guard on PVE. A dedicated typed policy model computes the total shutdown budget and effective runtime trigger. Low Battery configuration is capability-driven and hard-allowlisted. Confirmed configuration is handed to a dedicated root oneshot that performs transactional NUT/UPS mutation, verification, rollback, and an App restart. HA edits a draft only; explicit confirmation is required before mutation.

**Tech Stack:** Python 3.13 in CI, pytest, NUT 2.8.x (`upsmon`, `upsc`, `upsrw`, `upscmd`), Debian 12 / Proxmox VE 8, systemd 252, MQTT Discovery, Home Assistant package/dashboard YAML.

**Spec:** `docs/superpowers/specs/2026-09-15-dh-pve-ups-trigger-policy-v2-design.md`

**Dependency:** Complete, deploy, and non-destructively validate `docs/superpowers/plans/2026-09-15-dh-pve-runtime-observability.md` first. This plan relies on its `UPS_TRIGGER` logging vocabulary and expanded shutdown incident timeline.

## Global Constraints

- Production FSD rule is exactly: native NUT critical `OB + LB` **OR** confirmed runtime guard.
- Native LB remains standard NUT behavior. The App must not issue a duplicate FSD after NUT has already committed FSD.
- Runtime guard requires **2 consecutive valid UPS polls** below/equal threshold.
- Runtime telemetry is stale after **more than 15 seconds** without a successful valid `battery.runtime` sample.
- Runtime-based FSD is never triggered while OL, from missing/stale runtime, or from one low sample.
- Once App runtime guard commits FSD, the decision is latched for the current boot.
- Policy v2 has only two trigger settings: `battery_charge_low_percent` and `runtime_safety_reserve_seconds`.
- Low Battery range is exactly **10–30% step 5**.
- Runtime reserve range is exactly **60–900 s step 60**, default **180 s** for a new v2 policy.
- Old `on_battery_delay_minutes=30` is never migrated into runtime reserve.
- `host_shutdown_reserve_seconds` is exactly **120 s** in v2.
- Total budget is exactly `guest + HOSTSYNC + FINALDELAY + 120`; do not add UPS offdelay.
- `power_restore_delay_seconds` remains separate. Current installation behavior stays **120 s** and is not part of `Config UPS trigger`.
- DigitalHouses v1 ONBATT/ONLINE `upssched` timer is retired; unrelated administrator NUT/upssched content must be preserved.
- Long-running `dh_pve_app.service` remains `ProtectSystem=full`; do not give it generic `/etc/nut` write access.
- HA/MQTT never gains arbitrary `SET VAR`, `INSTCMD`, `FSD`, `shutdown.*`, `load.*`, or shell execution.
- A slider changes draft state only. No host/NUT/UPS mutation occurs until explicit Apply -> Confirm.
- A changed successful Apply restarts `dh_pve_app.service`; a true no-op Apply does not restart, increment revision, or emit a config-change event.
- Failed validation/mutation/read-back/restart never advances active revision or emits config-changed.
- Config-changed notification contains only committed old -> new fields and is emitted only after post-restart verification.
- Derived PVE budget changes are a separate `UPS_SHUTDOWN_BUDGET_CHANGED` event and never increment explicit UPS `policy_revision`.
- No destructive FSD/load-off/deep-discharge test is part of implementation or normal release validation.
- NFS/CIFS/SMB storage-provider dependency detection remains technical debt.

---

## File Structure

### New files

- `dh_pve_app/app/ups_trigger.py` — pure runtime-guard state machine and decision result.
- `dh_pve_app/app/ups_variables.py` — approved NUT variable discovery/read/write/read-back for `battery.charge.low` only.
- `dh_pve_app/app/ups_policy_request.py` — typed apply request/result/metadata serialization and atomic state-file contract.
- `dh_pve_app/bin/dh-pve-ups-policy-apply` — fixed entrypoint for the privileged oneshot; no user-supplied command text.
- `dh_pve_app/systemd/dh-pve-ups-policy-apply.service` — short-lived root apply worker.
- `dh_pve_app/tests/test_ups_trigger.py` — runtime guard and FSD-latch tests.
- `dh_pve_app/tests/test_ups_variables.py` — `upsrw`/SET/read-back allowlist tests.
- `dh_pve_app/tests/test_ups_policy_request.py` — typed request/result/revision-state tests.
- `dh_pve_app/tests/test_ups_policy_apply_service.py` — oneshot boundary/restart/ack/rollback tests.

### Existing files modified

- `dh_pve_app/app/ups_policy.py` — v2 domain model, exact ranges, total/effective budget helpers, canonical hash.
- `dh_pve_app/app/ups_policy_host.py` — safety facts use 120-second host reserve and expose total budget inputs.
- `dh_pve_app/app/ups_policy_apply.py` — remove managed v1 timer, preserve unrelated NUT content, add SET ACL when required, transactional v2 apply/read-back/rollback.
- `dh_pve_app/app/ups_policy_preflight.py` — v2 readiness/migration preflight.
- `dh_pve_app/app/ups_shutdown_policy.py` — report v2/legacy/effective policy without requiring upssched.
- `dh_pve_app/app/shutdown_integration.py` — readiness no longer requires upssched; feed v2 policy snapshot/reason into shutdown history.
- `dh_pve_app/app/ups_runtime.py` — v2 active/draft/UI state, runtime trigger evaluation, durable apply result consumption, budget-change detection.
- `dh_pve_app/app/ups_nut.py` — only if needed to retain runtime-sample freshness metadata without changing telemetry semantics.
- `dh_pve_app/app/ups_control.py` — keep instant-command allowlist separate; do not mix generic variable SET into existing public command capability.
- `dh_pve_app/app/mqtt_bridge.py` — typed draft/edit/review/confirm/cancel events; no FSD/SET passthrough.
- `dh_pve_app/app/topics.py` — v2 policy topics; retire fixed-delay topics.
- `dh_pve_app/app/discovery_ups.py` and `discovery_ups_groups.py` — v2 sensors/draft controls/buttons/readiness and v1 tombstones.
- `dh_pve_app/app/main.py` — build runtime FSD executor and fixed apply-service requester; update commissioning CLI contract.
- `dh_pve_app/app/shutdown_history.py` — accept v2 FSD reason and policy snapshot fields from the Observability design.
- `dh_pve_app/systemd/dh_pve_app.service` — allow only App-owned state writes; no `/etc/nut` relaxation.
- `dh_pve_app/install.sh` — install worker entrypoint/unit and reload systemd.
- `dh_pve_app/examples/dh_pve_ups_dashboard.yaml` — VIEW/EDIT/CONFIRM/APPLYING UX.
- `dh_pve_app/examples/packages/dh_app_pve_package.yaml` — post-restart config-change and budget-change notifications.
- `dh_pve_app/README.md`, `dh_pve_app/CHANGELOG.md` — v2 architecture/migration/operations.
- Existing UPS policy/runtime/discovery/MQTT/apply/preflight tests — migrate from the v1 contract rather than layering conflicting tests.

### Persistent state contract

Use these fixed paths under the existing App state directory:

```text
/var/lib/dh_pve_app/ups_runtime.json
/var/lib/dh_pve_app/ups_policy_active.json
/var/lib/dh_pve_app/ups_policy_request.json
/var/lib/dh_pve_app/ups_policy_result.json
/var/lib/dh_pve_app/ups_policy_startup_ack.json
```

All are typed JSON written atomically with root ownership and mode `0600` where they contain transaction metadata. They contain no passwords.

`ups_policy_active.json` is the privileged transaction metadata source. It contains at least:

```json
{
  "schema": 2,
  "phase": "active",
  "request_id": "...",
  "revision": 8,
  "policy": {
    "battery_charge_low_percent": 20,
    "runtime_safety_reserve_seconds": 300
  },
  "derived": {
    "guest_shutdown_budget_seconds": 280,
    "total_shutdown_budget_seconds": 420,
    "effective_runtime_trigger_seconds": 720
  },
  "applied_at": "2026-09-15T09:52:14+05:00",
  "last_change": {}
}
```

The exact state transition is:

```text
request -> worker validation -> mutation -> verified_restart_pending
       -> App restart/read-back -> startup_ack
       -> worker commits phase=active -> App consumes result/publishes
```

If restart/read-back acknowledgment fails, the worker rolls back and restarts the App on the previous state. A candidate revision is not presented as active until the worker receives a matching startup acknowledgment.

---

### Task 1: Replace the policy domain model with v2

**Files:**
- Modify: `dh_pve_app/app/ups_policy.py`
- Modify: `dh_pve_app/tests/test_ups_policy.py`
- Replace/rewrite: `dh_pve_app/tests/test_ups_policy_v2_contract.py`

**Interfaces:**
- Produces: `UpsPolicyDraft(battery_charge_low_percent, runtime_safety_reserve_seconds)`.
- Produces: `calculate_total_shutdown_budget(facts)` and `validate_policy(draft, facts)` returning all derived values.
- Consumes later: runtime guard, apply worker, Discovery/UI.

- [ ] **Step 1: Rewrite v2 contract tests RED**

Delete assertions that v2 contains `on_battery_delay_minutes` or that HA policy must remain read-only. Replace them with the approved domain contract:

```python
def test_v2_policy_has_only_trigger_settings():
    draft = UpsPolicyDraft(
        battery_charge_low_percent=20,
        runtime_safety_reserve_seconds=180,
    )
    assert draft.as_dict() == {
        "battery_charge_low_percent": 20,
        "runtime_safety_reserve_seconds": 180,
    }
    assert not hasattr(draft, "on_battery_delay_minutes")
    assert not hasattr(draft, "power_restore_delay_seconds")
```

Add exact boundary/step tests:

```text
Low Battery valid: 10,15,20,25,30
Low Battery invalid: 9,11,31
Reserve valid: 60..900 step 60
Reserve invalid: 0,61,901
```

- [ ] **Step 2: Add RED total-budget tests**

Use:

```python
facts = PolicySafetyFacts(
    guest_shutdown_budget_seconds=280,
    hostsync_seconds=15,
    finaldelay_seconds=5,
    host_shutdown_reserve_seconds=120,
    ups_poweroff_delay_seconds=60,
)
result = validate_policy(UpsPolicyDraft(20, 180), facts)
assert result.total_shutdown_budget_seconds == 420
assert result.effective_runtime_trigger_seconds == 600
```

Assert `ups_poweroff_delay_seconds` does not change the 420 value.

- [ ] **Step 3: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_policy.py tests/test_ups_policy_v2_contract.py -q
```

Expected: current v1 model fails new contract.

- [ ] **Step 4: Implement v2 dataclasses and exact ranges**

Use:

```python
@dataclass(frozen=True)
class UpsPolicyDraft:
    battery_charge_low_percent: int
    runtime_safety_reserve_seconds: int


@dataclass(frozen=True)
class PolicyValidationResult:
    battery_charge_low_percent: int
    runtime_safety_reserve_seconds: int
    guest_shutdown_budget_seconds: int
    total_shutdown_budget_seconds: int
    effective_runtime_trigger_seconds: int
```

Set `PolicySafetyFacts.host_shutdown_reserve_seconds = 120` by default. Keep `ups_poweroff_delay_seconds` as diagnostic facts if existing callers require it, but exclude it from `calculate_total_shutdown_budget()`.

`policy_hash()` hashes only canonical v2 policy fields, never credentials/derived mutable facts.

- [ ] **Step 5: Add explicit legacy-state migration helper**

Add a pure helper:

```python
def migrate_legacy_policy_state(raw: object, *, effective_low_battery: int | None) -> UpsPolicyDraft | None:
    ...
```

Rules:

```text
- never copy on_battery_delay_minutes into reserve
- reserve defaults to 180
- low battery initializes from effective UPS value only if it is in 10..30 and step-valid
- otherwise return None / require capability resolution before Apply
- power_restore_delay remains outside v2 policy
```

- [ ] **Step 6: Run domain tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_policy.py tests/test_ups_policy_v2_contract.py -q
```

- [ ] **Step 7: Commit**

```bash
git add dh_pve_app/app/ups_policy.py dh_pve_app/tests/test_ups_policy.py dh_pve_app/tests/test_ups_policy_v2_contract.py
git commit -m "refactor(dh-pve): define UPS trigger policy v2"
```

---

### Task 2: Make total shutdown budget authoritative

**Files:**
- Modify: `dh_pve_app/app/ups_policy_host.py`
- Modify: `dh_pve_app/app/ups_shutdown_policy.py`
- Modify: `dh_pve_app/tests/test_ups_policy_host.py`
- Modify: `dh_pve_app/tests/test_ups_shutdown_policy.py`

**Interfaces:**
- Consumes: v2 `PolicySafetyFacts` from Task 1.
- Produces: effective facts for guest budget, HOSTSYNC, FINALDELAY, host reserve 120, diagnostic offdelay and total budget.

- [ ] **Step 1: Preserve current guest-budget behavior with characterization tests**

Before changing code, add/retain tests for reverse startup order groups, per-guest `down` timeout, and `max_workers`. Use existing known sample tasks and assert current budget remains unchanged.

- [ ] **Step 2: Add RED total-facts tests**

Assert `read_policy_safety_facts()` returns:

```text
guest_shutdown_budget_seconds = current calculation
hostsync_seconds              = effective upsmon value
finaldelay_seconds            = effective upsmon value
host_shutdown_reserve_seconds = 120
ups_poweroff_delay_seconds    = effective ups.delay.shutdown/offdelay diagnostic
```

Add a helper/payload assertion for total budget. Do not sum offdelay.

- [ ] **Step 3: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_policy_host.py tests/test_ups_shutdown_policy.py -q
```

- [ ] **Step 4: Implement and expose the total budget**

Keep parsing responsibility in `ups_policy_host.py`; avoid duplicate budget math in runtime/discovery. `UpsShutdownPolicy.as_dict()` may include:

```text
guest_shutdown_budget_seconds
total_shutdown_budget_seconds
host_shutdown_reserve_seconds
hostsync_seconds
finaldelay_seconds
ups_poweroff_delay_seconds
```

`power_restore_delay_seconds` remains read-only/effective and separate.

- [ ] **Step 5: Run tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_policy_host.py tests/test_ups_shutdown_policy.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_policy_host.py dh_pve_app/app/ups_shutdown_policy.py dh_pve_app/tests/test_ups_policy_host.py dh_pve_app/tests/test_ups_shutdown_policy.py
git commit -m "feat(dh-pve): calculate total UPS shutdown budget"
```

---

### Task 3: Add hard-allowlisted Low Battery variable capability/read-back

**Files:**
- Create: `dh_pve_app/app/ups_variables.py`
- Create: `dh_pve_app/tests/test_ups_variables.py`
- Modify: `dh_pve_app/app/ups_control.py` only for shared credential runner utilities if necessary.

**Interfaces:**
- Produces: `UpsVariableCapability`, `read_ups_variable_capabilities()`, `set_battery_charge_low()`.
- Publicly writable variable allowlist contains exactly `battery.charge.low`.

- [ ] **Step 1: Write parser/capability RED tests from `upsrw` shape**

Fixture must include at least:

```text
[battery.charge.low]
Remaining battery level when UPS switches to LB (percent)
Type: STRING
Maximum length: 10
Value: 10
```

and unrelated writable variables. Require only `battery.charge.low` to become an approved capability.

- [ ] **Step 2: Write SET/read-back RED tests**

The setter contract:

```python
set_battery_charge_low(config, 20, runner=...)
```

must:

```text
1. validate 10..30 step 5 before subprocess
2. invoke NUT SET for battery.charge.low only
3. read back effective value through NUT
4. return success only when read-back == requested
5. raise sanitized error on rejection/mismatch
```

Add negative tests proving no caller can pass `ups.delay.start`, `battery.runtime.low`, `load.*`, or arbitrary variable names.

- [ ] **Step 3: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_variables.py -q
```

- [ ] **Step 4: Implement variable module**

Keep variable mutation separate from instant-command capability. Do not broaden `run_ups_beeper_command()`/battery-test command APIs.

Never put command password in exception strings or logs. Pass credentials through the existing NUT invocation pattern and redact subprocess stderr before surfacing it.

- [ ] **Step 5: Run tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_variables.py tests/test_ups_control.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_variables.py dh_pve_app/app/ups_control.py dh_pve_app/tests/test_ups_variables.py dh_pve_app/tests/test_ups_control.py
git commit -m "feat(dh-pve): manage Low Battery variable safely"
```

---

### Task 4: Implement the pure runtime-trigger state machine

**Files:**
- Create: `dh_pve_app/app/ups_trigger.py`
- Create: `dh_pve_app/tests/test_ups_trigger.py`

**Interfaces:**
- Produces: `UpsTriggerEvaluator.evaluate(...) -> UpsTriggerDecision`.
- Has no MQTT, subprocess, filesystem, or systemd side effects.

- [ ] **Step 1: Write RED state-machine tests**

Cover exactly:

```python
def test_ol_never_requests_runtime_fsd(): ...
def test_first_below_threshold_sample_is_only_confirmation_1_of_2(): ...
def test_second_consecutive_below_threshold_sample_requests_fsd(): ...
def test_above_threshold_resets_confirmation(): ...
def test_online_resets_confirmation_before_fsd(): ...
def test_missing_runtime_degrades_without_fsd(): ...
def test_runtime_older_than_15_seconds_degrades_without_fsd(): ...
def test_native_lb_is_immediate_and_bypasses_runtime_confirmation(): ...
def test_existing_fsd_token_prevents_duplicate_request(): ...
def test_committed_runtime_fsd_latches_until_new_boot(): ...
```

Use injected monotonic timestamps; do not sleep.

- [ ] **Step 2: Define decision vocabulary**

Use stable values:

```python
@dataclass(frozen=True)
class UpsTriggerDecision:
    runtime_state: str          # Ready / Confirming / Degraded / Triggered / Idle
    confirmation_count: int     # 0..2
    fsd_required: bool
    reason: str | None          # runtime_guard / native_lb / existing_fsd
    degraded_reason: str | None # runtime_missing / runtime_stale / budget_unavailable
```

- [ ] **Step 3: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_trigger.py -q
```

- [ ] **Step 4: Implement evaluator**

Inputs include only normalized facts:

```text
on_battery
line_power
low_battery
fsd_already_set
runtime_seconds
runtime_sample_monotonic
effective_runtime_trigger_seconds
current_monotonic
```

Freshness rule is `current - sample > 15.0` => stale. Exactly 15.0 remains fresh; `>15` is stale per spec.

Native LB reason is recorded but `fsd_required` is false if NUT already shows FSD; NUT remains authoritative for its own LB path.

- [ ] **Step 5: Run trigger tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_trigger.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_trigger.py dh_pve_app/tests/test_ups_trigger.py
git commit -m "feat(dh-pve): add runtime UPS trigger evaluator"
```

---

### Task 5: Integrate runtime guard with UPS polling and shutdown history

**Files:**
- Modify: `dh_pve_app/app/ups_runtime.py`
- Modify: `dh_pve_app/app/shutdown_integration.py`
- Modify: `dh_pve_app/app/shutdown_history.py`
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/tests/test_ups_runtime.py`
- Modify: `dh_pve_app/tests/test_shutdown_history.py`
- Modify: `dh_pve_app/tests/test_shutdown_integration.py`

**Interfaces:**
- Consumes: `UpsTriggerEvaluator` and authoritative `PolicyValidationResult`.
- Produces: internal fixed FSD executor for runtime guard only; `UPS_TRIGGER` transition logs; v2 incident reason/policy snapshot.

- [ ] **Step 1: Add RED runtime integration tests**

Inject a fake `fsd_executor` into `UpsRuntime`. Require:

```text
- no call OL
- no call at confirmation 1/2
- exactly one call at confirmation 2/2
- no second call after latch
- no call on stale/missing runtime
- no App call when snapshot already has LB+FSD
```

- [ ] **Step 2: Add RED audit-log transition tests**

With the Runtime Observability implementation already present, assert INFO transitions include stable prefixes:

```text
UPS_TRIGGER ON_BATTERY ...
UPS_TRIGGER RUNTIME_CONFIRM ... confirm=1/2
UPS_TRIGGER FSD reason=runtime_guard ...
UPS_TRIGGER LOW_BATTERY reason=native_lb ...
UPS_TRIGGER ONLINE ...
```

Do not log every unchanged UPS poll.

- [ ] **Step 3: Add RED shutdown-history reason tests**

Extend accepted FSD reasons to distinguish:

```text
native_lb
runtime_guard
manual_or_external_fsd
```

Historical policy snapshot must include:

```text
policy_revision
battery_charge_low_percent
guest_shutdown_budget_seconds
total_shutdown_budget_seconds
runtime_safety_reserve_seconds
effective_runtime_trigger_seconds
power_restore_delay_seconds
```

- [ ] **Step 4: Implement fixed internal FSD executor**

Use one non-parameterized function in `main.py`/a focused helper:

```python
def request_nut_fsd() -> None:
    subprocess.run(["/sbin/upsmon", "-c", "fsd"], ...)
```

The path/arguments are static. There is no MQTT topic or user payload that reaches this function.

- [ ] **Step 5: Integrate evaluator after each successful UPS snapshot**

Track the monotonic time of the last valid runtime sample. Use the current **active** v2 policy and current calculated budget; never use draft values.

If active policy/budget is unavailable, runtime guard reports `Blocked`/`Degraded` and does not call FSD. Native NUT LB remains independent.

- [ ] **Step 6: Run integration tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest \
  tests/test_ups_trigger.py \
  tests/test_ups_runtime.py \
  tests/test_shutdown_history.py \
  tests/test_shutdown_integration.py -q
```

- [ ] **Step 7: Commit**

```bash
git add dh_pve_app/app/ups_runtime.py dh_pve_app/app/shutdown_integration.py dh_pve_app/app/shutdown_history.py dh_pve_app/app/main.py dh_pve_app/tests
git commit -m "feat(dh-pve): enforce runtime UPS shutdown guard"
```

---

### Task 6: Retire only the DigitalHouses managed upssched timer

**Files:**
- Modify: `dh_pve_app/app/ups_policy_apply.py`
- Modify: `dh_pve_app/app/ups_shutdown_policy.py`
- Modify: `dh_pve_app/app/shutdown_integration.py`
- Modify: `dh_pve_app/tests/test_ups_policy_apply.py`
- Modify: `dh_pve_app/tests/test_ups_shutdown_policy.py`
- Modify: `dh_pve_app/tests/test_shutdown_integration.py`

**Interfaces:**
- Produces: v2 rendered NUT config with standard upsmon shutdown mechanics but no DH fixed timer.
- Preserves unrelated administrator upssched rules/config.

- [ ] **Step 1: Add RED renderer tests**

Start from a fixture containing both DH-managed lines and unrelated admin content:

```text
# DigitalHouses managed UPS shutdown policy
NOTIFYCMD /usr/sbin/upssched
NOTIFYFLAG ONBATT SYSLOG+EXEC
NOTIFYFLAG ONLINE SYSLOG+EXEC

# unrelated admin rule
NOTIFYFLAG REPLB SYSLOG
```

and:

```text
# DigitalHouses managed UPS shutdown schedule
CMDSCRIPT /opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd
AT ONBATT * START-TIMER dh-pve-ups-shutdown 1800
AT ONLINE * CANCEL-TIMER dh-pve-ups-shutdown

# admin-owned content
AT REPLB * EXECUTE replace-battery-notice
```

Expected v2 output removes only DH-owned timer linkage/rules and preserves `REPLB` content.

- [ ] **Step 2: Require standard NUT shutdown invariants**

Tests must keep:

```text
MONITOR ... dh_primary_user ... primary
SHUTDOWNCMD "/sbin/shutdown -h now"
POWERDOWNFLAG /etc/killpower
HOSTSYNC effective value
FINALDELAY effective value
```

Do not add `ignorelb` or `override.battery.*`.

- [ ] **Step 3: Change readiness tests**

`shutdown_policy_issues()` must no longer emit `upssched_inactive` or `on_battery_delay_unreadable`. It must emit a v2 legacy condition (stable key `legacy_dh_upssched_timer`) when the old DH timer is detected.

- [ ] **Step 4: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_policy_apply.py tests/test_ups_shutdown_policy.py tests/test_shutdown_integration.py -q
```

- [ ] **Step 5: Implement ownership-aware removal**

Replace `_render_upssched(delay_seconds, ...)` with a function that removes the known DH-managed block/token but does not blank arbitrary `upssched.conf`. `_render_upsmon()` must stop adding `NOTIFYCMD /usr/sbin/upssched` and ONBATT/ONLINE `+EXEC` for the DH timer.

If an administrator independently uses upssched for another event, preserve that functionality.

- [ ] **Step 6: Run tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_policy_apply.py tests/test_ups_shutdown_policy.py tests/test_shutdown_integration.py -q
```

- [ ] **Step 7: Commit**

```bash
git add dh_pve_app/app/ups_policy_apply.py dh_pve_app/app/ups_shutdown_policy.py dh_pve_app/app/shutdown_integration.py dh_pve_app/tests
git commit -m "refactor(dh-pve): retire managed ONBATT timer"
```

---

### Task 7: Extend managed NUT ACL for SET without widening MQTT control

**Files:**
- Modify: `dh_pve_app/app/ups_policy_apply.py`
- Modify: `dh_pve_app/app/ups_policy_preflight.py`
- Modify: `dh_pve_app/tests/test_ups_policy_apply.py`
- Modify: `dh_pve_app/tests/test_ups_policy_preflight.py`
- Modify: `dh_pve_app/tests/test_mqtt_bridge.py`

**Interfaces:**
- Produces: managed `dh_primary_user` with current primary/instcmd contract plus NUT SET permission required by `upsrw`.
- Does not expose a generic SET event in `MqttBridge`.

- [ ] **Step 1: Confirm expected NUT account text in tests**

Require the managed section to contain:

```text
[dh_primary_user]
    password = <managed secret>
    upsmon primary
    actions = SET
    instcmds = ALL
```

Preserve other user sections exactly.

- [ ] **Step 2: Add preflight credential/SET capability test**

Preflight must prove the managed credential can perform the **approved capability/read path** needed for Low Battery configuration without changing the variable during preflight. Do not perform a write just to prove credentials.

Actual SET is verified transactionally when the user changes Low Battery.

- [ ] **Step 3: Add MQTT negative contract**

Assert no subscription/event accepts arbitrary strings like:

```text
SET battery.charge.low 20
shutdown.return
load.off
upsmon -c fsd
```

- [ ] **Step 4: Implement ACL renderer and preflight**

Keep PR #12 behavior (`upsmon primary`, `instcmds = ALL`, one managed identity, credential probe) and add only `actions = SET`.

- [ ] **Step 5: Run ACL/preflight/MQTT tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest \
  tests/test_ups_policy_apply.py \
  tests/test_ups_policy_preflight.py \
  tests/test_mqtt_bridge.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_policy_apply.py dh_pve_app/app/ups_policy_preflight.py dh_pve_app/tests
git commit -m "feat(dh-pve): authorize approved UPS variable SET"
```

---

### Task 8: Add typed apply request/result and privileged oneshot boundary

**Files:**
- Create: `dh_pve_app/app/ups_policy_request.py`
- Create: `dh_pve_app/tests/test_ups_policy_request.py`
- Create: `dh_pve_app/bin/dh-pve-ups-policy-apply`
- Create: `dh_pve_app/systemd/dh-pve-ups-policy-apply.service`
- Create: `dh_pve_app/tests/test_ups_policy_apply_service.py`
- Modify: `dh_pve_app/app/ups_policy_apply.py`
- Modify: `dh_pve_app/systemd/dh_pve_app.service` only if an explicit state path directive is needed; do not relax `/etc` protection.

**Interfaces:**
- Daemon writes only typed request JSON and starts a fixed systemd unit.
- Worker owns `/etc/nut` mutation and transaction rollback.
- Worker/daemon coordinate post-restart verification with a request-id startup acknowledgment.

- [ ] **Step 1: Write RED request schema tests**

Define:

```python
@dataclass(frozen=True)
class PolicyApplyRequest:
    schema: int
    request_id: str
    expected_revision: int
    selected_ups: str
    draft: UpsPolicyDraft
    created_at: str
```

Reject unknown top-level fields, unknown draft fields, non-v2 schema, empty request ID, path/command fields, and revision mismatch.

- [ ] **Step 2: Define exact transaction files/results**

`ups_policy_request.json` is consumed once. `ups_policy_result.json` uses:

```json
{
  "schema": 2,
  "request_id": "...",
  "status": "success|failed|noop",
  "message": "sanitized",
  "revision": 8,
  "applied_at": "..."
}
```

`ups_policy_startup_ack.json` uses:

```json
{
  "schema": 2,
  "request_id": "...",
  "effective_verified": true,
  "verified_at": "..."
}
```

No passwords/file backups/stdout are stored in these public transaction files.

- [ ] **Step 3: Add RED systemd-unit security tests**

Require oneshot unit properties:

```ini
Type=oneshot
User=root
Group=root
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
```

Allow write paths narrowly to the managed NUT/App/state targets required by the current installer. Do not add a shell with user-controlled arguments. `ExecStart` is exactly the fixed installed worker entrypoint.

- [ ] **Step 4: Add RED restart/ack/rollback tests**

With fake filesystem/runner:

```text
valid request -> mutate/readback -> phase verified_restart_pending
-> restart dh_pve_app.service
-> matching startup ack -> commit active/revision/result success
```

Failure cases:

```text
missing/mismatched ack -> rollback -> restart old App state -> result failed
App restart command failure -> rollback
Low Battery readback mismatch -> rollback before App restart
NUT service unhealthy -> rollback
```

A no-op target writes result `noop`, does not restart App, does not increment revision.

- [ ] **Step 5: Refactor `UpsPolicyApplier` into reusable transaction phases**

Keep existing rollback-safe file snapshots/service-state restoration from PR #12. Add v2 UPS variable snapshot/read-back and legacy timer removal.

The worker must snapshot old `battery.charge.low` before write and restore it on rollback when it had changed and NUT remains safely reachable.

- [ ] **Step 6: Implement worker entrypoint**

The script only imports the App worker function and exits with its status. No shell parsing beyond fixed `--state-dir`/`--config` constants supplied by systemd.

- [ ] **Step 7: Run request/service/apply tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest \
  tests/test_ups_policy_request.py \
  tests/test_ups_policy_apply_service.py \
  tests/test_ups_policy_apply.py -q
systemd-analyze verify systemd/*.service
```

- [ ] **Step 8: Commit**

```bash
git add dh_pve_app/app/ups_policy_request.py dh_pve_app/app/ups_policy_apply.py dh_pve_app/bin/dh-pve-ups-policy-apply dh_pve_app/systemd dh_pve_app/tests
git commit -m "feat(dh-pve): add transactional UPS policy worker"
```

---

### Task 9: Implement backend VIEW/EDIT/CONFIRM/APPLYING state machine

**Files:**
- Modify: `dh_pve_app/app/ups_runtime.py`
- Modify: `dh_pve_app/app/mqtt_bridge.py`
- Modify: `dh_pve_app/app/topics.py`
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/tests/test_ups_runtime.py`
- Modify: `dh_pve_app/tests/test_mqtt_bridge.py`
- Modify: `dh_pve_app/tests/test_topics.py`
- Modify: `dh_pve_app/tests/test_main_contract.py`

**Interfaces:**
- UI states: `VIEW`, `EDIT_DRAFT`, `CONFIRM`, `APPLYING`.
- Fixed topics below `.../ups/policy`:

```text
edit
review
confirm
cancel
draft/battery_charge_low/set
draft/runtime_safety_reserve/set
```

- [ ] **Step 1: Add RED state-transition tests**

Require:

```text
VIEW + edit -> EDIT_DRAFT and draft=active
EDIT_DRAFT + slider -> draft only, no apply request
EDIT_DRAFT + cancel -> VIEW and draft=active
EDIT_DRAFT + review -> CONFIRM with immutable reviewed snapshot
CONFIRM + cancel -> EDIT_DRAFT without host mutation
CONFIRM + confirm -> APPLYING and exactly one typed request
APPLYING rejects draft/edit/review mutations
worker failure -> EDIT_DRAFT + sanitized error
worker success/noop -> VIEW
```

- [ ] **Step 2: Add RED restart recovery tests**

If App starts and privileged metadata is `verified_restart_pending` for request X, it must:

```text
1. reread effective Low Battery/NUT policy/budget
2. compare with target metadata
3. write startup ack for X only when effective values match
4. remain safe if values do not match
```

After worker marks the transaction active/result success, the App consumes the result, updates `ups_runtime.json`, publishes revision/last-change, and stores `notified_revision` only after successful publication.

- [ ] **Step 3: Add typed MQTT events**

Define explicit dataclasses/events. Draft parsers reuse v2 policy validation. Do not call `upsrw`, systemctl, or policy applier from `handle_message()`.

- [ ] **Step 4: Implement fixed apply-service requester**

The long-running App writes request atomically under its state dir and executes only:

```text
systemctl start --no-block dh-pve-ups-policy-apply.service
```

No service name or command comes from MQTT.

- [ ] **Step 5: Migrate persisted v1 runtime state**

On first v2 startup:

```text
- retain revision/history only when it can be represented safely
- do not copy on_battery_delay_minutes to reserve
- reserve starts at 180
- Low Battery draft is initialized from current effective UPS value if valid
- restore delay remains effective/read-only outside v2 policy
- UI/status remains Legacy policy until old timer migration is applied
```

Do not silently label an unmigrated v1 policy as v2 Active.

- [ ] **Step 6: Run backend state tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest \
  tests/test_ups_runtime.py \
  tests/test_mqtt_bridge.py \
  tests/test_topics.py \
  tests/test_main_contract.py -q
```

- [ ] **Step 7: Commit**

```bash
git add dh_pve_app/app/ups_runtime.py dh_pve_app/app/mqtt_bridge.py dh_pve_app/app/topics.py dh_pve_app/app/main.py dh_pve_app/tests
git commit -m "feat(dh-pve): add UPS policy edit and confirm flow"
```

---

### Task 10: Build v2 MQTT Discovery and dashboard UX with v1 tombstones

**Files:**
- Modify: `dh_pve_app/app/discovery_ups.py`
- Modify: `dh_pve_app/app/discovery_ups_groups.py`
- Modify: `dh_pve_app/examples/dh_pve_ups_dashboard.yaml`
- Modify: `dh_pve_app/tests/test_ups_discovery.py`
- Modify: `dh_pve_app/tests/test_ups_policy_v2_contract.py`
- Modify: `dh_pve_app/tests/test_ups_dashboard_contract.py`

**Interfaces:**
- Consumes: Task 9 policy payload/UI state.
- Produces: stable HA entities and conditional VIEW/EDIT/CONFIRM/APPLYING dashboard sections.

- [ ] **Step 1: Add RED discovery contract for VIEW entities**

Require stable entities for:

```text
active Low Battery threshold
active safety reserve
guest shutdown budget
total shutdown budget
effective runtime trigger
current battery runtime
native LB readiness
runtime readiness
overall policy status/UI state
policy revision
last applied
last change diff
runtime degraded reason
Config UPS trigger button
```

`power_restore_delay` remains a separate read-only observed sensor.

- [ ] **Step 2: Add capability-driven draft controls**

When `battery.charge.low` is writable:

```text
number draft Low Battery: min=10 max=30 step=5
```

If readable but not writable, expose only the active/effective sensor. Do not create a disabled fake number.

Always expose draft Safety Reserve number in edit mode:

```text
min=60 max=900 step=60 unit=s
```

Its command topic changes draft only.

- [ ] **Step 3: Add workflow buttons**

Discovery buttons map to the exact typed topics:

```text
Config UPS trigger -> edit
Apply configuration -> review
Confirm -> confirm
Cancel -> cancel
```

No button maps directly to FSD, SET VAR, `shutdown.return`, or generic commands.

- [ ] **Step 4: Tombstone v1 fixed-delay entities**

Add one-time Discovery tombstones for the old `policy_on_battery_delay_observed` component and any v1 editable IDs/topics that existed in earlier development versions. Preserve `policy_power_restore_delay_observed` as the separate read-only power-return value.

- [ ] **Step 5: Implement dashboard conditional sections**

`dh_pve_ups_dashboard.yaml` must render:

```text
VIEW        -> active policy summary + Config button
EDIT_DRAFT  -> two draft controls + calculated trigger + Apply + Cancel
CONFIRM     -> final values/diff + Confirm + Cancel
APPLYING    -> read-only applying status; no editable controls
error       -> returns to EDIT_DRAFT with error visible
```

Do not show `Unavailable` optional controls when capability is absent.

- [ ] **Step 6: Run discovery/dashboard tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest \
  tests/test_ups_discovery.py \
  tests/test_ups_policy_v2_contract.py \
  tests/test_ups_dashboard_contract.py -q
```

- [ ] **Step 7: Commit**

```bash
git add dh_pve_app/app/discovery_ups.py dh_pve_app/app/discovery_ups_groups.py dh_pve_app/examples/dh_pve_ups_dashboard.yaml dh_pve_app/tests
git commit -m "feat(dh-pve): add UPS trigger policy UI"
```

---

### Task 11: Add durable config-change and derived-budget notifications

**Files:**
- Modify: `dh_pve_app/app/ups_runtime.py`
- Modify: `dh_pve_app/app/shutdown_integration.py`
- Modify: `dh_pve_app/examples/packages/dh_app_pve_package.yaml`
- Modify: `dh_pve_app/tests/test_ups_runtime.py`
- Modify: `dh_pve_app/tests/test_ha_package_contract.py` or the existing package contract test used by this project.

**Interfaces:**
- Produces two distinct durable change classes: user policy config revision and derived budget revision/event.

- [ ] **Step 1: Add RED committed-diff tests**

Given active:

```json
{"battery_charge_low_percent": 10, "runtime_safety_reserve_seconds": 180}
```

and target:

```json
{"battery_charge_low_percent": 20, "runtime_safety_reserve_seconds": 300}
```

with trigger 600 -> 720, require:

```json
{
  "battery_charge_low_percent": {"old": 10, "new": 20},
  "runtime_safety_reserve_seconds": {"old": 180, "new": 300},
  "effective_runtime_trigger_seconds": {"old": 600, "new": 720}
}
```

No unchanged fields, credentials, raw config text, or internal file paths.

- [ ] **Step 2: Require post-restart-only notification signal**

`policy_revision` becomes publicly active only after matching startup ack and worker commit. Package automation triggers on a real revision increase, ignores initial HA startup/from-unavailable transitions, and formats the persisted `last_change` diff.

Example notification text:

```text
🔋 Конфигурация UPS изменена
Low Battery: 10 % -> 20 %
Safety reserve: 03:00 -> 05:00
Runtime trigger: 10:00 -> 12:00
Revision: 8
```

Use the project's existing notification service abstraction; do not hard-code a site-specific phone target into the global example package.

- [ ] **Step 3: Add RED derived-budget change tests**

Manual Refresh after a PVE guest timeout/order change must recalculate budget. If active user policy is unchanged:

```text
policy_revision does not change
policy_last_applied does not change
last_budget_change contains old/new total budget and runtime trigger
budget_change_revision/event increments separately
```

Classification string is exactly `UPS_SHUTDOWN_BUDGET_CHANGED`.

- [ ] **Step 4: Implement budget-change detection on Refresh**

Compare the previous effective derived values to newly-read facts. Only emit when total budget/effective trigger changes; ordinary refresh with equal values is silent.

- [ ] **Step 5: Run runtime/package tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_ups_runtime.py tests/test_ha_package_contract.py -q
```

If this repository uses a differently named HA package test, use the existing exact package-contract test file rather than creating duplicate test infrastructure.

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_runtime.py dh_pve_app/app/shutdown_integration.py dh_pve_app/examples/packages/dh_app_pve_package.yaml dh_pve_app/tests
git commit -m "feat(dh-pve): publish UPS policy change events"
```

---

### Task 12: Installer, commissioning CLI, docs, full verification, and safe deployment

**Files:**
- Modify: `dh_pve_app/install.sh`
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`
- Modify relevant installer/CLI tests.

**Interfaces:**
- Produces: release-ready Policy v2 installation/migration with two systemd units and no v1 timer dependency.

- [ ] **Step 1: Update installer RED tests/contracts**

Installer must install:

```text
/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-apply
/etc/systemd/system/dh-pve-ups-policy-apply.service
```

with root ownership and non-group/world-writable modes, then `systemctl daemon-reload`.

Do not install/enable the apply service as a long-running daemon; it is oneshot and started only on confirmed requests.

- [ ] **Step 2: Replace old commissioning CLI contract**

Retire CLI inputs that require `--on-battery-delay-minutes`. Safe commissioning/preflight should report v2 readiness/migration and accept v2 policy fields only where explicit commissioning still exists.

Do not expose direct FSD as part of commissioning.

- [ ] **Step 3: Update README**

Document:

```text
FSD = native LB OR confirmed runtime guard
Low Battery 10..30 step5
Safety reserve 60..900 step60 default180
Total budget = guest + HOSTSYNC + FINALDELAY + 120
Runtime stale >15s
2-poll confirmation
power restore delay remains separate at current 120s
HA draft -> review -> confirm -> transactional worker -> App restart
v1 upssched timer retired
```

Include a non-destructive diagnostic command section for reading active policy, budget and transaction state.

- [ ] **Step 4: Update CHANGELOG**

Record Policy v2 as a distinct feature after Runtime Observability. Explicitly call out v1 timer migration, new HA editor, hard-allowlisted Low Battery write, and no destructive release test.

- [ ] **Step 5: Run compile + full DH PVE test suite**

```bash
python -m compileall -q dh_pve_app/app dh_pve_app/tests
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q
bash -n dh_pve_app/install.sh
bash -n dh_pve_app/bin/dh-pve-ups-policy-apply
```

Expected: all PASS.

- [ ] **Step 6: Verify both systemd units**

```bash
sudo install -d /opt/digitalhouses/dh_pve_app/.venv/bin
sudo ln -sf "$(command -v python)" /opt/digitalhouses/dh_pve_app/.venv/bin/python
systemd-analyze verify dh_pve_app/systemd/*.service
```

Expected: exit 0.

- [ ] **Step 7: Run repository contract and diff checks**

```bash
python scripts/validate_repository.py
git diff --check
git status --short
git log --oneline --decorate -15
```

Review specifically:

```text
- no v1 ONBATT timer writer remains
- no generic MQTT SET/INSTCMD/FSD path exists
- no ignorelb/override.battery.* introduced
- no /etc/nut write permission added to long-running App unit
- no old 30-minute value mapped to reserve
- restore delay remains separate
- no fast Recorder entities introduced
```

- [ ] **Step 8: Commit docs/installer**

```bash
git add dh_pve_app/install.sh dh_pve_app/app/main.py dh_pve_app/README.md dh_pve_app/CHANGELOG.md dh_pve_app/tests
git commit -m "docs(dh-pve): finalize UPS trigger policy v2"
```

- [ ] **Step 9: Non-destructive home-PVE pre-apply validation**

Deploy exact feature SHA to `192.168.11.30` using the normal project deploy procedure. Before Apply, capture:

```bash
systemctl status dh_pve_app.service nut-monitor.service nut-server.service --no-pager
upsc ups@127.0.0.1:3493 | grep -E '^(ups.status|battery.charge|battery.charge.low|battery.runtime|ups.delay.start|ups.delay.shutdown):'
upsrw ups@127.0.0.1:3493 | grep -A8 -B2 -E '^\[battery\.charge\.low\]'
```

Verify HA reports `Legacy policy` while the old DH timer still exists.

- [ ] **Step 10: Characterize Low Battery safely while OL**

Do not unplug mains. Confirm the current CyberPower reports `battery.charge.low` writable. Apply only an approved range value through the new transaction, verify exact read-back, then if needed apply the intended final value. Do not test unsupported values just to discover failure boundaries.

- [ ] **Step 11: Verify first successful v2 migration**

After confirmed Apply:

```text
- App restarted successfully
- active revision/diff visible after restart
- battery.charge.low exact read-back equals requested value
- DH ONBATT/ONLINE timer absent
- unrelated upssched content preserved
- nut-driver/nut-server/nut-monitor healthy
- PRIMARY identity intact
- POWERDOWNFLAG/SHUTDOWNCMD/HOSTSYNC/FINALDELAY intact
- power restore delay still 120s effective
- VIEW mode restored
- config-change notification contains only old -> new changes
```

- [ ] **Step 12: Verify UI without host mutation**

Exercise:

```text
VIEW -> EDIT -> move sliders -> Cancel
VIEW -> EDIT -> move sliders -> Review -> Cancel
```

Confirm no NUT/UPS config changed and no App restart occurred.

Then perform one deliberate safe confirmed Apply while OL and verify one restart/revision only.

- [ ] **Step 13: Verify derived budget-change event**

Using a safe temporary Proxmox guest timeout/order adjustment approved for the test host, press UPS Refresh and verify:

```text
- total budget changes
- runtime trigger changes
- event = UPS_SHUTDOWN_BUDGET_CHANGED
- explicit policy_revision does not increment
```

Restore the guest setting and verify the reverse derived change. This is a PVE configuration test, not an UPS power test.

- [ ] **Step 14: Final release gate**

Inspect at least several normal UPS polling windows in the new Observability journal:

```bash
journalctl -u dh_pve_app.service --since -10min --no-pager | grep -E 'UPS_TRIGGER|PERF|COLLECTORS|COMMANDS|WARNING|ERROR'
```

Confirm there is no upssched battery-trigger loop in normal OL operation and no unexpected INFO storm.

**Do not** perform destructive FSD, mains removal, UPS output-off, deep discharge, or killpower as a release requirement.

---

## Self-Review Checklist

Before calling Policy v2 complete, verify every design requirement maps to implementation:

- V2 domain/ranges/defaults/no legacy delay migration: Task 1.
- Total budget and separate restore/offdelay semantics: Task 2.
- Capability-driven, hard-allowlisted Low Battery read/write/read-back: Task 3.
- 2-poll runtime guard, >15s stale behavior, native LB independence, latch: Tasks 4–5.
- `UPS_TRIGGER` observability and shutdown incident snapshot: Task 5.
- DigitalHouses upssched timer removal with unrelated-content preservation: Task 6.
- SET ACL without generic MQTT authority: Task 7.
- Privileged transactional worker, restart acknowledgment, rollback/no-op semantics: Task 8.
- VIEW/EDIT/CONFIRM/APPLYING backend with draft-only sliders: Task 9.
- Discovery/dashboard and v1 tombstones: Task 10.
- Durable post-restart old -> new notification and separate budget event: Task 11.
- Installer/docs/full CI/non-destructive home-PVE release validation: Task 12.
- `power_restore_delay=120s` remains separate from Config UPS trigger throughout.
- NFS/CIFS/SMB provider dependency detection remains technical debt and is not implemented in this plan.
