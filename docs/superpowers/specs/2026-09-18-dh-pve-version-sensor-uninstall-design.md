# DH PVE App Version Sensor and Uninstall Design

Date: 2026-09-18
Status: proposed for 0.5.1
Repository: `DigitalHouses/home-assistant-apps`
App: `dh_pve_app`

## Goal

Add two operational lifecycle capabilities:

1. expose the installed `dh_pve_app` version as a normal Home Assistant entity and show it in the PVE dashboard;
2. provide a supported uninstall path that removes the runtime cleanly without accidentally deleting configuration/state unless explicitly requested.

These changes must not alter UPS shutdown behavior, NUT ownership, collector cadence, notification semantics, or the existing MQTT machine-event contract.

## Current State

`dh_pve_app` already reads its release version from `dh_pve_app/VERSION` through `_version()` and already publishes that value as MQTT Device Discovery `device.sw_version` / `origin.sw_version`.

That makes the version visible in device metadata, but it is not available as a normal HA entity and is therefore inconvenient to display, automate against, or inspect from dashboards.

The repository currently has `dh_pve_app/install.sh` but no corresponding supported uninstall script.

## 1. Home Assistant App Version Sensor

### Entity contract

Add one canonical diagnostic entity:

- entity id: `sensor.dh_app_pve_app_version`
- platform: MQTT sensor
- state: exact installed app version from `VERSION`, for example `0.5.1`
- entity category: `diagnostic`
- icon: `mdi:tag-outline`
- device: existing `DH PVE` device, not the UPS device

The sensor is machine data. It must not contain localized prose.

### Source of truth

`VERSION` remains the single release-version source of truth.

The runtime must use the same `_version()` value already supplied to MQTT Discovery. No independent hard-coded Python version constant may be introduced.

### MQTT publication

The version is added to the existing retained PVE `diagnostics` presentation group:

```json
{
  "app_version": "0.5.1"
}
```

The existing diagnostics payload remains otherwise unchanged.

The Discovery component for `sensor.dh_app_pve_app_version` reads:

```jinja
{{ value_json.app_version | default('unknown') }}
```

This avoids creating a new MQTT topic solely for one static value and reuses the retained diagnostic publication already sent on startup/reconnect.

### Existing Device Discovery metadata

Existing `device.sw_version` and `origin.sw_version` remain present and must continue to match the sensor value.

Tests must assert that one release value is used consistently for:

- `device.sw_version`;
- `origin.sw_version`;
- `sensor.dh_app_pve_app_version` state publication.

### Dashboard

Update the example PVE dashboard so the first host/system card shows the App version alongside current host metadata.

Preferred presentation:

```text
<manufacturer> <model> · PVE <version> · App <app-version> · <primary-ip>
```

If the version entity is unavailable, omit only the `App ...` segment rather than rendering `unknown`/`unavailable` in the card.

The standalone version sensor remains available via More Info / entity lists even though it is also summarized in the main system card.

### Recorder

The version sensor is diagnostic/static metadata and must not be added to the explicit long-term Recorder whitelist.

## 2. Supported Uninstall Lifecycle

### Public interface

Add:

```text
/opt/digitalhouses/dh_pve_app/uninstall.sh
```

Default uninstall:

```bash
/opt/digitalhouses/dh_pve_app/uninstall.sh
```

removes the runtime but preserves user configuration and persistent state.

Full purge:

```bash
/opt/digitalhouses/dh_pve_app/uninstall.sh --purge
```

also removes configuration and persistent state.

No other destructive mode is required.

### Default preserved data

A normal uninstall MUST preserve:

- `/etc/dh_pve_app/`
- `/var/lib/dh_pve_app/`

This allows reinstall/upgrade recovery with the same MQTT identity, UPS selection, history, policy state, and local configuration.

### Purge data

`--purge` additionally removes:

- `/etc/dh_pve_app/`
- `/var/lib/dh_pve_app/`

The script must print an explicit message before deleting these paths.

### What uninstall removes

After successful MQTT cleanup, uninstall removes/disables:

- `dh_pve_app.service` runtime;
- `/etc/systemd/system/dh_pve_app.service`;
- `/opt/digitalhouses/dh_pve_app/`;
- systemd enablement for `dh_pve_app.service`.

It then performs `systemctl daemon-reload` and clears any stale failed-unit state if applicable.

### What uninstall must never remove or modify

Uninstall MUST NOT:

- remove or rewrite NUT configuration under `/etc/nut`;
- stop, disable, uninstall, or reconfigure NUT services;
- issue NUT FSD;
- invoke any UPS output/load command;
- remove Proxmox packages;
- remove shared OS packages installed as dependencies (`git`, `python3`, `smartmontools`, `pciutils`, `dmidecode`, `intel-gpu-tools`, etc.);
- modify HAOS configuration;
- remove the MQTT broker.

## 3. MQTT Cleanup Contract

### Why cleanup is required

Stopping the service publishes retained availability `offline`, but retained MQTT Device Discovery would otherwise keep stale `DH PVE` / `DH PVE UPS` entities registered in Home Assistant.

A supported uninstall therefore owns Discovery cleanup.

### Cleanup scope

Before local files are removed, uninstall must publish retained empty payloads (MQTT tombstones) for:

- current canonical PVE Device Discovery topic;
- current canonical UPS Device Discovery topic when configured/derivable;
- all legacy PVE Discovery topics already known by `Topics.legacy_discoveries`;
- all legacy UPS Discovery topics already known by `UpsTopics.legacy_discoveries`.

It must also publish retained `offline` availability for the canonical PVE and UPS availability topics before Discovery removal.

Diagnostic/state/history topics do not need to be individually deleted. Once Device Discovery is tombstoned they no longer create HA entities, and preserving retained machine state is useful for a non-purge reinstall with the same identity.

### Cleanup implementation boundary

Do not duplicate MQTT topic construction, credentials parsing, or identity rules in shell.

Add an internal Python cleanup command to the existing app CLI, invoked by `uninstall.sh` while the app virtual environment and source are still present. That command must reuse:

- `load_config()`;
- `resolve_identity()`;
- `build_topics()`;
- `build_ups_topics()`;
- existing MQTT configuration/credentials;
- canonical/legacy topic definitions from the app.

The shell script owns lifecycle orchestration; Python owns MQTT semantics.

### Transactional failure behavior

Uninstall is fail-safe by default.

Sequence:

1. validate root / Proxmox environment and arguments;
2. record whether `dh_pve_app.service` was active/enabled;
3. stop the service gracefully;
4. run the internal MQTT uninstall cleanup command;
5. only if cleanup succeeds, disable/remove the unit and application files;
6. preserve config/state unless `--purge` was supplied.

If MQTT cleanup fails:

- do not remove the unit, app directory, config, or state;
- if the service was active before uninstall, restart it;
- exit non-zero with a clear error explaining that local installation was preserved because HA/MQTT cleanup was incomplete.

This prevents a half-uninstalled state where the executable is gone but retained Discovery remains.

### Idempotency

Running uninstall against an already-stopped service or already-cleared Discovery must be safe.

MQTT tombstones are idempotent. Missing unit enablement must not be treated as fatal.

A second uninstall run after partial non-destructive preparation must either complete successfully or report that there is nothing left to remove.

## 4. Installer / Documentation Integration

`install.sh` already copies the complete `dh_pve_app` source tree into `/opt/digitalhouses/dh_pve_app`, so adding repository-root `dh_pve_app/uninstall.sh` naturally installs the script with the app.

`install.sh` must explicitly set executable mode on `uninstall.sh`, just as it currently does for the fixed UPS helper.

README must document:

- where the version appears in HA;
- default uninstall command;
- that default uninstall preserves config/state;
- `--purge` behavior;
- MQTT cleanup/abort behavior;
- that uninstall does not modify NUT or OS dependencies.

CHANGELOG must record both additions under the next release.

## 5. Testing Strategy

Development follows TDD.

### Version sensor tests

Tests must first fail for absence of the new entity/state, then verify:

- Discovery contains exactly one `app_version` sensor with canonical entity id;
- it is attached to the PVE device;
- it is diagnostic category;
- diagnostics retained payload contains the runtime release version;
- Discovery `device.sw_version`, `origin.sw_version`, and sensor value remain consistent;
- dashboard references `sensor.dh_app_pve_app_version` and hides unavailable version text.

### MQTT uninstall cleanup tests

Pure/unit tests with a fake MQTT client must verify:

- canonical PVE availability -> `offline` retained;
- canonical UPS availability -> `offline` retained when applicable;
- canonical PVE Discovery tombstone;
- canonical UPS Discovery tombstone when applicable;
- every legacy Discovery topic is tombstoned;
- QoS/retain semantics match normal app MQTT publication expectations;
- cleanup failure produces a non-zero result.

No test may trigger FSD, battery tests, beeper commands, UPS output commands, or NUT configuration writes.

### Shell uninstall tests

Shell/contract tests must verify:

- `bash -n dh_pve_app/uninstall.sh`;
- unknown arguments fail before destructive actions;
- default mode preserves config/state;
- `--purge` removes config/state only after successful cleanup;
- failed cleanup prevents local removal and requests service restoration when previously active;
- unit/app removal happens only after cleanup success;
- NUT paths/services and dependency package removal commands are absent from the script.

### Full verification

Before release:

- targeted RED -> GREEN tests for each behavior;
- full `dh_pve_app` pytest suite;
- repository contract/validator suite;
- `bash -n` for installer and uninstaller;
- systemd unit verification;
- final diff review;
- non-destructive deployment verification on a test/home PVE.

No destructive UPS/FSD test is required or permitted for this feature.

## 6. Release

Target release: `0.5.1`.

The release must not change the existing 0.5.0 machine-event schema, UPS safety boundaries, or HA notification package contract.

A normal upgrade from 0.5.0 to 0.5.1 should require only the standard installer. The new version sensor appears through MQTT Discovery automatically after restart/reconnect.
