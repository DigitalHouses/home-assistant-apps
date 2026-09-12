# DH PVE UPS — Control and Shutdown Design

Date: 2026-09-12
Branch: `feature/dh-pve-ups-scan`

## Scope

Extend the existing `dh_pve_app` UPS module with:

1. a capability sensor describing what the selected UPS actually supports;
2. safe battery-test controls exposed through Home Assistant;
3. a read-only shutdown-policy sensor describing the real Proxmox/NUT shutdown configuration;
4. explicit shutdown invariants for the later production shutdown implementation.

Dashboard work is out of scope for this phase.

## Existing architecture

- UPS is physically owned by Proxmox through NUT.
- `dh_pve_app` discovers and reads the selected UPS through NUT.
- Home Assistant receives MQTT Discovery entities from `dh_pve_app`.
- Home Assistant does not decide whether Proxmox shuts down.
- Current commissioning state intentionally has `nut-monitor` disabled and `SHUTDOWNCMD "/bin/true"`.
- Real FSD/shutdown activation is not part of this change.

## UPS capabilities

The app shall query NUT instant-command capabilities with read-only discovery equivalent to:

`upscmd -l <ups>@<host>:<port>`

The result is normalized into:

`sensor.dh_pve_ups_capabilities`

Primary state:

`<N> commands`

Attributes:

- `commands`: exact supported NUT command names;
- `battery_tests`: supported values among `quick`, `deep`, `stop`;
- `beeper_control`: boolean;
- `load_control`: boolean;
- `shutdown_control`: boolean;
- `supported_features`: short human-readable list.

Capability reporting must remain generic. No UPS-model-specific branches are allowed.

If NUT does not report a command, the related HA control entity is omitted from Discovery.

## Battery-test controls

Expose only battery-test actions in the current UI/API surface:

- `button.dh_pve_ups_test_quick` → `test.battery.start.quick`
- `button.dh_pve_ups_test_deep` → `test.battery.start.deep`
- `button.dh_pve_ups_test_stop` → `test.battery.stop`

Buttons are capability-driven and exist only when the selected UPS advertises the corresponding command.

The app may use a dedicated NUT application account/password. The password is private application configuration and is never published through MQTT or logs.

Although the UPS may advertise `load.*`, `shutdown.*`, or `beeper.*`, no HA controls for those commands are exposed in this phase.

Command execution must:

- target only the currently selected UPS;
- use a bounded timeout;
- log success/failure in Russian without credentials;
- refresh UPS state after command execution;
- never invoke FSD;
- never issue load or shutdown commands from these battery-test buttons.

## Shutdown-policy sensor

Create a read-only sensor:

`sensor.dh_pve_ups_shutdown_policy`

The sensor reports the effective configuration rather than merely echoing one file.

For the current commissioning configuration its state should resolve to:

`Commissioning`

Expected attributes include:

- `role`: `primary` / `secondary` / `unknown`;
- `nut_monitor`: `active` / `inactive`;
- `shutdown_enabled`: boolean derived from effective runtime state;
- `shutdown_command`;
- `minsuppplies`;
- `pollfreq_seconds`;
- `pollfreqalert_seconds`;
- `deadtime_seconds`;
- `hostsync_seconds`;
- `finaldelay_seconds`;
- `upssched_present`: boolean;
- `upssched_rules`: count of active `AT` rules;
- `upssched_active`: boolean;
- `guest_shutdown_budget_seconds`: target Proxmox guest-shutdown budget when configured;
- `power_restore_behavior`: human-readable normalized policy.

The parser is read-only and must tolerate missing files, comments, whitespace, and absent directives.

## Agreed shutdown invariants for the later production phase

These are architectural requirements, not yet executable behavior.

### Guest shutdown budget

Proxmox guests must be allowed up to **300 seconds** for graceful shutdown.

The budget is chosen because HAOS may require approximately 3–4 minutes to terminate cleanly. Faster guests such as TrueNAS may finish earlier; the system must not delay unnecessarily once all guests are stopped.

### No cancellation after shutdown commitment

Once the UPS policy decides to begin emergency shutdown, restoration of utility power must **not** cancel the sequence.

The system continues through:

1. graceful guest shutdown;
2. Proxmox host shutdown;
3. UPS output power removal / full power cycle;
4. UPS output restoration when utility power is available;
5. cold boot through firmware `Power On after AC loss` behavior;
6. normal Proxmox guest startup order.

The purpose is deterministic recovery. A mid-shutdown return of utility power must not leave the host powered off while AC remains continuously present.

### Power restore behavior

Normalized target policy:

`Full power cycle / restart`

The final implementation must use the NUT/UPS shutdown mechanism that guarantees this behavior for the supported UPS. The exact low-level command/driver mechanism is verified during the production-shutdown phase rather than hard-coded into this design.

## Safety boundaries

This phase must not:

- enable `nut-monitor`;
- replace `SHUTDOWNCMD "/bin/true"`;
- execute `upsmon -c fsd`;
- issue `shutdown.return`, `shutdown.stayoff`, `load.off`, or equivalent commands;
- modify `/etc/nut/*` from the runtime app;
- change Proxmox VM/LXC shutdown configuration.

NUT provisioning and real shutdown activation remain a separate installation/commissioning step.

## Testing

Add tests for:

- parsing `upscmd -l` output;
- capability grouping and unsupported-command omission;
- Discovery creation/removal for quick/deep/stop buttons;
- correct mapping from each HA button to exactly one NUT command;
- command timeout/failure handling without credential leakage;
- shutdown-policy parsing for current commissioning config;
- `upssched.conf` with zero and non-zero `AT` rules;
- state classification: commissioning vs enabled/unknown;
- preservation of the existing no-FSD/read-only safety tests.

Runtime transition tests remain required separately for `OL → OB → OB LB → OL`, NUT unavailable/recovery, OVER, RB and BYPASS.
