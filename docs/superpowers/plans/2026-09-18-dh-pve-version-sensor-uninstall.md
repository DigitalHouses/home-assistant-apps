# DH PVE App Version Sensor and Supported Uninstall Implementation Plan

> **For agentic workers:** execute task-by-task with TDD. Each behavior starts with a failing test, then minimal implementation, then focused GREEN before moving on.

**Goal:** release `dh_pve_app 0.5.1` with a canonical Home Assistant App version sensor on the existing retained PVE diagnostics group and a fail-safe supported uninstall lifecycle that cleans MQTT Discovery before removing local files.

**Architecture:** `VERSION` remains the single release-version source. Resolve it once in the PVE runtime construction path and feed the same value to PVE Device Discovery and the retained diagnostics payload. For uninstall, shell owns service/filesystem orchestration while a new internal Python CLI owns MQTT identity, topic derivation, credentials and cleanup semantics by reusing `load_config()`, `resolve_identity()`, `build_topics()` and `build_ups_topics()`.

**Tech Stack:** Python 3, Paho MQTT, Home Assistant MQTT Device Discovery, Bash, systemd, pytest, repository validators, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-18-dh-pve-version-sensor-uninstall-design.md`

## Global Constraints

- Target release: `0.5.1`.
- Current production/runtime baseline is `0.5.0`; do not change the 0.5.0 machine-event schema or UPS safety boundaries.
- `VERSION` is the only release-version source of truth.
- Version sensor belongs to `DH PVE`, never `DH PVE UPS`.
- Version state is published on retained group `diagnostics` as `app_version`.
- Do not add the version sensor to Recorder.
- Uninstall must tombstone canonical PVE, canonical UPS, all legacy PVE and all legacy UPS Discovery.
- Publish retained canonical PVE and UPS availability `offline` before tombstones.
- Canonical UPS cleanup is unconditional and derived from host identity, not from current UPS selection/runtime availability.
- Default uninstall preserves `/etc/dh_pve_app/` and `/var/lib/dh_pve_app/`.
- `--purge` deletes config/state only after successful MQTT cleanup.
- MQTT cleanup failure aborts local removal; restore the service if it was active before uninstall.
- Never modify `/etc/nut`, NUT services/configuration, UPS output/load, FSD behavior, HAOS, MQTT broker or OS dependencies.
- No destructive UPS/FSD tests.

---

## File / Responsibility Map

### Existing files to modify

- `dh_pve_app/app/main.py` — resolve release value for runtime; add internal uninstall-cleanup CLI path.
- `dh_pve_app/app/app.py` — carry immutable `app_version` into retained PVE diagnostics payload.
- `dh_pve_app/app/discovery_groups.py` — add canonical diagnostic sensor `sensor.dh_app_pve_app_version`.
- `dh_pve_app/app/mqtt_bridge.py` — expose focused cleanup publication primitive(s) without duplicating topic construction.
- `dh_pve_app/install.sh` — install `uninstall.sh` executable.
- `dh_pve_app/examples/dh_app_pve_dashboard.yaml` — show conditional `App <version>` in the first PVE system card.
- `dh_pve_app/tests/test_discovery_groups.py` — version-sensor Discovery contract.
- `dh_pve_app/tests/test_app_adaptive_runtime.py` — retained diagnostics value.
- `dh_pve_app/tests/test_dashboard_contract.py` — dashboard version segment and unavailable/unknown hiding.
- `dh_pve_app/tests/test_installer_contract.py` — installer executable-mode contract.
- `scripts/validators/apps/dh_pve_app.py` — repository contract for version sensor/uninstall safety.
- `dh_pve_app/README.md`, `dh_pve_app/CHANGELOG.md`, `dh_pve_app/VERSION` — release documentation/version.

### New files

- `dh_pve_app/app/uninstall_cleanup.py` — pure/focused MQTT uninstall cleanup orchestration using canonical topic builders.
- `dh_pve_app/uninstall.sh` — root/Proxmox checks, service transaction, cleanup invocation, fail-safe removal/purge.
- `dh_pve_app/tests/test_uninstall_cleanup.py` — fake-MQTT cleanup tests.
- `dh_pve_app/tests/test_uninstall_contract.py` — shell lifecycle/safety contract.

---

## Task 1: App version sensor on retained diagnostics

**Files:**
- Modify: `dh_pve_app/app/app.py`
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/app/discovery_groups.py`
- Modify: `dh_pve_app/tests/test_app_adaptive_runtime.py`
- Modify: `dh_pve_app/tests/test_discovery_groups.py`

### Step 1 — RED: Discovery contract

Add failing assertions that the shutdown-aware PVE Discovery contains exactly one `app_version` component with:

- platform `sensor`;
- `default_entity_id: sensor.dh_app_pve_app_version`;
- diagnostics state topic;
- `value_template: {{ value_json.app_version | default('unknown') }}`;
- `entity_category: diagnostic`;
- `icon: mdi:tag-outline`;
- PVE Device Discovery metadata `device.sw_version == origin.sw_version == version`.

Run:

```bash
PYTHONPATH=dh_pve_app python -m pytest   dh_pve_app/tests/test_discovery_groups.py -q
```

Expected: FAIL because `app_version` component does not exist.

### Step 2 — GREEN: Discovery component

Add `app_version` to `_diagnostic_components()` in `discovery_groups.py`. It must use the existing PVE diagnostics group and inherit the existing PVE device from Device Discovery.

Re-run focused Discovery tests.

### Step 3 — RED: retained diagnostics payload

Extend `test_app_adaptive_runtime.py` so a runtime constructed with `app_version="0.5.1"` must publish:

```python
diagnostics["app_version"] == "0.5.1"
```

Expected: FAIL.

### Step 4 — GREEN: one runtime release value

Add immutable `app_version` to `DhPveRuntime` and `_publish_diagnostics()`.

In `build_runtime()`:

```python
version = _version()
```

Use that same resolved value for:

- `build_shutdown_aware_pve_discovery_payload(..., version=version)`;
- `ProblemAwareRuntime(..., app_version=version)`.

Do not add another hard-coded version constant.

Run:

```bash
PYTHONPATH=dh_pve_app python -m pytest   dh_pve_app/tests/test_discovery_groups.py   dh_pve_app/tests/test_app_adaptive_runtime.py -q
```

### Step 5 — Commit

Commit the version sensor runtime/Discovery slice before dashboard/release work.

---

## Task 2: Dashboard App version presentation

**Files:**
- Modify: `dh_pve_app/examples/dh_app_pve_dashboard.yaml`
- Modify: `dh_pve_app/tests/test_dashboard_contract.py`

### Step 1 — RED

Add static dashboard assertions requiring:

- `sensor.dh_app_pve_app_version` reference;
- first system card includes an `App ` segment;
- template explicitly suppresses `unknown` and `unavailable` for that segment.

Run:

```bash
PYTHONPATH=dh_pve_app python -m pytest   dh_pve_app/tests/test_dashboard_contract.py -q
```

Expected: FAIL.

### Step 2 — GREEN

Update the first host/system card to render:

```text
<manufacturer> <model> · PVE <version> · App <app-version> · <IP>
```

Build the App fragment separately and include it only when the version sensor has a usable state. Do not make dashboard logic a second source of version truth.

Re-run dashboard tests and commit.

---

## Task 3: Python MQTT uninstall cleanup path

**Files:**
- Create: `dh_pve_app/app/uninstall_cleanup.py`
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/app/mqtt_bridge.py`
- Create: `dh_pve_app/tests/test_uninstall_cleanup.py`

### Step 1 — RED: exact cleanup publication set

With a fake MQTT client/config, test that cleanup publishes in order:

1. canonical PVE availability = `offline`, QoS 1, retain true;
2. canonical UPS availability = `offline`, QoS 1, retain true;
3. canonical PVE Discovery tombstone = empty retained payload;
4. canonical UPS Discovery tombstone = empty retained payload;
5. every `Topics.legacy_discoveries` topic tombstoned;
6. every `UpsTopics.legacy_discoveries` topic tombstoned.

Also verify UPS cleanup happens even with no selected UPS state.

Expected: FAIL because no cleanup module/CLI exists.

### Step 2 — GREEN: focused cleanup function

Implement a focused cleanup function that receives config/identity-derived topics plus an MQTT transport, and returns success/failure without touching filesystem/service/NUT.

Prefer a dedicated bridge/client path rather than starting the normal runtime. Reuse normal MQTT credentials, host, port, keepalive, QoS 1 and retained publication semantics.

The function must fail if connect or any required publication fails.

### Step 3 — RED: internal CLI contract

Add tests around a new internal CLI flag, e.g. `--uninstall-mqtt-cleanup`, proving it:

- calls `load_config(args.config)`;
- resolves identity;
- builds both PVE and UPS topics;
- executes cleanup;
- returns 0 only on complete success;
- returns non-zero on cleanup failure;
- does not initialize collectors, UPS runtime, FSD or NUT control.

### Step 4 — GREEN: CLI integration

Add the internal command to `app.main` before normal runtime startup.

No topic literals or credential parsing may be duplicated in shell.

Run focused cleanup/main tests and commit.

---

## Task 4: Fail-safe `uninstall.sh`

**Files:**
- Create: `dh_pve_app/uninstall.sh`
- Create: `dh_pve_app/tests/test_uninstall_contract.py`

### Step 1 — RED: shell contract

Static/isolated shell tests must first fail for the absent script and then assert:

- shebang + `set -euo pipefail`;
- root check and Proxmox check;
- accepted modes are only no argument and `--purge`;
- unknown arguments fail before `systemctl stop`, cleanup invocation or `rm`;
- service active/enabled state is captured before stopping;
- cleanup is invoked through installed venv Python + `-m app.main --uninstall-mqtt-cleanup`;
- app/unit removal occurs only after cleanup command success;
- default flow has no removal of config/state;
- `--purge` removal of config/state is gated after cleanup success;
- cleanup failure restores service when it had been active and exits non-zero;
- script contains no `/etc/nut`, `upsmon -c fsd`, `upscmd`, `load.off`, package-removal, HAOS or broker mutation.

### Step 2 — GREEN: lifecycle transaction

Implement sequence:

1. validate root, PVE and arguments;
2. capture `was_active` / `was_enabled`;
3. stop service if present/active;
4. invoke Python MQTT cleanup while app + venv + config are still intact;
5. on cleanup failure, restart service iff it was active; exit non-zero; remove nothing;
6. on success, disable service if applicable;
7. remove unit and app directory;
8. if `--purge`, print explicit purge message then remove config/state;
9. `systemctl daemon-reload`;
10. `systemctl reset-failed dh_pve_app.service || true`.

Missing enablement/unit must not be fatal. Tombstone cleanup makes repeated cleanup safe.

### Step 3 — GREEN verification

Run:

```bash
bash -n dh_pve_app/uninstall.sh
PYTHONPATH=dh_pve_app python -m pytest   dh_pve_app/tests/test_uninstall_contract.py -q
```

Commit the uninstall shell slice.

---

## Task 5: Installer integration and release documentation

**Files:**
- Modify: `dh_pve_app/install.sh`
- Modify: `dh_pve_app/tests/test_installer_contract.py`
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`
- Modify: `dh_pve_app/VERSION`

### Step 1 — RED: installer mode

Add a failing assertion that installer explicitly executes:

```bash
chmod 0755 "${APP_DIR}/uninstall.sh"
```

### Step 2 — GREEN

Add explicit mode restoration next to the fixed helper executable handling.

### Step 3 — release docs/version

Set `VERSION` to `0.5.1`.

README must document:

- `sensor.dh_app_pve_app_version`;
- dashboard placement;
- normal uninstall preserving config/state;
- `--purge`;
- MQTT cleanup before local deletion;
- abort + service restore semantics;
- NUT and dependency non-ownership.

CHANGELOG 0.5.1 must record version sensor and supported uninstall.

Do not add version sensor to Recorder examples/packages.

Run installer contract tests and commit.

---

## Task 6: Repository validator hardening

**Files:**
- Modify: `scripts/validators/apps/dh_pve_app.py`

Add validator checks for:

- release version `0.5.1`;
- canonical version sensor ID + diagnostics routing;
- installer executable handling for `uninstall.sh`;
- uninstall invokes Python cleanup path;
- no NUT/FSD/output/package-removal destructive strings;
- README documents preserve/purge behavior.

Run the repository validator locally before final CI.

---

## Task 7: Full verification and final review

Run, in order:

```bash
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q
python -m compileall -q dh_pve_app/app
bash -n dh_pve_app/install.sh
bash -n dh_pve_app/uninstall.sh
systemd-analyze verify dh_pve_app/systemd/dh_pve_app.service
python scripts/validate_repo.py
```

Then:

- inspect complete diff from `5d1bb058baffd3edcf4e242a4404e5259d039f0b`;
- verify no accidental 0.5.0 machine-event, UPS cadence, FSD or NUT changes;
- verify no Recorder addition for App version;
- verify cleanup publication order and fail-safe removal boundary;
- push final commits and wait for complete GitHub Actions result;
- inspect failed job logs if any and fix through RED/GREEN.

No production deploy in this task until explicit user approval.
