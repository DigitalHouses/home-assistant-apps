# DH PVE App

`dh_pve_app` is the DigitalHouses native Linux agent for Proxmox VE 8.x. It collects host, CPU, memory, storage, disk/SMART, GPU, fan and VM/LXC state, publishes Home Assistant entities through MQTT Discovery, and can monitor a locally attached UPS through Network UPS Tools (NUT).

`VERSION` remains `0.3.0`; the current branch contains unreleased runtime/UPS architecture work described below.

MQTT base namespace: `DigitalHouses/Global/dh_pve_app/<instance>`.

## Architecture

The App is the source of truth for acquisition, calculations, thresholds, problem state, topology, UPS interpretation and effective policy. Home Assistant is a light client for UI, explicit Recorder history, notifications and user configuration input.

Normal data-source priority on Proxmox VE 8.x is:

1. `/proc` and `/sys`;
2. `/etc/pve` configuration and PVE-maintained cache/status files;
3. a subprocess only when there is no suitable cheap source;
4. `pvesh`/API actions only for rare or on-demand work.

A failed cheap parser/source is reported as unavailable/problem state. The daemon does not fall back permanently to heavy `pvesh`, `qm`, `pct`, `pvesm` or QGA polling loops.

## Fixed collection cadence

Collection cadence is App-owned and does not accelerate because a resource becomes busy:

- `FAST` — 10 s: CPU, temperature/frequency, RAM, Swap, fans;
- `UPS` — 10 s: NUT runtime data;
- `SLOW` — 60 s: storage usage, disk temperature, GPU/transcoding, VM/LXC runtime, host runtime diagnostics and `/etc/pve/.version` check;
- `HEALTH` — 1 h: full SMART/wear and genuinely heavy health diagnostics;
- `STATIC` — startup, Manual Refresh and detected PVE configuration-version changes.

The legacy `[ups] poll_interval_seconds` configuration key is accepted only for upgrade compatibility and is ignored; UPS collection remains fixed at 10 seconds.

Manual Refresh executes the relevant current-state collection immediately. Heavy HEALTH operations remain sequential rather than creating a parallel burst.

## MQTT presentation

Collection and Home Assistant publication are separate concerns. Continuous telemetry is published through independent retained groups rather than one monolithic state object.

The normal publication windows are:

- `NORMAL` — 15 min;
- `DETAIL` — 5 min.

`DETAIL` is selected per domain and only changes MQTT presentation frequency. It never increases collector frequency, SMART frequency, NUT polling cost or command/API depth. Meaningful discrete changes and problem transitions publish immediately.

Canonical Home Assistant entity prefixes are:

- PVE: `dh_app_pve_*`;
- UPS: `dh_app_pve_ups_*`.

Legacy MQTT Discovery identities are removed through retained tombstones during migration so old and canonical entities do not coexist indefinitely.

## Problems and diagnostics

Problem calculation is App-owned. Home Assistant does not scan `states.sensor`, wildcard all entities, rebuild topology or calculate thresholds.

Current problems are exposed as `binary_sensor` entities with `device_class: problem`. Aggregate problem state and compact presentation are separate sensors.

Native MQTT Event entities are used for diagnostic transitions:

- `event.dh_app_pve_diagnostic`;
- `event.dh_app_pve_ups_diagnostic`.

Problem event types are `problem_started`, `problem_recovered` and `problem_updated`. UPS policy changes also use `config_changed` with OLD and NEW values. Runtime Event messages are non-retained and are published after the synchronized metric/threshold/problem/current-state bundle.

## Recorder

Recorder configuration is an explicit whitelist. Continuous history is kept only for useful metrics such as CPU, RAM/Swap, fan RPM, storage usage, disk temperature/wear, GPU telemetry and selected UPS telemetry/status.

Rich presentation, debug diagnostics and MQTT Event entities are intentionally not Recorder history.

## UPS / NUT ownership

Physical ownership is:

```text
UPS -> USB -> Proxmox -> NUT
```

Proxmox/NUT remains the shutdown authority. Home Assistant never decides to shut down Proxmox and does not expose generic shell, arbitrary `upscmd`, `load.*`, UPS output-off or arbitrary FSD controls.

The long-running `dh_pve_app.service` treats `/etc/nut` as read-only. Existing administrator NUT/upssched configuration may be observed for diagnostics, but the former App-managed ONBATT/upssched timer writer and root commissioning CLI are not part of the current product path.

Native UPS/NUT Low Battery behavior remains authoritative. The App does not install `ignorelb` and does not rewrite/synthesize hardware Low Battery thresholds.

## UPS Trigger Policy v2

Software shutdown uses two independent guards joined by OR, plus native NUT Low Battery:

```text
Trigger A: OB and battery.charge <= configured charge threshold
OR
Trigger B: OB and battery.runtime <= shutdown_budget + runtime reserve
OR
native NUT Low Battery emergency path
```

Editable policy values are:

- battery charge shutdown threshold: 10..30 %, step 5;
- runtime reserve: 60..900 s, step 60.

The current default runtime reserve is 180 seconds.

`shutdown_budget` is calculated by the App from current PVE shutdown configuration plus comparable clean shutdown history. The regular Trigger B path uses cheap PVE files/cache; it does not run `qm list`/`pct list` every UPS poll. Budget/configuration fingerprints prevent unrelated historical shutdown samples from being treated as comparable.

Storage backed by a VM/NAS through NFS/CIFS/SMB can extend the final host shutdown if the provider disappears before unmount. That dependency is treated as an explicit shutdown-budget risk and is not hidden by guest-duration history.

## HA policy workflow

The UPS trigger controls are MQTT Discovery configuration entities:

- `number.dh_app_pve_ups_shutdown_battery_charge_threshold`;
- `number.dh_app_pve_ups_shutdown_runtime_reserve`;
- `button.dh_app_pve_ups_apply_trigger_policy`.

Changing a number changes only the draft. It does **not** change the active shutdown policy.

A real Apply is a durable transaction:

1. validate draft;
2. persist a pending target while keeping the previous active policy;
3. request the fixed `dh_pve_app.service` reload;
4. handle `SIGHUP` in the main loop;
5. promote and reread/verify the target policy;
6. publish synchronized current state;
7. publish `config_changed` OLD -> NEW last.

A no-op Apply does not reload the service, increment the policy revision or emit an event. Reload/request/verification failure rolls back to the previous active policy. An interrupted transaction is also recovered conservatively on startup.

The service reload command is fixed internally. MQTT cannot provide a service name or shell command.

## Fixed FSD boundary

When Trigger A or Trigger B commits, the App can only call the installed immutable helper:

```text
/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd dh-pve-ups-shutdown
```

The helper has one fixed action: NUT FSD through `/sbin/upsmon -c fsd`. There is no generic helper argument surface.

A software-trigger shutdown reason is recorded only after the fixed helper returns successfully. Failed helper execution is not latched as a successful shutdown commitment and may be retried on a later valid UPS sample.

## UPS battery tests and beeper

Supported controls are capability-driven:

- Refresh;
- Quick battery test;
- Deep battery test;
- Stop test;
- physical beeper switch when the UPS exposes paired beeper commands.

Quick and Deep schedules are independent. A scheduled test can temporarily set its configured beeper mode; the original physical beeper state is restored after completion, failure or stop. Manual tests use the current beeper state and do not apply a temporary override.

## Read-only preflight

A non-destructive UPS/NUT/PVE safety report is available without MQTT:

```bash
python -m app.main \
  --config /etc/dh_pve_app/dh_pve_app.conf \
  --state-dir /var/lib/dh_pve_app \
  --ups-policy-preflight
```

Preflight checks the selected UPS, NUT services/PRIMARY path, native Low Battery safety, fixed helper ownership/mode and relevant shutdown facts. It does not trigger FSD or modify `/etc/nut`.

## Installation / update

The installer deploys the App code, fixed helper and systemd unit. It preserves existing configuration/state where appropriate and does not silently execute destructive UPS commissioning.

For a reviewed ref/commit:

```bash
REF=<reviewed-ref-or-sha>
bash <(curl -fsSL "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/$REF/dh_pve_app/install.sh")
```

After deployment verify the exact installed version/ref, service state, MQTT availability and read-only preflight before any UPS shutdown commissioning.

## Safety boundary

Routine CI/deploy validation is non-destructive. It must not casually perform:

- live FSD;
- UPS output/load off;
- mains unplug tests;
- deep-discharge testing;
- Home Assistant initiated host shutdown.

Live shutdown commissioning is a separate reviewed gate after code, configuration, runtime budget and topology are validated.
