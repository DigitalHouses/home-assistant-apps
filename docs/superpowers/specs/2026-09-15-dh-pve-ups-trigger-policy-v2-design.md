# DH PVE UPS Trigger Policy v2 Design

Date: 2026-09-15
Branch: `design/dh-pve-observability-ups-trigger-v2`
Depends on: PR #12 (`fix/dh-pve-nut-command-acl`, head `40f1121b5560a3832569cdfe777055b092c9b1be`)
Recommended implementation order: Runtime Observability first, UPS Trigger Policy v2 second.

## Purpose

Replace the current fixed `ONBATT -> upssched START-TIMER -> FSD` policy with a shutdown trigger model based on actual battery state and the time required to shut this Proxmox host down safely.

The new policy must preserve Proxmox/NUT as the shutdown authority, keep Home Assistant as a configuration/observability surface, and remove the failure mode where a fixed wall-clock timer is unrelated to UPS load/runtime.

## Design summary

The production shutdown commitment rule is:

```text
FSD if:
    native_low_battery
OR
    runtime_guard_confirmed
```

where:

```text
native_low_battery = UPS/NUT reports OB + LB

runtime_guard_candidate =
    UPS is On Battery
AND battery.runtime is valid and fresh
AND battery.runtime <= total_shutdown_budget + runtime_safety_reserve

runtime_guard_confirmed = candidate observed on 2 consecutive UPS polls
```

Native Low Battery is immediate and has no debounce.

The fixed `on_battery_delay_minutes` control and DigitalHouses `upssched` ONBATT timer are removed from the production policy.

## Goals

- Use the UPS native Low Battery state as an independent fail-safe trigger.
- Add a second independent runtime-based trigger tied to the actual shutdown budget of the current PVE host.
- Remove fixed elapsed-time shutdown from ordinary operation.
- Keep the policy surface small: only values a user should meaningfully configure.
- Keep draft edits harmless until an explicit Apply + confirmation.
- Apply configuration transactionally with read-back and rollback.
- Preserve the long-running daemon's read-only protection for `/etc/nut`.
- Emit durable configuration-change information with old and new values after a successful service restart.
- Keep `power_restore_delay` separate from the shutdown-trigger UI.
- Preserve current NUT PRIMARY/FSD/POWERDOWNFLAG shutdown mechanics.
- Avoid destructive FSD validation during development/release.

## Non-goals

- No automatic rewriting of VM/LXC shutdown order or timeouts.
- No automatic NFS/CIFS/SMB dependency detection in this change.
- No generic NUT SET/INSTCMD shell exposed to Home Assistant.
- No Home Assistant automation that decides when PVE must shut down.
- No attempt to infer exact physical UPS output-off duration from host boot timestamps.
- No replacement for NUT's standard FSD/PRIMARY/SECONDARY shutdown sequence.

## Current policy being retired

The current managed policy includes:

```text
ONBATT -> upssched START-TIMER dh-pve-ups-shutdown 1800
ONLINE -> CANCEL-TIMER dh-pve-ups-shutdown
helper -> upsmon -c fsd
```

The 1800-second value ultimately comes from the App policy draft default of 30 minutes.

This is being retired for two reasons:

1. fixed elapsed time does not reflect UPS load or remaining runtime;
2. the installed NUT/upssched version exhibited a battery-triggered CPU tight loop during the 2026-09-15 incident, making the timer path operationally unsafe on this target system.

The standard NUT native Low Battery path remains authoritative and is not replaced.

## Trigger architecture

### Path A: native Low Battery

The UPS reports battery state through NUT. When the PRIMARY sees the UPS in critical `OB + LB`, the normal NUT behavior may commit FSD.

`dh_pve_app` does not reimplement this path.

Responsibilities of the App:

- expose the configured/effective Low Battery threshold when supported;
- optionally configure the writable UPS variable approved by policy;
- verify read-back;
- record decision/timeline context;
- report whether the native LB path is ready.

No debounce is applied to native LB.

If native LB and the App runtime guard become true at nearly the same time, the incident reason should prefer `native_lb` when the UPS/NUT evidence already shows LB/FSD, avoiding a misleading duplicate cause.

### Path B: runtime guard

The App observes `battery.runtime` while the UPS is On Battery.

Derived threshold:

```text
effective_runtime_trigger_seconds =
    total_shutdown_budget_seconds
  + runtime_safety_reserve_seconds
```

Candidate condition:

```text
on_battery
AND runtime_valid
AND runtime_fresh
AND battery.runtime <= effective_runtime_trigger_seconds
```

Confirmation:

- require 2 consecutive UPS collector polls meeting the condition;
- with the current default 5-second UPS poll this is approximately 10 seconds;
- the confirmation count is an internal safety rule, not a Home Assistant setting.

Reset confirmation when:

- utility returns before FSD;
- runtime rises above the threshold before confirmation;
- runtime becomes unavailable/stale;
- a new application boot starts.

Once the App commits FSD, that shutdown decision is latched for the current boot and cannot be cancelled by later `ONLINE` state.

### Runtime invalid/stale behavior

If `battery.runtime` is missing, invalid, or stale:

- runtime guard state becomes `Degraded`;
- the App must not invent a runtime value;
- native Low Battery protection remains available;
- HA diagnostics must state why runtime protection is degraded;
- no FSD is committed solely because runtime telemetry disappeared.

## User-configurable trigger policy

The trigger UI exposes only two user-configurable values.

### 1. Battery Low threshold

Semantic name:

```text
battery_charge_low_percent
```

This corresponds to the UPS/NUT writable low-charge variable when the selected UPS/driver exposes a supported writable control, currently expected as `battery.charge.low` on the CyberPower installation.

The UI must be capability-driven:

- if the variable is writable and supported, expose an editable draft control;
- if it is readable but not writable, show the effective value read-only;
- if unsupported, do not invent a control.

The exact allowed range/step must come from the approved App policy for the supported device capability and must be validated again server-side. The initial product range may be 10-30%, but implementation must not assume every UPS accepts every integer in that range without characterization/read-back.

Apply requires:

1. write only the approved variable;
2. read it back through NUT;
3. verify the effective value matches the requested policy;
4. fail/rollback if the UPS rejects, rounds unexpectedly outside the accepted contract, or loses the value during required restart verification.

Do not enable `ignorelb` merely to force this value. Do not use arbitrary `override.battery.*` as the normal implementation.

### 2. Runtime safety reserve

Semantic name:

```text
runtime_safety_reserve_seconds
```

This is additional runtime beyond the calculated total shutdown budget.

The user does not configure the final runtime threshold directly.

The UI shows the derived value:

```text
Runtime trigger = Total shutdown budget + Safety reserve
```

Hard min/max/step are App policy and must be validated server-side. The design intentionally leaves the exact first-release range to implementation tuning from the known PVE shutdown budget and desired product UX; it must be expressed in tests and Discovery metadata once chosen.

## Shutdown budget model

The current code calculates a `guest_shutdown_budget_seconds` from Proxmox VM/LXC topology using shutdown order, per-guest `down` timeout, and worker concurrency.

Policy v2 separates guest budget from total shutdown budget.

### Guest shutdown budget

Keep the existing conservative calculation based on configured Proxmox behavior.

Actual historical shutdown duration is diagnostic evidence and must not automatically reduce the configured safety budget.

### Total shutdown budget

The runtime guard must use a broader value representing the time needed after FSD for the host to shut down safely.

Initial model:

```text
total_shutdown_budget_seconds =
    guest_shutdown_budget_seconds
  + hostsync_seconds
  + finaldelay_seconds
  + host_shutdown_reserve_seconds
```

`host_shutdown_reserve_seconds` is an explicit engineering allowance for the host/systemd final shutdown path after guests stop. It is App policy, not a user slider.

The exact initial reserve must be selected during implementation from the observed shutdown history and conservative safety needs, then locked by tests/docs.

Do not add UPS `offdelay` to the host OS shutdown budget merely because it exists. It describes the UPS output-off sequence after host shutdown and is a separate power-cycle stage.

### Observed history

The HA dashboard should show both configured budget and observed history, for example:

```text
Configured VM/LXC budget   04:40
Total shutdown budget      07:45
Last observed shutdown     02:11
Worst recent observed      03:42
```

Observed history may warn about suspicious VM/LXC behavior (`timeout`, `forced`, `near_timeout`) but does not silently rewrite the trigger threshold.

## Power restore delay

`power_restore_delay_seconds` remains a separate power-return policy setting.

It is not part of the `Config UPS trigger` block because it answers a different question: how the UPS output returns after a completed shutdown/power cycle.

Current observed/configured installation value:

```text
ups.delay.start = 120 s
driver.parameter.ondelay = 120 s
```

A previous shutdown showed an offline-to-next-boot gap consistent with approximately this delay plus boot overhead; therefore there is no current evidence requiring the value to be changed as part of Trigger Policy v2.

The existing commissioning/read-back behavior for restore delay is preserved unless separately redesigned.

## NUT configuration changes

### Remove DigitalHouses upssched timer dependency

The production managed policy must no longer require:

- `NOTIFYCMD /usr/sbin/upssched` for the DigitalHouses trigger;
- `NOTIFYFLAG ONBATT ... +EXEC` solely to launch the timer;
- managed `AT ONBATT ... START-TIMER` rule;
- managed `AT ONLINE ... CANCEL-TIMER` rule;
- `dh-pve-ups-shutdown` timer token as a production trigger.

The system package/file may remain present. The migration owns only the DigitalHouses-managed rules and configuration it previously installed.

Policy readiness must no longer report `upssched_inactive` as a fault simply because Policy v2 intentionally does not use upssched.

Legacy DigitalHouses ONBATT timer presence should instead be reported as a migration/legacy-policy issue until removed by a successful apply/commissioning transaction.

### Preserve standard upsmon shutdown path

Keep:

- PRIMARY role;
- selected `MONITOR` identity;
- `SHUTDOWNCMD`;
- `POWERDOWNFLAG`;
- `HOSTSYNC`;
- `FINALDELAY`;
- normal NUT FSD mechanics;
- SECONDARY behavior.

### NUT authorization for writable UPS variable

PR #12 establishes one `dh_primary_user` identity with `upsmon primary` and `instcmds = ALL`.

If the implementation uses NUT `SET VAR` for `battery.charge.low`, the managed account must receive only the additional NUT permission required for SET operations, while the App still restricts its public command surface to an explicit allowlist.

Home Assistant must never gain:

- arbitrary `SET VAR`;
- arbitrary `INSTCMD`;
- `load.*`;
- `shutdown.*`;
- direct FSD command;
- shell execution.

## HA draft/active state model

Reuse the existing `UpsRuntime` concepts of active policy, draft policy, status, revision, hash, and last-applied time, but migrate their fields to Policy v2.

State machine:

```text
VIEW
  -> EDIT_DRAFT
  -> CONFIRM
  -> APPLYING
       -> success -> VIEW
       -> failure -> EDIT_DRAFT + error
```

### VIEW block

Example:

```text
UPS Shutdown Trigger

Low Battery threshold       20 %
VM/LXC budget               04:40
Total shutdown budget       07:45
Safety reserve              03:00
Runtime trigger             10:45
Current battery runtime     87:30
Status                      Ready
Last applied                15.09.2026 09:42

[ Config UPS trigger ]
```

### EDIT_DRAFT block

Example:

```text
Configure UPS trigger

Low Battery threshold
[------ slider ------] 20 %

Safety reserve
[------ slider ------] 3 min

Calculated:
Total shutdown budget       07:45
Runtime trigger             10:45

[ Apply configuration ]
[ Cancel ]
```

Moving draft controls must have no host/NUT/UPS side effects.

`Cancel` restores draft from the current active policy and returns to VIEW.

### Confirmation

`Apply configuration` must require an explicit confirmation step that shows the final requested values and important derived values before the transaction begins.

No configuration write occurs when merely entering edit mode or moving a draft control.

## Apply execution boundary

Do not grant the long-running MQTT daemon generic write access to `/etc/nut`.

Preserve `dh_pve_app.service` hardening (`ProtectSystem=full` or stricter equivalent).

Use a short-lived privileged apply path for host mutation.

Recommended architecture:

```text
HA confirmed Apply
  -> dh_pve_app validates draft and creates one immutable request
  -> root-owned request/state under /var/lib/dh_pve_app
  -> dedicated dh-pve-ups-policy-apply.service oneshot
  -> validate again under mutation authority
  -> transactional NUT/UPS update
  -> verify/read-back
  -> persist committed active policy + diff
  -> restart dh_pve_app.service if required
```

The exact trigger from daemon to oneshot must be narrow and deterministic; it must not become arbitrary root command execution.

The oneshot service should use systemd sandboxing and narrow `ReadWritePaths` for only the files/state it owns.

## Apply transaction

A successful Apply is one atomic logical transaction.

### Pre-write phase

- snapshot immutable draft;
- verify selected UPS identity;
- verify NUT connectivity;
- verify UPS is in a safe state for policy mutation (normally stable line power, not in an active destructive battery test/shutdown sequence);
- read supported/writable variables;
- read current effective `battery.charge.low`;
- calculate current guest and total shutdown budgets;
- validate runtime reserve and all hard ranges;
- validate NUT role/config prerequisites;
- snapshot all managed files/service states required for rollback;
- capture old active policy and effective values.

No write before this phase succeeds.

### Mutation phase

Apply only changed values.

Possible actions:

- update approved UPS writable Low Battery variable;
- remove/replace DigitalHouses legacy upssched timer policy;
- update managed NUT directives required by Policy v2;
- update policy metadata;
- restart/reload only components actually requiring it.

Do not restart services merely because Apply was pressed if no changed setting requires restart.

### Verification phase

- read back UPS low-battery setting;
- reread effective NUT shutdown policy;
- confirm no legacy DigitalHouses timer remains active;
- confirm PRIMARY/shutdown invariants;
- confirm effective calculated policy equals target;
- verify required services are healthy;
- if `dh_pve_app.service` must restart, treat successful post-restart read-back as part of completion.

### Commit phase

Only after successful verification:

```text
policy_active = target
policy_revision += 1
policy_hash = hash(canonical active policy)
policy_last_applied = local timestamp
policy_last_change = committed old/new diff
policy_status = Active/Ready
```

Draft is synchronized to active after success.

## Rollback

If validation fails before writes:

- no host state changes;
- active policy/revision/last-applied unchanged;
- draft remains available for correction;
- status shows validation failure.

If a write/restart/read-back/verification stage fails:

- restore managed files and prior service state;
- restore previous supported UPS variable value when it was changed and can be safely restored;
- verify rollback where possible;
- keep previous active policy authoritative;
- revision and last-applied remain unchanged;
- edit block remains open with a sanitized error.

Never publish a partially applied target as active.

## Durable configuration-change event

A configuration change notification must survive the App restart that completes Apply.

Do not rely only on a transient MQTT event.

Persist committed change metadata before/through restart and publish it after successful startup/read-back.

Required public fields:

- `policy_revision`;
- `policy_last_applied`;
- committed `changes` map containing old/new values;
- effective derived values changed by the transaction.

Example:

```json
{
  "revision": 8,
  "applied_at": "2026-09-15T09:52:14+05:00",
  "changes": {
    "battery_charge_low_percent": {"old": 10, "new": 20},
    "runtime_safety_reserve_seconds": {"old": 180, "new": 300},
    "effective_runtime_trigger_seconds": {"old": 645, "new": 765}
  }
}
```

Only actually changed fields belong in the user-facing diff.

Credentials and arbitrary config text are forbidden.

## Notifications

Home Assistant notification wording is built from the committed diff, not from assumptions about prior entity state.

Example:

```text
🔋 Конфигурация UPS изменена

Low Battery:
10 % -> 20 %

Safety reserve:
03:00 -> 05:00

Runtime trigger:
10:45 -> 12:45

Revision: 8
```

A failed apply must not emit `UPS_CONFIG_CHANGED`.

Failures use a separate result/event state such as `UPS_CONFIG_APPLY_FAILED` if notifications are desired.

### Shutdown budget changed without UPS config Apply

If the user changes VM/LXC shutdown configuration in Proxmox and then presses UPS Manual Refresh, the App recalculates the budget.

If the budget/effective runtime threshold changes while UPS user-configured values remain the same, this is not an UPS config apply.

Expose a separate change classification/event:

```text
UPS_SHUTDOWN_BUDGET_CHANGED
```

Example notification:

```text
Shutdown budget:
04:35 -> 06:10

Runtime trigger:
07:35 -> 09:10
```

Do not increment the UPS user-policy revision solely because PVE topology/config changed, unless implementation defines a distinct derived-policy revision. The simple first design keeps `policy_revision` for explicit successful Apply transactions and represents derived budget changes separately.

## Manual Refresh behavior

UPS Manual Refresh already rereads auxiliary policy/facts.

Policy v2 uses this path to:

- reread NUT/UPS effective values;
- recalculate guest/total shutdown budget;
- update effective runtime trigger;
- detect derived budget changes;
- refresh readiness/degraded diagnostics.

Manual Refresh does not apply draft values.

## Readiness model

Expose independent trigger health rather than one opaque Ready bit.

Example normalized state:

```text
Native LB trigger     Ready
Runtime trigger       Ready
Overall policy        Ready
```

Possible runtime states include:

- `Ready`;
- `Degraded` — runtime unavailable/stale;
- `Blocked` — shutdown budget cannot be calculated;
- `Legacy policy` — old DigitalHouses upssched timer still installed;
- `Apply failed`.

Native LB readiness considers NUT/UPS LB telemetry and configured threshold capability.

Overall Ready requires all mandatory production invariants; native LB may remain a fail-safe even when runtime guard is degraded.

## UPS runtime decision audit

Use the logging contract defined by Runtime Observability.

At INFO, transitions only.

Example On Battery:

```text
UPS_TRIGGER ON_BATTERY charge=83 runtime=1920 charge_low=20 budget=465 reserve=180 runtime_trigger=645 policy_revision=8
```

Runtime candidate:

```text
UPS_TRIGGER RUNTIME_CONFIRM runtime=632 threshold=645 confirm=1/2
```

FSD:

```text
UPS_TRIGGER FSD reason=runtime_guard runtime=625 threshold=645 policy_revision=8
```

Native LB:

```text
UPS_TRIGGER LOW_BATTERY reason=native_lb charge=20 runtime=890 policy_revision=8
```

Do not emit the same INFO decision line every 5 seconds.

## Shutdown history integration

When an FSD incident occurs, store the policy snapshot and timeline fields specified in the Runtime Observability design.

The historical record must answer:

- why FSD was committed;
- what Low Battery threshold was active;
- what shutdown budget and reserve were active;
- what runtime threshold was active;
- when outage/FSD/shutdown/next boot occurred;
- how each VM/LXC actually shut down;
- whether host shutdown was clean.

Policy changes after reboot must not rewrite the historical incident snapshot.

## MQTT / Discovery changes

Retire/tombstone obsolete Policy v1 entities/topics tied to fixed ONBATT delay.

New/updated entities should cover at least:

- active Low Battery threshold;
- draft Low Battery threshold when writable;
- active runtime safety reserve;
- draft runtime safety reserve;
- guest shutdown budget;
- total shutdown budget;
- effective runtime trigger;
- policy/readiness status;
- policy revision;
- last applied timestamp;
- committed last-change diff in attributes/state group appropriate for notifications;
- runtime trigger health/reason when degraded.

The dashboard may use card visibility to implement VIEW vs EDIT mode, but the backend contract must enforce draft/apply safety independently of UI visibility.

## Migration

Policy v2 migration must be explicit and testable.

On first successful Apply/commissioning under v2:

- detect Policy v1 DigitalHouses ONBATT timer;
- remove its managed `upssched` trigger rules/config linkage;
- preserve unrelated administrator NUT configuration;
- retire/tombstone fixed ONBATT delay Discovery entities;
- migrate persisted active/draft policy state only where semantics are still valid;
- do not convert the old 30-minute delay into any new reserve value automatically;
- retain `power_restore_delay_seconds` as a separate existing setting;
- preserve PR #12 credential/ACL contract.

Before migration is applied, diagnostics should clearly show legacy fixed-timer policy rather than silently claiming Policy v2 is active.

## Security boundary

The long-running daemon remains primarily read-only with respect to host configuration.

The privileged apply worker:

- accepts only a typed validated request;
- supports only approved policy fields;
- writes only owned NUT/App paths and approved NUT writable variables;
- never exposes arbitrary command text from MQTT;
- sanitizes errors/logs;
- rolls back on failure.

The public HA/MQTT control surface remains narrower than the permissions held by the local administrative NUT user.

## Testing

Use TDD.

Tests must cover at least:

### Policy/domain

- Policy v2 has no `on_battery_delay_minutes` field;
- derived runtime trigger = total budget + reserve;
- Low Battery capability/read-only/writable cases;
- validation rejects unsupported/out-of-range values;
- old 30-minute value is not silently mapped to reserve;
- policy hash excludes credentials and uses canonical v2 fields.

### Runtime guard

- no runtime FSD while OL;
- candidate starts on OB when runtime <= threshold;
- one low runtime sample is insufficient;
- second consecutive low sample confirms guard;
- candidate resets if runtime recovers;
- candidate resets on ONLINE before FSD;
- unavailable/stale runtime degrades guard without FSD;
- native LB path remains independent;
- no duplicate FSD attempt after NUT already committed FSD;
- final incident reason selection is deterministic.

### Budget

- guest budget calculation remains correct for shutdown order/max_workers/timeouts;
- total budget includes approved host/NUT components exactly once;
- history does not reduce configured budget;
- Manual Refresh recalculates changed topology/config.

### Apply/UI contract

- draft slider updates do not write host/NUT/UPS state;
- Cancel restores draft from active;
- Apply requires explicit request/confirmation path;
- immutable draft snapshot used for apply;
- successful apply increments revision exactly once;
- successful apply stores old/new diff;
- no-op apply does not fake a change event;
- failed validation does not mutate active state;
- mutation failure rolls back;
- read-back mismatch rolls back;
- restart failure/failed post-restart verification does not claim success;
- successful post-restart publication exposes committed revision/diff;
- failed apply emits no config-changed notification state.

### NUT migration

- legacy DigitalHouses `upssched` timer is removed;
- unrelated upssched/NUT content is preserved;
- readiness no longer requires `upssched_active`;
- lingering legacy timer is diagnosed;
- PRIMARY/POWERDOWNFLAG/SHUTDOWNCMD/HOSTSYNC/FINALDELAY invariants preserved;
- SET authorization added only if required by supported low-battery write path;
- MQTT cannot issue arbitrary SET/INSTCMD/FSD.

### Discovery/dashboard

- old ONBATT delay entities receive tombstones;
- new active/draft/derived entities have stable IDs;
- editor visibility cannot bypass backend safety;
- notification template receives old/new committed values;
- budget-change notification is distinct from config-change notification.

## Deployment validation

Perform only non-destructive production validation initially.

1. deploy exact feature SHA after Runtime Observability is already present;
2. verify legacy Policy v1 is detected before migration;
3. inspect generated target NUT config/diff without FSD;
4. apply Policy v2 while UPS is stable OL;
5. verify low-battery write/read-back if supported;
6. verify managed upssched timer is removed and no upssched process appears during ordinary OL operation;
7. verify `nut-monitor`, NUT server/driver, PRIMARY identity, POWERDOWNFLAG, and command ACLs remain healthy;
8. verify App restart and post-restart active policy/read-back;
9. verify HA VIEW/EDIT/Cancel/Confirm behavior;
10. verify successful configuration notification uses old -> new values;
11. change a safe PVE shutdown timeout/order, press UPS Refresh, and verify derived budget/runtime threshold refresh without calling it an UPS config Apply;
12. verify no Recorder storm from policy diagnostics.

Do not perform destructive FSD, UPS load-off, or deep discharge testing as part of the normal release gate.

A future controlled power-fail exercise may validate the full runtime guard end-to-end only with explicit user approval.

## Technical debt explicitly out of scope

Track separately:

> Automatically detect PVE NFS/CIFS/SMB storage whose provider is a VM/LXC/NAS participating in the same shutdown sequence. Warn if provider shutdown can make PVE unmount/finalization exceed the calculated shutdown budget.

This dependency analysis is important, but it must not expand the first Policy v2 implementation.