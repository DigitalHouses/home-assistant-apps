# DH PVE UPS Managed Shutdown Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe, user-facing UPS shutdown policy workflow to `dh_pve_app`: MQTT draft sliders, explicit Apply Policy, validation, active/draft state, timestamps/revision/hash, and a managed NUT/Proxmox apply transaction with rollback.

**Architecture:** Keep policy semantics in a new pure module, keep MQTT transport/discovery separate, keep draft/active lifecycle in `UpsRuntime`, and isolate all host writes in a dedicated `UpsPolicyApplier`. Home Assistant only edits draft values; production configuration changes only inside the explicit Apply transaction. The existing UPS polling, scan, refresh, and battery-test paths remain read-only.

**Tech Stack:** Python 3.13, pytest, paho-mqtt, NUT 2.8.x, Proxmox VE 8.4, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-12-dh-pve-ups-control-shutdown-design.md`

## Global Constraints

- Branch: `feature/dh-pve-ups-scan`; do not modify `main`.
- Use TDD: RED commit, verify expected CI failure, then GREEN implementation.
- Home Assistant never decides shutdown; Proxmox/NUT remains authoritative.
- No HA control may expose FSD, `load.off`, `shutdown.return`, `shutdown.stayoff`, arbitrary `upscmd`, arbitrary shell, or arbitrary NUT file text.
- Draft sliders never modify host state.
- Active policy is the source of truth.
- Failed validation/apply leaves active policy and `last_applied` unchanged and restores draft sliders to the active policy.
- Secrets never enter MQTT state, policy hash, discovery, validation errors, or logs.
- Dashboard work is out of scope until backend policy contract is complete.
- Existing UPS telemetry must remain model-generic; do not special-case CyberPower telemetry.

---

### Task 1: Pure policy model, ranges, hash, and shutdown-budget math

**Files:**
- Create: `dh_pve_app/app/ups_policy.py`
- Create: `dh_pve_app/tests/test_ups_policy.py`

**Interfaces:**
- Produces `UpsPolicyDraft(on_battery_delay_minutes: int, emergency_runtime_reserve_minutes: int, power_restore_delay_seconds: int)`.
- Produces `PolicySafetyFacts(guest_shutdown_budget_seconds, hostsync_seconds, finaldelay_seconds, host_shutdown_reserve_seconds=60, ups_poweroff_delay_seconds=60, safety_margin_seconds=60)`.
- Produces `PolicyValidationError`.
- Produces `parse_policy_value(key: str, text: str) -> int` for the three MQTT number controls.
- Produces `policy_hash(policy: UpsPolicyDraft) -> str` using canonical JSON and SHA-256.
- Produces `calculate_guest_shutdown_budget(tasks: Sequence[GuestShutdownTask], max_workers: int) -> int`, grouping by descending startup order and simulating concurrent workers inside a group.
- Produces `validate_policy(draft, facts) -> PolicyValidationResult` with hard minimum and recommended reserve.

- [ ] **Step 1: Write failing tests**

Tests must prove:

```python
assert parse_policy_value("on_battery_delay_minutes", "30") == 30
assert parse_policy_value("emergency_runtime_reserve_minutes", "15") == 15
assert parse_policy_value("power_restore_delay_seconds", "120") == 120
```

and reject malformed, out-of-range, and wrong-step values. Hard UI/application ranges are 5–60 min step 5, 10–30 min step 1, and 60–300 s step 30.

Test canonical hashes are stable for equal policy values.

Test guest budget with the current production topology equivalent to group maxima `30 + 30 + 60 + 60 + 100 = 280` seconds when workers are sufficient, and a second case where more tasks than workers requires multiple waves.

Test safety calculation with `guest=280`, `HOSTSYNC=120`, `FINALDELAY=5`, host reserve `60`, UPS poweroff `60`, safety margin `60`: hard minimum is `585 s`; a 10-minute emergency reserve is valid and 9 minutes is rejected. Recommended reserve is hard minimum plus a 300-second operational cushion, rounded up to the next whole minute.

- [ ] **Step 2: Run RED**

Run in CI: `PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ups_policy.py -q`

Expected: FAIL because `app.ups_policy` does not exist.

- [ ] **Step 3: Implement minimal pure module**

No subprocess, filesystem, MQTT, or NUT calls are allowed in `ups_policy.py`.

- [ ] **Step 4: Run GREEN and full DH PVE tests**

Run: `PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat(dh-pve): add UPS shutdown policy model`

---

### Task 2: MQTT topics, draft controls, Apply Policy button, and policy sensors

**Files:**
- Modify: `dh_pve_app/app/topics.py`
- Modify: `dh_pve_app/app/mqtt_bridge.py`
- Modify: `dh_pve_app/app/discovery_ups.py`
- Modify: `dh_pve_app/tests/test_mqtt_bridge.py`
- Modify: `dh_pve_app/tests/test_ups_discovery.py`

**Interfaces:**
- Extend `UpsTopics` with:
  - `policy_on_battery_delay_set`
  - `policy_emergency_runtime_reserve_set`
  - `policy_power_restore_delay_set`
  - `policy_apply`
- Add `PolicyDraftUpdate(key: str, value: int)` queue entries.
- Add `MqttEvents.ups_policy_updates` and `MqttEvents.ups_policy_apply_requested`.
- Discovery reads policy state from the existing retained UPS JSON state topic.

- [ ] **Step 1: Write failing MQTT/discovery tests**

Verify three number entities:

```text
number.dh_pve_ups_policy_on_battery_delay      min=5 max=60 step=5 unit=min
number.dh_pve_ups_policy_emergency_runtime_reserve min=10 max=30 step=1 unit=min
number.dh_pve_ups_policy_power_restore_delay   min=60 max=300 step=30 unit=s
```

Each number uses `mode: slider`, its own `/set` command topic, and a state template under `value_json.policy.draft`.

Verify `button.dh_pve_ups_apply_policy` publishes `PRESS` to `<base>/ups/policy/apply`.

Verify sensors:
- `sensor.dh_pve_ups_policy_status`
- `sensor.dh_pve_ups_policy_apply_result`
- `sensor.dh_pve_ups_policy_last_applied` with `device_class: timestamp` and revision/hash attributes.

Verify MQTT accepts valid number payloads into the policy queue, rejects malformed/out-of-range payloads, and sets Apply event only for `PRESS`.

- [ ] **Step 2: Run RED in CI**

Expected: failures for missing topics/entities/events.

- [ ] **Step 3: Implement transport/discovery only**

Do not write NUT/PVE configuration in this task.

- [ ] **Step 4: Run GREEN and full suite**

- [ ] **Step 5: Commit**

Commit message: `feat(dh-pve): expose UPS policy draft controls`

---

### Task 3: Draft/active lifecycle, persistence, status, timestamp, revision, and rollback-to-active UI

**Files:**
- Modify: `dh_pve_app/app/ups_runtime.py`
- Modify: `dh_pve_app/tests/test_ups_runtime.py`
- Create: `dh_pve_app/tests/test_ups_policy_runtime.py`

**Interfaces:**
- Add injectable `policy_facts_reader: Callable[[], PolicySafetyFacts]`.
- Add injectable `policy_applier: Callable[[UpsPolicyDraft, PolicySafetyFacts], PolicyApplyResult]`.
- Persist under `ups_runtime.json`:
  - `policy_active`
  - `policy_draft`
  - `policy_status`
  - `policy_apply_result`
  - `policy_last_applied`
  - `policy_revision`
  - `policy_hash`
- UPS state payload adds a top-level `policy` object containing draft, active, status, result, timestamps, revision/hash, hard/recommended reserves, and normalized timeline fields.

- [ ] **Step 1: Write failing lifecycle tests**

Prove:
- changing a draft queue value sets `Pending changes` and never calls `policy_applier`;
- Apply takes one immutable copy of draft values;
- successful apply sets `Active`, increments revision, updates hash, and sets `last_applied` to `now_iso()`;
- failed validation leaves active/revision/timestamp unchanged and resets draft to active values;
- failed apply leaves active/revision/timestamp unchanged, resets draft to active, and reports `Apply failed`;
- reconnect republishes persisted policy state;
- no secret-bearing config object contributes to policy hash.

- [ ] **Step 2: Run RED in CI**

- [ ] **Step 3: Implement lifecycle with no host writes except through injected applier**

Commissioning with no active policy starts with draft defaults `30 min / 15 min / 120 s`, status `Commissioning`, revision `0`, no last-applied timestamp.

- [ ] **Step 4: Run GREEN and full suite**

- [ ] **Step 5: Commit**

Commit message: `feat(dh-pve): manage UPS policy draft and active state`

---

### Task 4: Read Proxmox shutdown topology and calculate real guest budget

**Files:**
- Create: `dh_pve_app/app/ups_policy_host.py`
- Create: `dh_pve_app/tests/test_ups_policy_host.py`
- Modify: `dh_pve_app/app/main.py`

**Interfaces:**
- `read_policy_safety_facts(...) -> PolicySafetyFacts` reads:
  - `/etc/pve/qemu-server/*.conf`
  - `/etc/pve/lxc/*.conf`
  - `qm list`
  - `pct list`
  - `/etc/pve/datacenter.cfg`
  - effective `HOSTSYNC`, `FINALDELAY`, UPS `offdelay`.
- Include all autostart guests plus currently-running guests.
- Missing `startup order` is treated as the highest shutdown group, matching PVE stopall behavior.
- Missing `down` uses 180 seconds.
- Worker count uses `max_workers` if configured, otherwise `nproc`.

- [ ] **Step 1: Write failing parser/budget tests with fixture configs**

Verify the current topology computes 280 seconds and that stopped, non-autostart experimental guests do not inflate the active policy budget unless currently running.

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement read-only host facts**

- [ ] **Step 4: Run GREEN and full suite**

- [ ] **Step 5: Commit**

Commit message: `feat(dh-pve): calculate Proxmox UPS shutdown budget`

---

### Task 5: Managed NUT apply transaction and rollback

**Files:**
- Create: `dh_pve_app/app/ups_policy_apply.py`
- Create: `dh_pve_app/tests/test_ups_policy_apply.py`
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/app/ups_shutdown_policy.py`

**Interfaces:**
- `UpsPolicyApplier.apply(draft: UpsPolicyDraft, facts: PolicySafetyFacts) -> PolicyApplyResult`.
- All command execution is injected for tests.
- Managed paths are explicitly whitelisted:
  - `/etc/nut/upsmon.conf`
  - `/etc/nut/upssched.conf`
  - owned policy command script
  - owned directives in `/etc/nut/ups.conf`
  - policy metadata under app state directory.
- Guest startup/down topology is read-only in this implementation.

- [ ] **Step 1: Write failing transaction tests**

Verify generated target semantics:
- `SHUTDOWNCMD` becomes the local system shutdown command only in the target production configuration;
- `POWERDOWNFLAG /etc/killpower` is present;
- `NOTIFYCMD /usr/sbin/upssched` and required ONLINE/ONBATT execution flags are present;
- ONBATT starts a cancellable timer using `on_battery_delay_minutes * 60`;
- ONLINE cancels that timer;
- timer expiry invokes local `upsmon -c fsd` through the owned command script;
- `offdelay` remains at least 60 seconds;
- `ondelay` is the validated draft restore delay;
- low-runtime reserve is set to the validated emergency reserve using the restricted NUT writable-variable path;
- post-write verification must match target values before success is returned.

Rollback tests must inject failure after each mutation stage and prove previous file contents/service state/active policy remain authoritative.

Tests must prove no generated HA path exposes FSD or arbitrary NUT commands.

- [ ] **Step 2: Run RED in CI**

- [ ] **Step 3: Implement atomic backups/writes, bounded commands, service reload/restart, post-read verification, and rollback**

Do not execute this transaction during tests; all host operations use fakes/temp paths.

- [ ] **Step 4: Run GREEN and full suite**

- [ ] **Step 5: Commit**

Commit message: `feat(dh-pve): apply validated UPS shutdown policy`

---

### Task 6: Effective policy payload, documentation, and final verification

**Files:**
- Modify: `dh_pve_app/app/ups_shutdown_policy.py`
- Modify: `dh_pve_app/app/discovery_ups.py`
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`
- Tests: policy/discovery/runtime suites above

**Interfaces:**
- `sensor.dh_pve_ups_shutdown_policy` exposes normalized active semantics plus technical diagnostics:
  - trigger mode
  - on-battery delay seconds
  - emergency reserve seconds
  - hard/recommended reserve seconds
  - irreversible commit behavior
  - guest budget
  - HOSTSYNC/FINALDELAY
  - UPS off/on delays
  - role/monitor/powerdown flag/upssched state
  - `Full power cycle / restart` behavior.

- [ ] **Step 1: Add failing contract assertions for the normalized payload**
- [ ] **Step 2: Implement only missing payload/documentation wiring**
- [ ] **Step 3: Run complete DH PVE suite and repository CI**

Run: `PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q`

Also verify compile, installer shell syntax, and systemd validation through `.github/workflows/validate.yml`.

- [ ] **Step 4: Commit**

Commit message: `docs(dh-pve): document managed UPS shutdown policy`

- [ ] **Step 5: Live commissioning remains a separate explicit step**

After CI is green, deploy the branch to the PVE host, verify MQTT entities and draft-only behavior first, then inspect the exact target diff before the first real Apply Policy press. Do not use `upsmon -c fsd` as a test command and do not simulate a real shutdown until the generated policy has been reviewed live.
