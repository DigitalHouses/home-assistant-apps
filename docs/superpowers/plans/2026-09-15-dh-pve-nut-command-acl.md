# DH PVE NUT Command ACL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make explicit UPS/NUT commissioning fully own the single `dh_primary_user` identity, including `upsd.users`, synchronized App credentials, transactional rollback, and read-only readiness checks.

**Architecture:** Keep `install.sh` and the long-running daemon unchanged in ownership: installation may occur without UPS hardware and runtime stays read-only for `/etc/nut`. Extend only the explicit root commissioning transaction so it manages `upsd.users`, normalizes the PRIMARY `MONITOR` identity, synchronizes `[ups]` command credentials in the App config, restarts/verifies `nut-server`, and rolls back every managed file/service on failure. Extend preflight to verify the identity/ACL contract without exposing the secret.

**Tech Stack:** Python 3.13, pytest, configparser, NUT 2.8.x, systemd, Proxmox VE 8.4, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-15-dh-pve-nut-command-acl-design.md`

## Global Constraints

- `dh_primary_user` is the only local NUT control identity managed by commissioning.
- Managed user contract: `upsmon primary` plus `instcmds = ALL`.
- `dh_pve_app` uses the same credentials for authenticated `upscmd` calls.
- MQTT/Home Assistant command exposure remains restricted by App allowlists; no arbitrary `upscmd`, FSD, `load.*`, `shutdown.*`, or shell execution is added.
- `install.sh` does not rewrite NUT configuration.
- `dh_pve_app.service` remains read-only with respect to `/etc/nut`.
- No destructive FSD test.
- Secrets never appear in MQTT state, logs, result messages, exceptions, docs examples, or policy hashes.
- All NUT/App config changes made by commissioning participate in one rollback transaction.

---

### Task 1: Define managed NUT identity rendering

**Files:**
- Modify: `dh_pve_app/app/ups_policy_apply.py`
- Modify: `dh_pve_app/tests/test_ups_policy_apply.py`

**Interfaces:**
- Extend `ManagedNutPaths` with `upsd_users: Path` and `app_config: Path`.
- Extend `ManagedPolicyTarget` with rendered `upsd_users_text`, `app_config_text`, and the managed username.
- Add focused render helpers that preserve unrelated users/config while canonicalizing only `dh_primary_user` and selected PRIMARY/App credentials.

- [ ] **Step 1: Write failing renderer tests**

Add tests proving:

```python
assert "[other_user]" in target.upsd_users_text
assert "[dh_primary_user]" in target.upsd_users_text
assert "upsmon primary" in target.upsd_users_text
assert "instcmds = ALL" in target.upsd_users_text
assert "command_username = dh_primary_user" in target.app_config_text
assert "command_password = existing-secret" in target.app_config_text
assert "MONITOR ups@127.0.0.1 1 dh_primary_user existing-secret primary" in target.upsmon_text
```

Also assert that an existing non-empty `dh_primary_user` password is preserved, a missing user can be rendered with a supplied generated secret, unrelated NUT users and unrelated App config sections survive, and duplicate `[dh_primary_user]` sections are rejected.

- [ ] **Step 2: Run RED**

Run:

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ups_policy_apply.py -q
```

Expected: failures for missing paths/target fields/rendering.

- [ ] **Step 3: Implement minimal renderers**

Keep parsing local and explicit. Do not log or interpolate secrets into errors. Preserve unrelated sections. Normalize only the managed user, selected `MONITOR`, and `[ups]` command credentials.

- [ ] **Step 4: Run GREEN**

Run the same focused test file and then:

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q
```

- [ ] **Step 5: Commit**

Commit message: `feat(dh-pve): render managed NUT control identity`

---

### Task 2: Make commissioning transaction own `upsd.users` and App credentials

**Files:**
- Modify: `dh_pve_app/app/ups_policy_apply.py`
- Modify: `dh_pve_app/app/ups_commission.py`
- Modify: `dh_pve_app/tests/test_ups_policy_apply.py`
- Modify/add commissioning tests covering `commission_ups_policy`

**Interfaces:**
- Commissioning supplies or generates one secret for `dh_primary_user`.
- Existing non-empty password in `upsd.users` wins and is preserved.
- Missing password/user uses `secrets.token_urlsafe(...)` through an injectable secret generator for deterministic tests.
- Apply transaction snapshots and writes `upsmon.conf`, `upssched.conf`, `ups.conf`, `upsd.users`, App config, and metadata.
- Restart `nut-server.service` after writing `upsd.users`, before command-path verification.
- Add injected `command_auth_verifier` that verifies the commissioned identity can read the selected UPS command inventory without exposing the secret.

- [ ] **Step 1: Write failing transaction tests**

Cover successful migration, first-time secret generation, restart order (`nut-driver` -> `nut-server` -> auth verification -> restore-delay verification -> `nut-monitor`), and rollback of every managed file when `nut-server` restart or auth verification fails.

- [ ] **Step 2: Run RED**

Run focused commissioning/apply tests and verify failure is specifically due to the missing transaction behavior.

- [ ] **Step 3: Implement commissioning changes**

Use one immutable credential snapshot for the whole transaction. App config remains `0600`; NUT files remain `0640` with inherited `/etc/nut` ownership semantics. Ensure result/error messages never contain the secret.

- [ ] **Step 4: Run GREEN and full DH PVE suite**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q
```

- [ ] **Step 5: Commit**

Commit message: `fix(dh-pve): commission complete NUT control identity`

---

### Task 3: Extend read-only preflight/readiness for command authorization

**Files:**
- Modify: `dh_pve_app/app/ups_policy_preflight.py`
- Modify: `dh_pve_app/tests/test_ups_policy_preflight.py`
- Modify: `dh_pve_app/tests/test_ups_policy_helper_ownership.py` only if fixture paths require the new managed files.

**Interfaces:**
- Read-only checks parse `upsd.users`, `upsmon.conf`/effective policy, and the App config.
- Checks include managed user existence, `upsmon primary`, `instcmds = ALL`, PRIMARY monitor username, App command username, and password consistency without returning the password.
- Missing/mismatched authorization makes `ready=False`.

- [ ] **Step 1: Write failing preflight tests**

Create cases for missing user, wrong role, missing `instcmds = ALL`, wrong App username, password mismatch, and fully consistent READY state. Assert check details never include the test secret.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests/test_ups_policy_preflight.py -q
```

- [ ] **Step 3: Implement read-only identity checks**

Do not execute UPS-mutating commands in preflight. Parse only files/effective read-only state and service status.

- [ ] **Step 4: Run GREEN and full DH PVE suite**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q
```

- [ ] **Step 5: Commit**

Commit message: `feat(dh-pve): verify NUT command identity in preflight`

---

### Task 4: Regression guardrails, docs, CI, and diff review

**Files:**
- Modify: `dh_pve_app/tests/test_ups_beeper_control.py`
- Modify: `dh_pve_app/tests/test_ups_control_policy.py`
- Modify: `dh_pve_app/tests/test_ups_readonly_runtime_architecture.py`
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`

**Interfaces:**
- Runtime allowlists remain unchanged even though NUT grants `instcmds = ALL` to the managed identity.
- Read-only runtime/systemd sandbox contract remains unchanged.
- Documentation defines install -> discover -> explicit commissioning -> READY -> normal operation.

- [ ] **Step 1: Add regression assertions**

Assert dangerous commands are still rejected by App code and no runtime path gains `/etc/nut` write access. Update fixture username expectations from legacy test-only names where necessary to the commissioned `dh_primary_user` contract.

- [ ] **Step 2: Update README/CHANGELOG**

Document the single-user ownership model, `upsd.users` transaction ownership, credential synchronization, explicit recommissioning migration, and the fact that `instcmds = ALL` does not expand the MQTT/HA command surface.

- [ ] **Step 3: Run complete verification**

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q
python -m compileall -q dh_pve_app/app
bash -n dh_pve_app/install.sh
```

Then verify repository GitHub Actions on the branch/PR.

- [ ] **Step 4: Final diff review**

Confirm only commissioning/preflight/docs/tests changed, no installer-driven NUT mutation was added, no secret appears in fixtures/results beyond explicit dummy test values, and no destructive FSD path was introduced.

- [ ] **Step 5: Commit**

Commit message: `docs(dh-pve): document managed NUT control identity`
