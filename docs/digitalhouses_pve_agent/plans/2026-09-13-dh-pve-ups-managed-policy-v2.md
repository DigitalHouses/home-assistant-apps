# DH PVE UPS Managed Policy Implementation Plan v2

> Supersedes the policy-surface and Task 5/6 portions of `2026-09-13-dh-pve-ups-managed-policy.md`.

**Goal:** finish the managed NUT/Proxmox shutdown policy without overriding hardware Low Battery, simplify Home Assistant to two writable policy values, expose UPS hardware thresholds read-only, add persistent scheduled Quick/Deep battery testing with last-10 history, and require a read-only commissioning preflight before any live shutdown wiring.

**Architecture:** PVE/NUT owns shutdown. Normal prolonged outage uses `ONBATT -> upssched timer -> local FSD`. Emergency shutdown uses the UPS-native `LB` signal through `upsmon`. Home Assistant edits draft policy only and never decides shutdown. Battery testing is a separate local PVE scheduler.

**Spec:** `docs/superpowers/specs/2026-09-13-dh-pve-ups-policy-testing-revision.md`

## Global constraints

- Branch `feature/dh-pve-ups-scan` only.
- TDD: RED commit and verified failing CI before production change.
- No live FSD, host shutdown, load-off, UPS output removal, or real shutdown commissioning in repository tests.
- Do not enable `ignorelb`.
- Do not write `battery.runtime.low` or `battery.charge.low` from policy code.
- Preserve existing commissioning state on the live host until a separately reviewed deployment.
- Hardware values are read-only telemetry; no UPS-model-specific correction logic.
- `UpsPolicyApplier` remains unwired in `main.py` until the read-only commissioning preflight has been reviewed on the target PVE.

## Completed work retained from v1

Tasks 1–4 already implemented the initial policy model, MQTT/discovery plumbing, draft/active lifecycle, and Proxmox shutdown-budget reader. Those implementations now require a compatibility refactor because the approved policy surface changed from three values to two.

## Task 4A — RED contract for simplified policy

**Files:**
- modify `dh_pve_app/tests/test_ups_policy.py`
- modify policy MQTT/discovery/runtime tests

Write failing tests proving:

- `UpsPolicyDraft` has only `on_battery_delay_minutes` and `power_restore_delay_seconds`;
- `parse_policy_value()` rejects `emergency_runtime_reserve_minutes` as unknown;
- policy hash contains only the two approved values;
- validation no longer computes/requires emergency runtime reserve;
- MQTT has no emergency-reserve command topic;
- Discovery has no emergency-reserve number entity;
- runtime persisted/default draft is `30 min / 120 s`;
- lifecycle rollback/success semantics remain unchanged for the two-value model.

Commit RED tests and verify CI fails only because production code still implements the old three-value contract.

## Task 4B — GREEN simplified policy refactor

**Files:**
- `dh_pve_app/app/ups_policy.py`
- `dh_pve_app/app/topics.py`
- `dh_pve_app/app/mqtt_bridge.py`
- `dh_pve_app/app/discovery_ups.py`
- `dh_pve_app/app/ups_runtime.py`
- affected tests/fixtures

Remove the emergency-reserve field/topic/entity/state from the application contract. Keep Proxmox shutdown-budget facts as read-only diagnostics for commissioning and effective-policy reporting.

Run full DH PVE tests and repository CI green.

## Task 5 — Managed NUT apply transaction, native LB preserved

**Files:**
- create `dh_pve_app/app/ups_policy_apply.py`
- create `dh_pve_app/bin/dh-pve-ups-policy-cmd`
- create/modify policy apply and sandbox tests
- modify installer/systemd comments as required
- do **not** wire the applier into `main.py` yet

### RED tests

Prove generated target semantics:

- production `SHUTDOWNCMD` is the local system shutdown command;
- `POWERDOWNFLAG /etc/killpower` exists;
- `NOTIFYCMD /usr/sbin/upssched` and required ONLINE/ONBATT EXEC flags exist;
- ONBATT starts a cancellable timer using `on_battery_delay_minutes * 60`;
- ONLINE cancels that timer before commitment;
- timer expiry invokes local `upsmon -c fsd` only through the owned internal command script;
- `offdelay` remains at least the device/driver-safe minimum;
- `ondelay` matches the validated restore delay and is reread/verified;
- generated configuration does **not** contain `ignorelb`;
- existing flag-form `ignorelb` without `=` is rejected;
- Apply never writes `battery.runtime.low`, `battery.charge.low`, or an override for either;
- post-write verification must match target values before success;
- every mutable-file mutation stage has rollback coverage;
- no HA-exposed path can execute FSD/arbitrary NUT command/arbitrary shell.

### Immutable helper rule

The FSD timer helper is versioned application code at:

`/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd`

It must be installed `root:root`, executable, not group/other writable, and protected by `ProtectSystem=full`. The runtime applier validates and references it but never creates, edits, replaces, or rolls it back. Only the exact timer token `dh-pve-ups-shutdown` may invoke `upsmon -c fsd`.

### GREEN implementation

Implement explicit-path atomic backup/write/verify/rollback for mutable policy files with injected command execution for tests. Keep the applier disconnected from production runtime until Task 10 preflight is complete. Do not run the transaction on the live PVE host in this task.

## Task 6 — Read-only effective UPS configuration

**Files:**
- `dh_pve_app/app/ups_shutdown_policy.py`
- `dh_pve_app/app/ups_runtime.py`
- `dh_pve_app/app/discovery_ups.py`
- tests

Add normalized read-only fields when exposed by NUT:

- hardware low runtime (`battery.runtime.low`);
- low charge (`battery.charge.low`);
- warning charge (`battery.charge.warning`);
- UPS shutdown/off delay (`ups.delay.shutdown`);
- UPS start/restore delay (`ups.delay.start`).

Human-readable effective-policy semantics must say:

- prolonged outage waits configured N minutes;
- restoration before commit cancels normal timer;
- UPS-native Low Battery commits shutdown immediately;
- after commit the full power-cycle sequence is irreversible.

Remove old hard/recommended emergency reserve fields from the product contract.

## Task 7 — Battery-test scheduler model

**Files:**
- create `dh_pve_app/app/ups_test_schedule.py`
- create `dh_pve_app/tests/test_ups_test_schedule.py`

Pure model first.

Represent independent Quick/Deep schedules:

- interval days (`0` disables automatic test);
- preferred local `HH:MM`;
- last scheduled execution;
- next due calculation.

Initial defaults:

- Quick: 30 days, 12:00;
- Deep: 180 days, 13:00.

Tests prove:

- due calculation survives restart from persisted timestamps;
- overdue test outside preferred time does not run immediately;
- disabled schedule never becomes runnable;
- Deep takes priority if both are eligible together;
- safety-gate rejection keeps the test due.

No subprocess/MQTT/filesystem operations in the pure scheduling module.

## Task 8 — MQTT/Discovery settings for battery-test schedules

Expose writable schedule settings and read-only next/last/current/history state.

Backend representation remains strict local `HH:MM`; Home Assistant MQTT Discovery uses the supported time entity transport.

Required semantics:

- Quick interval days;
- Quick preferred time;
- Deep interval days;
- Deep preferred time;
- last/next Quick;
- last/next Deep;
- current test state;
- bounded last-10 history.

Direct MQTT payloads must be validated server-side.

## Task 9 — Persistent scheduler, safety gate, and history

**Files:**
- modify `dh_pve_app/app/ups_runtime.py` or isolate a dedicated test runtime component
- tests

Persist schedule config and last 10 records under app state.

Before scheduled Quick/Deep execution require:

- NUT/UPS available;
- `OL` and not `OB`/`LB`;
- requested command capability exists;
- no test already active;
- battery not critical/low;
- no shutdown/FSD in progress.

History record fields where available:

- start/end local timestamps;
- type Quick/Deep;
- source Manual/Scheduled;
- normalized result plus safe exact NUT result;
- duration;
- charge before/after;
- runtime before/after;
- load before;
- failure/skip reason.

History keeps newest 10 only.

## Task 10 — Read-only commissioning preflight

**Files:**
- create `dh_pve_app/app/ups_policy_preflight.py`
- create `dh_pve_app/tests/test_ups_policy_preflight.py`
- optionally expose a read-only CLI/report surface after the pure reader is green

The preflight must return `Ready` only when all required commissioning conditions are true:

- selected UPS reachable through NUT;
- `nut-driver@<ups>` active;
- `nut-server` active;
- local upsmon role `primary`;
- `nut-monitor` still inactive;
- current `SHUTDOWNCMD` still `/bin/true`;
- `/etc/killpower` absent;
- immutable helper exists, is executable, and is not group/other writable;
- selected UPS section contains no `ignorelb`/LB override;
- Proxmox guest shutdown budget is readable.

The reader may issue only read/status operations. Tests must prove it does not call service mutation commands, `upsmon -c fsd`, generic `upscmd`, or any write path.

If any check fails, state is `Blocked`; the preflight never repairs the host automatically.

## Task 11 — Documentation/dashboard contract and final verification

Update README/CHANGELOG/dashboard contract after backend is green.

UI sections:

1. operational UPS status;
2. electrical/battery telemetry;
3. read-only UPS protection/settings;
4. PVE emergency shutdown policy with two writable values and Apply button;
5. battery testing: schedules, manual controls, current test, last 10 history;
6. commissioning/preflight diagnostics;
7. general diagnostics.

Run complete DH PVE tests and repository CI. Then use verification/code-review workflow before claiming completion.

## Separate live commissioning gate

Live commissioning remains a separate explicit step after repository verification:

1. deploy the reviewed feature branch while keeping `UpsPolicyApplier` unwired;
2. run/read the commissioning preflight on the actual PVE;
3. verify MQTT remains draft-only and cannot execute FSD;
4. inspect the exact generated NUT diff from the target host facts;
5. only after explicit review wire/enable the real apply path;
6. never use `upsmon -c fsd` as a casual live test.
