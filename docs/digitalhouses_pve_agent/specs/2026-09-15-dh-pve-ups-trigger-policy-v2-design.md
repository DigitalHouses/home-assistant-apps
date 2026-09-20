# DH PVE UPS Trigger Policy v2 Design

Date: 2026-09-15
Branch: `design/dh-pve-observability-ups-trigger-v2`
Depends on: PR #12 (`fix/dh-pve-nut-command-acl`, head `40f1121b5560a3832569cdfe777055b092c9b1be`)
Recommended order: Runtime Observability first, UPS Trigger Policy v2 second.

## Purpose

Replace the fixed `ONBATT -> upssched START-TIMER -> FSD` policy with a shutdown trigger based on actual battery state and the real shutdown budget of this Proxmox host.

Proxmox/NUT remains the shutdown authority. Home Assistant is configuration and observability only.

## Production trigger rule

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
AND battery.runtime is valid/fresh
AND battery.runtime <= total_shutdown_budget + runtime_safety_reserve

runtime_guard_confirmed = candidate on 2 consecutive UPS polls
```

Native LB is immediate and has no debounce.

The fixed `on_battery_delay_minutes` policy and DigitalHouses ONBATT `upssched` timer are retired.

## Goals

- Native UPS Low Battery remains an independent fail-safe.
- Add an independent runtime guard tied to shutdown budget.
- Remove fixed elapsed-time shutdown from ordinary operation.
- Expose only two trigger settings to the user.
- Draft changes have no host side effects until explicit Apply + confirmation.
- Apply is transactional, read-back verified and rollback-safe.
- The long-running daemon keeps `/etc/nut` read-only.
- Successful Apply survives/requires service restart and publishes a durable old -> new diff.
- `power_restore_delay` stays separate from the trigger editor.
- Preserve PRIMARY/FSD/SECONDARY/POWERDOWNFLAG mechanics.
- No destructive FSD test in the normal release gate.

## Non-goals

- No automatic VM/LXC timeout/order rewrite.
- No NFS/CIFS/SMB dependency detection in this change.
- No generic NUT SET/INSTCMD/shell exposed to HA.
- No HA automation deciding shutdown.
- No claim that host boot timestamps are exact UPS output-off/on timestamps.

## Policy v1 being retired

Current managed behavior:

```text
ONBATT -> upssched START-TIMER dh-pve-ups-shutdown 1800
ONLINE -> CANCEL-TIMER dh-pve-ups-shutdown
helper -> upsmon -c fsd
```

The 1800 seconds comes from the current 30-minute App draft default.

It is retired because fixed time ignores load/runtime and because NUT/upssched 2.8.0 on this installation produced a battery-triggered tight CPU loop during the 2026-09-15 incident.

## Trigger A: native Low Battery

NUT PRIMARY keeps its standard critical `OB + LB` behavior and may commit FSD normally.

`dh_pve_app` does not duplicate that state machine. It only:

- exposes effective Low Battery configuration;
- configures the approved writable threshold when supported;
- verifies read-back;
- records reason/timeline context;
- reports readiness.

If NUT has already committed FSD from LB, the App must not issue a duplicate FSD. Historical reason prefers `native_lb` when LB/FSD evidence exists.

## Trigger B: runtime guard

The App evaluates `battery.runtime` only while OB.

```text
effective_runtime_trigger_seconds =
    total_shutdown_budget_seconds
  + runtime_safety_reserve_seconds
```

Confirmation requires 2 consecutive UPS polls. At the current 5-second poll this is approximately 10 seconds.

Reset pending confirmation on:

- ONLINE before FSD;
- runtime above threshold before confirmation;
- runtime unavailable/stale;
- new App boot.

After App-initiated FSD the decision is latched for the current boot and ONLINE cannot cancel it.

### Runtime invalid/stale

If runtime is missing/invalid/stale:

- runtime guard = `Degraded`;
- no invented runtime;
- no runtime-based FSD;
- native LB remains available;
- diagnostics explain the reason.

Freshness rule for first release: runtime is stale if no successful UPS snapshot containing a valid `battery.runtime` has been received for more than 15 seconds (3 current poll intervals).

## User trigger settings

Only two user-adjustable values belong to `Config UPS trigger`.

### Battery Low threshold

Field:

```text
battery_charge_low_percent
```

For a writable/supported UPS variable such as `battery.charge.low`:

- UI draft range: 10-30%;
- step: 5%;
- initial default for a new v2 policy: current effective UPS value if it is within the range; otherwise no editable default is invented and Apply is blocked until capability handling resolves the value.

The backend validates the same 10-30/5 contract. Write + read-back is mandatory. If the UPS rejects or returns a different unsupported value, Apply fails/rolls back.

Capability behavior:

- writable + readable: editable draft control;
- readable but not writable: effective value read-only;
- unsupported: no fake slider.

Do not enable `ignorelb` to force this behavior. Do not use arbitrary `override.battery.*` as the normal implementation.

### Runtime safety reserve

Field:

```text
runtime_safety_reserve_seconds
```

First-release UI/backend contract:

- minimum: 60 s;
- maximum: 900 s;
- step: 60 s;
- default for a new v2 policy: 180 s.

The old 30-minute ONBATT delay is never mapped to this reserve.

The user does not configure the final runtime threshold directly.

## Shutdown budget model

### Guest budget

Keep the existing conservative Proxmox calculation based on guest shutdown order, per-guest `down` timeout and worker concurrency.

Historical observed times are evidence only and never reduce configured safety budget automatically.

### Total shutdown budget

First-release formula:

```text
total_shutdown_budget_seconds =
    guest_shutdown_budget_seconds
  + hostsync_seconds
  + finaldelay_seconds
  + host_shutdown_reserve_seconds
```

with:

```text
host_shutdown_reserve_seconds = 120
```

The 120-second host reserve is an internal engineering constant for the first release, not a HA setting. It protects the final host/systemd/storage-unmount phase not represented by guest timeouts. It can be tuned in a later release from production evidence, but Policy v2 tests/docs must treat 120 as the current contract.

Do not add UPS `offdelay` to the host OS shutdown budget; it is part of the later UPS output-off sequence.

Example with the current known 280-second guest budget, `HOSTSYNC=15`, `FINALDELAY=5`:

```text
Guest budget         280 s
HOSTSYNC              15 s
FINALDELAY             5 s
Host reserve         120 s
--------------------------
Total budget         420 s  (07:00)
Default reserve      180 s  (03:00)
Runtime trigger      600 s  (10:00)
```

If actual effective HOSTSYNC differs, use the real read-back value.

### Observed shutdown history

Dashboard shows configured and observed facts separately, for example:

```text
VM/LXC budget          04:40
Total shutdown budget  07:00
Last observed          02:11
Worst recent           03:42
```

Timeout/forced/near-timeout history warns the user but does not silently change policy.

## Power restore delay

`power_restore_delay_seconds` is a separate power-return setting and is not part of `Config UPS trigger`.

Current installation:

```text
ups.delay.start = 120 s
driver.parameter.ondelay = 120 s
```

The observed previous shutdown/boot gap is consistent with this value plus normal boot overhead. Policy v2 leaves the existing 120-second restore delay behavior intact.

## Remove DigitalHouses upssched trigger

Policy v2 must no longer require:

- `NOTIFYCMD /usr/sbin/upssched` for DigitalHouses shutdown timing;
- `NOTIFYFLAG ONBATT ... +EXEC` solely for the timer;
- managed `AT ONBATT ... START-TIMER`;
- managed `AT ONLINE ... CANCEL-TIMER`;
- the `dh-pve-ups-shutdown` timer token as production trigger.

Do not remove unrelated administrator NUT/upssched content.

Readiness no longer treats `upssched_inactive` as an error. Presence of the old DigitalHouses timer is instead a `Legacy policy` condition until migration succeeds.

Keep standard NUT:

- PRIMARY role;
- selected `MONITOR` identity;
- `SHUTDOWNCMD`;
- `POWERDOWNFLAG`;
- `HOSTSYNC`;
- `FINALDELAY`;
- FSD mechanics;
- SECONDARY behavior.

## NUT authorization for Low Battery write

PR #12 establishes `dh_primary_user` with `upsmon primary` and `instcmds = ALL`.

If `battery.charge.low` is changed via NUT `SET VAR`, add only the NUT permission required for SET operations to this managed local account. The public MQTT/App surface still allowlists only the approved Low Battery variable.

HA must never gain arbitrary:

- `SET VAR`;
- `INSTCMD`;
- `load.*`;
- `shutdown.*`;
- direct FSD;
- shell execution.

## HA draft/active model

Reuse/migrate existing `UpsRuntime` active/draft/status/revision/hash/last-applied concepts.

State machine:

```text
VIEW
 -> EDIT_DRAFT
 -> CONFIRM
 -> APPLYING
      -> success -> VIEW
      -> failure -> EDIT_DRAFT + error
```

### VIEW

```text
UPS Shutdown Trigger

Low Battery threshold       20 %
VM/LXC budget               04:40
Total shutdown budget       07:00
Safety reserve              03:00
Runtime trigger             10:00
Current battery runtime     87:30
Status                      Ready
Last applied                15.09.2026 09:42

[ Config UPS trigger ]
```

### EDIT_DRAFT

```text
Configure UPS trigger

Low Battery threshold
[ slider ] 20 %

Safety reserve
[ slider ] 3 min

Calculated:
Total shutdown budget       07:00
Runtime trigger             10:00

[ Apply configuration ]
[ Cancel ]
```

Slider movement updates draft only.

`Cancel` does:

```text
draft = active
```

and returns to VIEW.

`Apply configuration` requires an explicit confirmation dialog/card showing final requested + derived values.

## Privileged Apply boundary

Do not grant the long-running MQTT daemon generic write access to `/etc/nut`.

Keep `dh_pve_app.service` hardened and use a dedicated short-lived root oneshot for mutation:

```text
HA confirmed Apply
 -> daemon validates immutable draft
 -> writes typed request under /var/lib/dh_pve_app
 -> starts dh-pve-ups-policy-apply.service
 -> worker validates again
 -> transactional UPS/NUT mutation
 -> read-back verification
 -> committed active policy + diff
 -> restart dh_pve_app.service
 -> post-restart read-back/publish
```

The request is typed data, never arbitrary shell/command text.

The oneshot uses narrow systemd `ReadWritePaths` for only owned NUT/App/state paths.

## Apply transaction

### Pre-write

- immutable draft snapshot;
- selected UPS identity and NUT connectivity;
- stable safe mutation state (normally OL, no running destructive test/shutdown);
- writable variable capability/read-back;
- current effective Low Battery value;
- current guest/total budgets;
- hard-range validation;
- NUT role/config prerequisites;
- managed file/service-state backup;
- old active policy/effective values.

No writes before all pre-write checks pass.

### Mutation

Apply only changed items:

- approved Low Battery writable variable;
- remove DigitalHouses legacy upssched timer linkage/rules;
- update owned NUT directives required by v2;
- update policy metadata;
- restart/reload only components actually requiring it.

`dh_pve_app.service` restart is part of a successful changed-policy transaction so the running daemon reloads the committed configuration and publishes the durable change event. A true no-op Apply must not restart the service or increment revision.

### Verification

Before success:

- read back Low Battery threshold;
- reread effective NUT policy;
- confirm legacy DigitalHouses timer is absent;
- confirm PRIMARY/shutdown invariants;
- verify required services healthy;
- restart App when transaction changed effective policy;
- after restart, reread/publish committed active policy and verify revision/diff are visible.

### Commit

Only after successful verification:

```text
policy_active = target
policy_revision += 1
policy_hash = canonical v2 hash
policy_last_applied = local timestamp
policy_last_change = committed old/new diff
policy_status = Active/Ready
policy_draft = policy_active
```

## Rollback

Pre-write validation failure:

- no mutation;
- active/revision/last-applied unchanged;
- draft stays open for correction.

Mutation/restart/read-back failure:

- restore managed files and previous service state;
- restore previous UPS variable value when it was changed and safe to restore;
- verify rollback where possible;
- previous active remains authoritative;
- revision/last-applied unchanged;
- edit block stays open with sanitized error.

Never publish a partial target as active.

## Durable old -> new change event

A successful config notification must survive the App restart.

Persist committed change metadata and publish it after successful startup/read-back.

Required data:

- `policy_revision`;
- `policy_last_applied`;
- only actually changed fields with `old` and `new`;
- changed derived effective values.

Example:

```json
{
  "revision": 8,
  "applied_at": "2026-09-15T09:52:14+05:00",
  "changes": {
    "battery_charge_low_percent": {"old": 10, "new": 20},
    "runtime_safety_reserve_seconds": {"old": 180, "new": 300},
    "effective_runtime_trigger_seconds": {"old": 600, "new": 720}
  }
}
```

No credentials/config-file text.

HA notification example:

```text
🔋 Конфигурация UPS изменена

Low Battery:
10 % -> 20 %

Safety reserve:
03:00 -> 05:00

Runtime trigger:
10:00 -> 12:00

Revision: 8
```

Failed Apply never emits config-changed.

## Derived budget changes are a different event

If the user changes PVE guest timeout/order and presses UPS Refresh, UPS user settings did not change.

Recalculate budget and effective runtime trigger, then classify separately:

```text
UPS_SHUTDOWN_BUDGET_CHANGED
```

Example:

```text
Shutdown budget:
07:00 -> 08:30

Runtime trigger:
10:00 -> 11:30
```

Do not increment explicit UPS `policy_revision` solely for a derived PVE budget change.

## Manual Refresh

UPS Refresh rereads:

- NUT/UPS effective values;
- Low Battery value/capability;
- guest/total shutdown budget;
- effective runtime trigger;
- readiness/degraded reason.

It may emit a derived budget-change event, but never applies draft values.

## Readiness model

Expose independent status:

```text
Native LB trigger   Ready
Runtime trigger     Ready
Overall policy      Ready
```

Possible runtime states:

- `Ready`;
- `Degraded` (runtime unavailable/stale);
- `Blocked` (budget unavailable);
- `Legacy policy` (old DigitalHouses timer remains);
- `Apply failed`.

Native LB can remain a fail-safe while runtime guard is degraded.

## Runtime decision audit

Use Runtime Observability event vocabulary; INFO logs transitions only.

```text
UPS_TRIGGER ON_BATTERY charge=83 runtime=1920 charge_low=20 budget=420 reserve=180 runtime_trigger=600 policy_revision=8
UPS_TRIGGER RUNTIME_CONFIRM runtime=590 threshold=600 confirm=1/2
UPS_TRIGGER FSD reason=runtime_guard runtime=580 threshold=600 policy_revision=8
```

Native LB example:

```text
UPS_TRIGGER LOW_BATTERY reason=native_lb charge=20 runtime=890 policy_revision=8
```

## Shutdown history integration

Persist with each shutdown incident:

- final FSD reason;
- active low-battery threshold;
- guest/total budget;
- runtime reserve/trigger;
- policy revision;
- outage/FSD/shutdown/next-boot timeline;
- per-guest actual shutdown results;
- clean/unclean host result;
- power restore delay.

Later config changes do not rewrite historical snapshots.

## MQTT / Discovery migration

Retire/tombstone Policy v1 fixed-delay entities/topics.

Policy v2 surface covers at least:

- active Low Battery threshold;
- draft Low Battery threshold when writable;
- active/draft runtime safety reserve;
- guest shutdown budget;
- total shutdown budget;
- effective runtime trigger;
- native/runtime readiness;
- overall policy status;
- policy revision;
- last applied;
- committed last-change diff;
- runtime degraded reason.

Backend safety is authoritative regardless of dashboard visibility.

On first successful v2 Apply/commissioning:

- detect/remove DigitalHouses v1 ONBATT timer;
- preserve unrelated NUT/upssched content;
- tombstone fixed-delay Discovery entities;
- do not map old 30-minute delay to reserve;
- keep restore delay separately;
- preserve PR #12 ACL/credential contract.

Before migration, diagnostics say `Legacy policy`; they do not claim v2 Ready.

## Security

The privileged worker:

- accepts only typed policy fields;
- writes only owned paths/approved UPS variable;
- has no arbitrary MQTT command execution path;
- sanitizes errors/logs;
- rolls back on failure.

Public HA/MQTT capability remains narrower than `dh_primary_user` permissions.

## Testing

Use TDD. Cover at least:

### Domain

- no `on_battery_delay_minutes` in v2;
- Low Battery range exactly 10-30 step 5;
- runtime reserve exactly 60-900 step 60, default 180;
- host reserve exactly 120;
- runtime trigger = total budget + reserve;
- old 30-minute value not migrated into reserve;
- canonical hash excludes secrets.

### Runtime guard

- no runtime FSD while OL;
- one low sample insufficient;
- second consecutive low sample confirms;
- recovery/ONLINE resets before FSD;
- runtime stale after >15 seconds and degrades without FSD;
- native LB independent/immediate;
- no duplicate FSD after NUT commit;
- deterministic final reason.

### Budget

- existing guest budget behavior retained;
- total includes guest + HOSTSYNC + FINALDELAY + 120 exactly once;
- history never reduces configured budget;
- Manual Refresh recalculates guest config changes.

### Apply/UI

- draft slider has no host write;
- Cancel restores active;
- explicit confirmation required;
- immutable draft snapshot;
- success increments revision once and persists old/new diff;
- no-op Apply does not restart/increment/event;
- validation failure leaves active unchanged;
- mutation/read-back/restart failure rolls back and never claims success;
- post-restart publication exposes committed revision/diff.

### NUT migration/security

- DigitalHouses v1 upssched timer removed;
- unrelated NUT/upssched preserved;
- readiness no longer requires upssched;
- lingering v1 timer diagnosed;
- PRIMARY/POWERDOWNFLAG/SHUTDOWNCMD/HOSTSYNC/FINALDELAY preserved;
- SET authorization only as required;
- MQTT cannot issue arbitrary SET/INSTCMD/FSD.

### Discovery/dashboard

- v1 delay entities tombstoned;
- new IDs stable;
- config notification uses committed old/new values;
- budget-change notification is distinct.

## Deployment validation

Non-destructive first release gate:

1. Runtime Observability already deployed;
2. deploy exact v2 feature SHA;
3. verify v1 legacy policy detection before Apply;
4. inspect target config/diff without FSD;
5. Apply v2 while UPS is stable OL;
6. verify Low Battery write/read-back when supported;
7. verify DigitalHouses upssched timer removed;
8. verify NUT driver/server/monitor, PRIMARY identity, POWERDOWNFLAG and command ACLs healthy;
9. verify App restart and post-restart active policy/diff;
10. verify VIEW/EDIT/Cancel/Confirm;
11. verify old -> new config notification;
12. safely change a PVE guest timeout/order, press Refresh, verify separate budget-change event;
13. verify no Recorder storm.

No destructive FSD, load-off or deep discharge test is part of the normal release gate.

## Technical debt out of scope

Track separately:

> Detect PVE NFS/CIFS/SMB storage whose provider is a VM/LXC/NAS participating in the same shutdown sequence. Warn if provider shutdown can make PVE unmount/finalization exceed the calculated shutdown budget.
