# DH PVE UPS — Control and Shutdown Policy Design

Date: 2026-09-13
Branch: `feature/dh-pve-ups-scan`

## Scope

Extend the existing `dh_pve_app` UPS module with:

1. capability reporting for the selected UPS;
2. safe battery-test controls exposed through Home Assistant;
3. a read-only view of the effective Proxmox/NUT shutdown configuration;
4. a managed **UPS shutdown policy** abstraction for ordinary users;
5. MQTT draft controls plus an explicit **Apply Policy** action;
6. validation, atomic apply/rollback, and publication of the last successfully applied policy;
7. explicit shutdown invariants for the production NUT/Proxmox shutdown path.

Dashboard layout work remains out of scope until the backend policy contract is complete.

## Existing architecture

- UPS is physically owned by Proxmox through NUT.
- `dh_pve_app` discovers and reads the selected UPS through NUT.
- Home Assistant receives MQTT Discovery entities from `dh_pve_app`.
- Home Assistant never decides whether Proxmox shuts down.
- Proxmox/NUT is the only authority that can commit an emergency shutdown.
- Current commissioning state intentionally has `nut-monitor` disabled and `SHUTDOWNCMD "/bin/true"`.
- The production policy must preserve this commissioning safety until an explicitly validated policy is applied and the final shutdown path is commissioned.

## Product abstraction: shutdown policy, not NUT settings

The Home Assistant UI must not expose NUT implementation details as the primary user model.

The user configures a **shutdown policy**: what the system should do when utility power fails, how long it should continue running, how much battery reserve must remain for a clean shutdown, and how power should return after the shutdown sequence.

Terms such as FSD, LB, HOSTSYNC, POWERDOWNFLAG, `upsmon`, `upssched`, `offdelay`, and `ondelay` are implementation details. They may appear in technical diagnostics but are not user-facing policy controls.

The runtime app translates the validated high-level policy into the required NUT/Proxmox configuration.

## User-adjustable draft policy

Home Assistant exposes writable MQTT `number` entities for a small, bounded policy surface.

Initial controls:

- **Wait after utility loss** — `number.dh_pve_ups_policy_on_battery_delay`
  - semantic value: minutes from confirmed On Battery until shutdown commit;
  - hard range: 5–60 minutes;
  - step: 5 minutes.
- **Emergency battery reserve** — `number.dh_pve_ups_policy_emergency_runtime_reserve`
  - semantic value: minimum remaining runtime required to preserve a clean shutdown window;
  - hard range: 10–30 minutes;
  - step: 1 minute.
- **Power restore delay** — `number.dh_pve_ups_policy_power_restore_delay`
  - semantic value: delay before UPS output is restored after utility returns following a committed full power cycle;
  - hard range: 60–300 seconds;
  - step: 30 seconds.

These values are **draft values only**. Changing a slider must never modify NUT, Proxmox, the UPS, or the active shutdown policy.

The Proxmox guest shutdown budget is not a user slider. It is calculated from the real Proxmox guest topology (`startup order`, per-guest `down`, and worker concurrency) and exposed read-only.

## Draft/active policy model

The app maintains two distinct models:

- **active policy** — the last policy that passed validation, was applied, reread, and verified against the host;
- **draft policy** — the values currently selected in Home Assistant.

The active policy is the source of truth. Home Assistant slider state is not authoritative.

Changing a draft value changes policy status to `Pending changes` but causes no host-side write.

Draft values may be retained/persisted so UI state survives MQTT reconnects, but they must never be interpreted as active unless an Apply transaction succeeds.

## Apply Policy action

Expose:

`button.dh_pve_ups_apply_policy`

When pressed, `dh_pve_app` takes one immutable snapshot of the current draft and runs a complete apply transaction.

The transaction is:

1. snapshot draft values;
2. read current host/NUT/UPS facts required for validation;
3. validate hard ranges and cross-field safety constraints;
4. calculate derived values and the human-readable shutdown timeline;
5. create backups of every managed configuration file that would change;
6. write the complete target configuration using atomic file replacement where applicable;
7. apply/reload only the exact services/drivers required by changed parameters;
8. reread the effective host/NUT/UPS configuration;
9. verify that the effective configuration matches the target policy;
10. persist the new active policy only after successful verification;
11. publish active policy, policy status, result, last-applied timestamp, revision/hash, and synchronized slider states.

No configuration write may occur before all pre-write validation has passed.

## Validation

Validation is authoritative in `dh_pve_app`, not in Home Assistant.

Home Assistant min/max ranges are convenience constraints only.

Validation must include at least:

- all slider values inside hard ranges;
- selected UPS exists and NUT telemetry is available;
- selected UPS advertises the capabilities required for the target power-cycle behavior;
- NUT role and local host topology are compatible with PRIMARY operation;
- required configuration paths/services are present and writable;
- calculated Proxmox guest shutdown worst-case is known;
- emergency runtime reserve is not lower than the calculated hard minimum;
- restore delay is compatible with the UPS/NUT driver requirements;
- generated `upsmon`/`upssched` policy is internally consistent;
- no forbidden load/shutdown command can be reached through the HA control surface.

The minimum emergency reserve is a derived safety value. It must account for the relevant shutdown stages, including NUT synchronization, Proxmox guest shutdown worst-case, final host shutdown reserve, UPS power-off timing, and an explicit safety margin.

The app exposes both:

- `minimum_emergency_runtime_reserve_seconds`;
- `recommended_emergency_runtime_reserve_seconds`.

A draft below the hard minimum must be rejected even if Home Assistant somehow publishes it directly to MQTT.

## Apply failure and rollback

If validation fails before any write:

- active production configuration is untouched;
- policy status becomes `Validation failed`;
- apply result contains a concise user-facing reason;
- all MQTT number states are republished with values from the active policy, reverting the sliders;
- last successful apply timestamp/revision remain unchanged.

If any write, reload, reread, or post-write verification fails:

- restore every modified managed file from its transaction backup;
- restore/reload the previous effective service/driver configuration as required;
- verify rollback where possible;
- keep the previous active policy authoritative;
- policy status becomes `Apply failed`;
- publish a sanitized reason without credentials;
- republish all slider states from the previous active policy.

A partially applied policy must never be published as active.

## Policy MQTT state

Expose at least:

- `button.dh_pve_ups_apply_policy`
- `sensor.dh_pve_ups_policy_status`
  - `Active`
  - `Pending changes`
  - `Validation failed`
  - `Apply failed`
  - `Commissioning`
  - `Unknown`
- `sensor.dh_pve_ups_policy_apply_result`
  - concise user-facing result of the latest Apply attempt;
- `sensor.dh_pve_ups_policy_last_applied`
  - state: ISO-8601 local timestamp of the last **successful** policy application;
  - no timestamp update on failed validation/apply;
  - attributes include `policy_revision` and `policy_hash`.
- `sensor.dh_pve_ups_shutdown_policy`
  - effective active policy plus calculated/technical attributes.

The policy hash is computed from a canonical normalized active-policy representation, never from credentials or arbitrary file contents.

Policy revision is monotonically incremented only after a successful apply transaction.

## Human-readable policy/timeline

The backend publishes enough normalized information for HA to explain the system without interpreting raw NUT directives.

Example meaning:

1. Utility fails; UPS enters battery mode.
2. System continues running for the configured wait period.
3. If utility returns before shutdown commit, the timer is cancelled.
4. If the configured wait expires, or the emergency battery reserve is reached first, the system commits shutdown.
5. After commit, shutdown is irreversible even if utility returns.
6. NUT SECONDARY systems (for example TrueNAS) begin their shutdown.
7. Proxmox gracefully shuts down VM/LXC groups in reverse startup order within the calculated worst-case window.
8. Proxmox host shuts down.
9. NUT performs the final UPS power-off/full-cycle action.
10. UPS output remains off until utility is available and the configured restore delay is satisfied.
11. Firmware `Power On after AC loss` starts Proxmox.
12. Proxmox starts guests according to configured startup order.

The effective policy payload should provide normalized fields including:

- `trigger_mode`;
- `on_battery_delay_seconds`;
- `emergency_runtime_reserve_seconds`;
- `minimum_emergency_runtime_reserve_seconds`;
- `recommended_emergency_runtime_reserve_seconds`;
- `shutdown_commit_behavior` (`Irreversible` when production policy is active);
- `guest_shutdown_budget_seconds`;
- `hostsync_seconds`;
- `finaldelay_seconds`;
- `ups_poweroff_delay_seconds`;
- `ups_restart_delay_seconds`;
- `power_restore_behavior`;
- `role`;
- `nut_monitor`;
- `powerdown_flag`;
- `upssched_active`;
- `upssched_rules`.

Technical raw values remain diagnostic attributes rather than primary user controls.

## Production shutdown trigger

The target production policy uses two paths:

- **normal early trigger:** `ONBATT` starts a cancellable `upssched` timer for `on_battery_delay_seconds`; `ONLINE` cancels it if shutdown has not yet committed;
- **emergency fallback:** Low Battery / insufficient remaining runtime causes immediate shutdown commitment when the safe reserve would otherwise be violated.

Timer expiration invokes the NUT FSD mechanism locally on the PRIMARY host. FSD is the shutdown commitment point.

Once FSD is committed, restoration of utility power must not cancel the sequence.

## NUT/Proxmox shutdown path

Target sequence after shutdown commitment:

1. PRIMARY enters FSD.
2. Connected NUT SECONDARY systems observe FSD and begin shutdown.
3. PRIMARY waits up to `HOSTSYNC` as required by NUT.
4. PRIMARY executes its configured `SHUTDOWNCMD`.
5. Proxmox system shutdown invokes the standard `pve-guests.service` stop path.
6. Proxmox guest groups are shut down in descending `startup order`; guests in the same group run concurrently subject to `maxWorkers`.
7. Individual `startup: ... down=N` values override the node `stopall` fallback timeout.
8. Proxmox host completes shutdown.
9. Debian/NUT `system-shutdown/nutshutdown` checks `upsmon -K`; only a valid NUT powerdown flag allows `upsdrvctl shutdown`.
10. UPS removes output after its configured power-off delay.
11. Following utility restoration, UPS restores output after the configured restart delay.
12. Firmware `Power On after AC loss` and normal Proxmox autostart restore services.

## Current verified host facts (commissioning reference)

These values describe the current development host and are not universal defaults:

- PVE 8.4.6, 4 worker threads when `max_workers` is not explicitly configured;
- running VM QEMU Guest Agents verified for HAOS 110, Plex 501, TrueNAS 700;
- shutdown groups currently configured so their conservative per-group worst-case sum is 280 seconds;
- TrueNAS 700 is a NUT SECONDARY connected to PVE PRIMARY;
- `HOSTSYNC=120`;
- `FINALDELAY=5`;
- current UPS low-runtime value: 600 seconds;
- CyberPower driver effective `offdelay=60`, `ondelay=120`;
- Debian/NUT system shutdown hook is present;
- current commissioning config has no `POWERDOWNFLAG`, `nut-monitor` inactive, `SHUTDOWNCMD "/bin/true"`.

These facts are inputs to validation and commissioning, not values to blindly hard-code for all installations.

## Capability reporting

The app queries NUT instant-command capabilities with read-only discovery equivalent to:

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

Capability reporting remains generic. No UPS-model-specific telemetry correction branches are allowed.

## Battery-test controls

Expose only battery-test actions directly from HA:

- `button.dh_pve_ups_test_quick` → `test.battery.start.quick`
- `button.dh_pve_ups_test_deep` → `test.battery.start.deep`
- `button.dh_pve_ups_test_stop` → `test.battery.stop`

Buttons are capability-driven and exist only when the selected UPS advertises the corresponding command.

Although the UPS may advertise `load.*`, `shutdown.*`, or `beeper.*`, no HA controls for those commands are exposed.

Battery-test command execution must:

- target only the currently selected UPS;
- use a bounded timeout;
- log success/failure in Russian without credentials;
- refresh UPS state after command execution;
- never invoke FSD;
- never issue load or shutdown commands from these battery-test buttons.

## Effective shutdown-policy sensor

`sensor.dh_pve_ups_shutdown_policy` reports effective configuration, not merely one file.

Commissioning should resolve to `Commissioning`; a fully validated active production policy should resolve to `Active`/`Enabled` according to the final state naming used by the implementation.

Technical attributes include at least:

- `role`;
- `nut_monitor`;
- `shutdown_enabled`;
- `shutdown_command`;
- `min_supplies`;
- `pollfreq_seconds`;
- `pollfreqalert_seconds`;
- `deadtime_seconds`;
- `hostsync_seconds`;
- `finaldelay_seconds`;
- `upssched_present`;
- `upssched_rules`;
- `upssched_active`;
- `guest_shutdown_budget_seconds`;
- `power_restore_behavior`;
- policy fields listed in the human-readable policy section above.

Parsers/readers must tolerate missing files, comments, whitespace, absent directives, and commissioning states.

## Managed-write safety boundary

The previous read-only rule for `/etc/nut/*` is superseded only for the explicit **Apply Policy** transaction.

Outside Apply Policy, runtime polling, MQTT reconnect, scan, refresh, and battery-test code remain read-only with respect to NUT/PVE configuration.

Apply Policy may change only an explicit whitelist of policy-owned settings/files. It must not become a generic remote file editor or generic NUT command executor.

The initial whitelist is limited to the settings required for the approved shutdown policy, such as:

- owned directives in `upsmon.conf`;
- owned directives/rules in `upssched.conf`;
- the owned `upssched-cmd` implementation;
- UPS driver delay/low-runtime values required by the active policy;
- policy metadata persisted under the app state directory.

Proxmox guest `startup order/down` topology is read and validated by the policy engine. Automatic rewriting of arbitrary guest topology is not part of the first policy Apply implementation unless explicitly added in a later design revision.

No HA-exposed policy action may directly expose:

- `upsmon -c fsd`;
- `shutdown.return`;
- `shutdown.stayoff`;
- `load.off`;
- arbitrary `upscmd`;
- arbitrary shell commands;
- arbitrary `/etc/nut` text.

## Logging and secrets

- Logs are human-readable and in Russian for operational messages.
- NUT usernames/passwords are never included in MQTT state, discovery, policy hashes, validation errors, or logs.
- Apply/rollback logs identify the policy revision/transaction but not credentials.
- Failed external commands must be sanitized before logging/publishing.

## Testing

Use TDD.

Add tests for at least:

- MQTT Discovery for all policy draft numbers and Apply Policy button;
- hard min/max/step metadata for the draft controls;
- MQTT draft command parsing and rejection of malformed/out-of-range direct payloads;
- draft changes producing `Pending changes` without host writes;
- apply button taking one immutable draft snapshot;
- successful validation/apply/verify publishing `Active` and a new local ISO timestamp;
- successful apply incrementing revision and updating policy hash;
- failed validation leaving active policy and timestamp unchanged;
- failed validation republishing slider values from active policy;
- write/reload/verification failure invoking rollback;
- failed apply republishing active slider values and `Apply failed`;
- policy hash excluding secrets;
- calculated guest shutdown worst-case from representative Proxmox topologies;
- emergency reserve hard-minimum calculation;
- human-readable normalized timeline/policy fields;
- parsing `upscmd -l` output;
- capability grouping and unsupported-command omission;
- correct mapping of quick/deep/stop battery tests;
- command timeout/failure handling without credential leakage;
- shutdown-policy parsing for commissioning and production examples;
- `upssched.conf` with zero/non-zero `AT` rules;
- preservation of existing no-generic-FSD/no-load-command safety tests.

Live commissioning tests remain separate from unit tests. No automated test may intentionally shut down the development PVE host or remove UPS output.
