# DH PVE UPS Monitoring Alpha — Design

Date: 2026-09-12
Status: proposed for implementation after review
Target version: `dh_pve_app` 0.2.0-alpha

## Goal

Add read-only UPS monitoring to `dh_pve_app` through an existing local NUT server on Proxmox. The app must expose UPS telemetry to Home Assistant through MQTT Discovery as a separate logical device named `DH UPS`, while preserving the existing `DH PVE` device and all current PVE monitoring behavior.

The alpha exists to validate what the app receives from real NUT installations before shutdown automation is designed.

## Non-goals

This alpha must not:

- configure or install NUT;
- access the UPS over USB directly;
- issue NUT commands that can change UPS state;
- enable `upsmon`, FSD, host shutdown, guest shutdown, battery tests, beeper changes, or outlet control;
- add UPS notifications;
- make Home Assistant part of the safety path;
- require CyberPower-specific behavior.

## Safety model

NUT remains the hardware authority and the sole source of UPS data.

```text
UPS -> USB -> Proxmox -> NUT driver -> upsd
                                  |-> HAOS NUT integration (later)
                                  |-> dh_pve_app UPS reader -> MQTT -> HA
```

For the remote validation site, `nut-monitor` remains disabled and inactive. The app is strictly read-only.

Future shutdown work is a separate phase. It must not be implicitly activated by installing or upgrading `dh_pve_app`.

## Source interface

The alpha reads one NUT UPS through the local NUT client command:

```text
upsc <ups_name>@<host>:<port>
```

Default source:

```text
ups_name = ups
host = 127.0.0.1
port = 3493
```

The collector parses `key: value` output. Unknown variables are retained in normalized raw data for diagnostics but do not automatically become Home Assistant entities.

`upsc` is intentionally the first backend because:

1. NUT remains the only process that talks to UPS hardware.
2. It works across UPS vendors and NUT drivers.
3. It keeps the first implementation small and easy to validate.
4. A future direct NUT TCP client can replace the backend without changing the normalized UPS model or MQTT contract.

## Configuration

Add an optional `[ups]` section to `/etc/dh_pve_app/dh_pve_app.conf`.

Proposed keys:

```ini
[ups]
enabled = true
name = ups
host = 127.0.0.1
port = 3493
poll_interval_seconds = 5
command_timeout_seconds = 3
```

Rules:

- UPS monitoring is opt-in for the alpha.
- Existing configs without `[ups]` remain valid and behave exactly as before.
- No UPS username/password is required for read-only `upsc` queries against a local NUT server.
- Installer does not edit NUT files and does not enable `nut-monitor`.

## Normalized UPS model

The collector produces a vendor-neutral `UpsSnapshot` from whatever NUT variables are available.

Core identity fields:

- manufacturer: `device.mfr` fallback `ups.mfr`
- model: `device.model` fallback `ups.model`
- serial: `device.serial` fallback `ups.serial` when present
- NUT driver name/version/data version

Operational fields, when present:

- raw status tokens from `ups.status`
- line power present
- on battery
- low battery
- replace battery
- bypass
- overload
- charging
- discharging
- battery charge percent
- battery runtime seconds
- battery voltage
- battery nominal voltage
- UPS load percent
- nominal real power watts
- estimated real power watts, calculated by Python only when both load percent and nominal real power are present
- input voltage
- input nominal voltage
- output voltage
- battery warning charge threshold
- battery low charge threshold
- battery low runtime threshold
- UPS test result
- beeper status

The raw NUT status string is preserved exactly. Parsed booleans are derived in Python from NUT status tokens so Home Assistant templates do not have to interpret `OL`, `OB`, `LB`, and combined status strings.

## NUT status semantics

The parser must support multiple simultaneous NUT status tokens. At minimum:

- `OL` -> line power present
- `OB` -> on battery
- `LB` -> low battery
- `RB` -> replace battery
- `OVER` -> overload
- `BYPASS` -> bypass
- `CHRG` -> charging
- `DISCHRG` -> discharging

Unknown tokens are retained in `status_tokens` and do not fail the collector.

No user-facing entity should require knowledge of NUT abbreviations to understand normal operation.

## Derived values

Python may produce normalized/derived facts that make the UI simpler. The alpha allows one derived metric:

```text
estimated_real_power_w = nominal_real_power_w * load_percent / 100
```

This is explicitly labeled as an estimate, not a measured UPS output power value.

No Home Assistant template performs UPS calculations.

## MQTT topology

Keep one running process and one MQTT client connection, but publish two Home Assistant MQTT Discovery devices:

```text
DH PVE
DH UPS
```

Existing `DH PVE` topics remain unchanged.

UPS topics use a separate namespace under the same app instance:

```text
DigitalHouses/Global/dh_pve_app/<instance>/ups/state
DigitalHouses/Global/dh_pve_app/<instance>/ups/availability
homeassistant/device/dh_ups_<instance>/config
```

The UPS device identifiers must be stable across restarts and upgrades.

The `DH UPS` discovery payload references only UPS state/availability topics. A failure of UPS/NUT collection must not make the existing `DH PVE` device unavailable.

## Home Assistant entities for alpha

Create entities only for fields supported by the current UPS.

Always create when UPS support is enabled:

- `sensor.dh_ups_status` — human-readable normalized status, raw NUT status as an attribute;
- `binary_sensor.dh_ups_available` — whether the NUT UPS can currently be read;
- `button.dh_ups_refresh` — manual read/publish request;
- `sensor.dh_ups_last_refresh` — timestamp of the last successful manual UPS refresh.

Conditional entities, created only when the corresponding NUT variable exists:

- `sensor.dh_ups_battery_charge` `%`;
- `sensor.dh_ups_battery_runtime` seconds with duration device class where supported;
- `sensor.dh_ups_battery_voltage` `V`;
- `sensor.dh_ups_load` `%`;
- `sensor.dh_ups_nominal_real_power` `W`;
- `sensor.dh_ups_estimated_real_power` `W`;
- `sensor.dh_ups_input_voltage` `V`;
- `sensor.dh_ups_output_voltage` `V`;
- diagnostic threshold sensors for warning/low charge and low runtime;
- diagnostic test-result sensor when reported;
- diagnostic beeper-status sensor when reported;
- `binary_sensor.dh_ups_on_battery`;
- `binary_sensor.dh_ups_low_battery`;
- `binary_sensor.dh_ups_replace_battery`;
- `binary_sensor.dh_ups_overload`;
- `binary_sensor.dh_ups_bypass`;
- `binary_sensor.dh_ups_charging`;
- `binary_sensor.dh_ups_discharging`.

The device should expose manufacturer/model/serial through MQTT device metadata where available rather than duplicating all identity fields as primary UI sensors.

## Discovery behavior

UPS discovery is capability-driven.

At startup and manual refresh:

1. query NUT;
2. parse the current variable set;
3. build UPS capability inventory;
4. build `DH UPS` discovery payload from that inventory;
5. publish discovery if capabilities changed or if forced by startup/reconnect/manual refresh;
6. publish UPS state.

If a variable disappears temporarily because one read fails, retain the last known capability inventory. Do not delete entities because of a transient NUT error.

If a variable is genuinely absent on a different UPS after installation/reconfiguration, a full capability refresh may remove stale discovery components. Removal behavior must be explicit and tested; it must not depend on a single failed poll.

## Polling and publication policy

Default UPS poll interval: 5 seconds.

Collection and publication are separate concerns:

- read NUT every poll interval;
- publish immediately on discrete state changes such as `OL`/`OB`/`LB`, availability changes, overload, bypass, replace-battery, charging/discharging transitions;
- numeric telemetry uses the existing meaningful-change publication policy where applicable;
- manual refresh forces a read and publish;
- MQTT reconnect republishes UPS discovery and last known UPS state;
- no periodic MQTT state heartbeat is required.

Initial alpha change thresholds should be conservative and version-controlled. At minimum:

- battery charge: publish on >= 1 percentage-point change;
- load: publish on >= 1 percentage-point change;
- voltages: publish on >= 1.0 V change;
- runtime: publish on >= 60 s change, except large/discrete changes caused by power-state transitions which publish immediately;
- estimated power: publish consistently with load changes.

These thresholds are app behavior, not Home Assistant helpers.

## Failure isolation

UPS monitoring is an optional subsystem and must not destabilize PVE monitoring.

Cases:

- `upsc` command missing -> UPS unavailable; PVE continues;
- NUT server unreachable -> UPS unavailable; PVE continues;
- UPS name unknown -> UPS unavailable; PVE continues;
- command timeout -> UPS unavailable; PVE continues;
- malformed one-off field -> ignore that field, retain valid fields;
- total parse failure -> UPS unavailable, retain last valid data for diagnostics but do not present stale data as current availability.

The app log reports failures in Russian and must never expose MQTT passwords.

## Remote-site validation target

The first validation device is the current remote UPS exposed by NUT as:

```text
manufacturer = CPS
model = UT2200E
vendorid = 0764
productid = 0501
driver = usbhid-ups
subdriver = CyberPower HID 0.6
```

Observed variables include:

```text
battery.charge = 100
battery.charge.low = 10
battery.charge.warning = 20
battery.runtime = 2160
battery.runtime.low = 300
battery.voltage = 27.2
battery.voltage.nominal = 24
input.voltage = 221.0
input.voltage.nominal = 230
output.voltage = 221.0
ups.load = 8
ups.realpower.nominal = 1320
ups.status = OL
ups.test.result = No test initiated
ups.beeper.status = enabled
```

`input.transfer.high` and `input.transfer.low` currently report `0`; the alpha must not present zero-valued transfer thresholds as useful operational limits.

Expected initial estimated load for this sample is approximately `105.6 W` (`1320 W * 8%`). It must be labeled estimated.

## Installer and upgrade behavior

For 0.2.0-alpha:

- keep the existing `dh_pve_app.service`;
- install no second daemon;
- ensure the NUT client tool needed by the selected backend is present or fail UPS monitoring clearly without breaking PVE monitoring;
- do not install/configure `nut-server` automatically;
- preserve existing `/etc/dh_pve_app/dh_pve_app.conf` values;
- if `[ups]` is absent, leave UPS disabled unless the user explicitly enables it;
- do not touch `/etc/nut/*`;
- do not start or enable `nut-monitor`.

## Testing

Unit tests must cover:

- parsing the observed CyberPower `upsc` sample;
- parsing multi-token NUT status strings;
- unknown status tokens;
- missing optional variables;
- malformed numeric fields;
- estimated power calculation;
- filtering useless zero transfer thresholds;
- subprocess timeout/error handling;
- capability-driven entity creation;
- UPS unavailable state without PVE failure;
- separate `DH PVE` and `DH UPS` discovery payloads/device identifiers/topics;
- unchanged existing PVE topic contract;
- meaningful-change publication behavior;
- forced startup/manual-refresh/reconnect publication;
- existing config remains valid without `[ups]`;
- safety contract: no shutdown/FSD/NUT control commands in alpha code paths.

Repository CI must remain green for all existing `dh_pve_app` tests.

## Acceptance criteria

The alpha is ready for remote installation when:

1. all existing PVE tests pass unchanged;
2. new UPS tests pass;
3. `dh_pve_app` starts normally with UPS disabled;
4. with UPS enabled against local NUT, Home Assistant receives a separate `DH UPS` MQTT device;
5. the remote CyberPower reports its supported metrics correctly;
6. the PVE device remains healthy if NUT is stopped or unreadable;
7. no code path can trigger UPS shutdown, FSD, host shutdown, guest shutdown, UPS test, beeper control, or outlet control;
8. `nut-monitor` state is outside the app's control.

## Deferred work

After remote telemetry validation and local physical testing:

- LAN NUT client configuration for HAOS/TrueNAS/other guests;
- coordinated shutdown policy;
- FSD behavior and explicit explanation in UI;
- return-of-power/restart behavior;
- UPS notification package;
- battery health/history heuristics;
- self-test scheduling/control, if ever desired;
- UPS dashboard design.
