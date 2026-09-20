# UPS Runtime Read-Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move NUT policy changes out of the running `dh_pve_app` service and into explicit commissioning while preserving full read-only monitoring.

**Architecture:** The daemon only reads NUT and publishes effective policy state. A root-only CLI commissioning path reuses the existing transactional policy applier. The systemd sandbox enforces the runtime boundary by keeping `/etc/nut` read-only.

**Tech Stack:** Python 3, NUT, systemd, MQTT Discovery, pytest.

**Spec:** `docs/digitalhouses_pve_agent/specs/2026-09-13-ups-runtime-readonly-design.md`

## Global Constraints

- Home Assistant must never initiate Proxmox/NUT shutdown-policy configuration.
- No runtime writes to `/etc/nut`.
- Battery tests and their scheduler remain supported.
- Native UPS Low Battery behavior remains unchanged.
- Existing `policy_apply_enabled` config lines must not break upgrades.

---

### Task 1: Lock the desired architecture with regression tests

**Files:**
- Create: `dh_pve_app/tests/test_ups_readonly_runtime_architecture.py`

- [ ] Add tests proving policy Discovery is read-only, policy MQTT commands are ignored, the service has no `/etc/nut` write exception, legacy `policy_apply_enabled` is ignored, effective delays are parsed from NUT config, and an explicit commissioning CLI exists.
- [ ] Run the DH PVE test suite and confirm the new tests fail for the expected old runtime-Apply behavior.
- [ ] Commit the RED state.

### Task 2: Make runtime policy observation read-only

**Files:**
- Modify: `dh_pve_app/app/ups_shutdown_policy.py`
- Modify: `dh_pve_app/app/discovery_ups.py`
- Modify: `dh_pve_app/app/ups_runtime.py`
- Modify: `dh_pve_app/app/mqtt_bridge.py`
- Modify: `dh_pve_app/app/topics.py`
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/app/config.py`
- Modify: policy/discovery/MQTT/runtime tests that describe the superseded writable contract.

- [ ] Parse ONBATT timer and `ondelay` from the actual NUT files.
- [ ] Publish those values as sensors/attributes with no `command_topic`.
- [ ] Remove policy draft/update/apply queues, events, subscriptions and runtime persistence.
- [ ] Stop constructing a policy applier in `build_ups_runtime`.
- [ ] Ignore legacy `policy_apply_enabled` config keys.
- [ ] Run focused tests, then all DH PVE tests.

### Task 3: Keep explicit commissioning outside the daemon

**Files:**
- Modify: `dh_pve_app/app/ups_policy_apply.py`
- Create: `dh_pve_app/app/ups_commission.py`
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/tests/test_ups_policy_apply.py`
- Add/modify commissioning CLI tests.

- [ ] Add `--ups-policy-commission`, `--on-battery-delay-minutes`, and `--power-restore-delay-seconds` CLI options.
- [ ] Require explicit root/admin invocation and stable `OL` UPS state before applying.
- [ ] Write managed NUT files atomically with `/etc/nut` owner/group and `0640` mode; preserve rollback safety.
- [ ] Verify the effective UPS restore delay before enabling/restarting `nut-monitor`.
- [ ] Run focused tests, then all DH PVE tests.

### Task 4: Enforce the boundary and update examples/docs

**Files:**
- Modify: `dh_pve_app/systemd/dh_pve_app.service`
- Modify: `dh_pve_app/examples/dh_pve_ups_dashboard.yaml`
- Modify: `dh_pve_app/examples/dh_pve_app.conf.example`
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`
- Modify: contract tests as required.

- [ ] Remove `ReadWritePaths=/etc/nut` from the runtime service.
- [ ] Remove Apply/draft controls from the example dashboard and show observed policy values instead.
- [ ] Document commissioning as a rare explicit administrative action.
- [ ] Run `python -m compileall`, installer shell syntax checks, systemd verification, and the full repository CI-equivalent test suite.
- [ ] Commit GREEN state and fast-forward `feature/dh-pve-ups-scan` only after all checks pass.
