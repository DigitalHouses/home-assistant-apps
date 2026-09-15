# DH PVE UPS Trigger Policy v2 — canonical implementation plan

Date: 2026-09-16
Branch: `design/dh-pve-observability-ups-trigger-v2`
Authority: `docs/superpowers/specs/2026-09-15-dh-pve-simplified-runtime-haos-design.md`

This plan supersedes `2026-09-15-dh-pve-ups-trigger-policy-v2.md` wherever it conflicts with the canonical design. The older plan/spec remain historical implementation input only.

## Frozen behavior

Production shutdown commitment is local to PVE/NUT and is:

```text
software charge guard
OR software runtime-budget guard
OR native UPS/NUT Low Battery emergency
```

Software Trigger A:

```text
OB
AND valid battery.charge
AND battery.charge <= active shutdown_battery_charge_threshold_percent
```

Software Trigger B:

```text
OB
AND valid battery.runtime
AND battery.runtime <= shutdown_budget_seconds + active runtime_reserve_seconds
```

The first satisfied software trigger commits the local shutdown path. There is no two-poll debounce in the canonical contract. Missing/invalid telemetry is omitted, never converted to zero.

Native `LB` is independent. Trigger A/B must not implement themselves by rewriting `battery.charge.low`, `battery.runtime.low`, `ignorelb`, or override directives.

## Policy model

The editable trigger policy contains only:

```text
shutdown_battery_charge_threshold_percent
runtime_reserve_seconds
```

Power-restore delay remains separate from trigger policy.

Initial implementation limits are explicit backend configuration and may be changed only with tests/documentation:

```text
charge threshold: 10..30 %, step 5
runtime reserve:   60..900 s, step 60
new-policy reserve default: 180 s
```

These are implementation bounds, not canonical architectural constants.

## Shutdown budget

Budget is derived, read-only, conservative and evidence-backed:

```text
configured_guest_budget = current effective PVE shutdown ceiling
observed_guest_budget   = comparable clean historical evidence, when available
effective_guest_budget  = max(configured_guest_budget, observed_guest_budget)

host_tail_budget = max(internal fallback floor, comparable observed host tail)

shutdown_budget =
    effective HOSTSYNC budget
  + FINALDELAY
  + effective_guest_budget
  + host_tail_budget

runtime_guard_threshold = shutdown_budget + runtime_reserve
```

History may increase safety budget but never lower the configured guest ceiling. UPS output-off/restart delays are diagnostics and are not added to the pre-handoff shutdown budget.

If a mandatory component is unavailable, Trigger B is unavailable; Trigger A and native LB remain independent.

## Apply transaction

HA controls draft state only. Slider changes never alter active behavior.

Explicit Apply/Confirm performs:

```text
snapshot draft
-> read current facts
-> validate
-> derive budget/threshold
-> backup managed App state
-> atomically persist target active policy
-> controlled dh_pve_app service restart/reload when effective policy changed
-> reread/verify effective policy
-> commit active revision
-> publish synchronized state
-> publish config_changed event LAST with OLD -> NEW
```

Failure restores previous effective App state and revision. A true no-op Apply does not restart, increment revision, or emit config_changed.

No generic NUT SET/INSTCMD/FSD/shell surface is added to MQTT. No `/etc/nut` mutation is required merely to implement Trigger A/B.

## Implementation sequence

1. **Policy domain model**
   - replace v1 timer draft with charge threshold + runtime reserve;
   - backend validation and canonical policy hash;
   - legacy migration never maps `on_battery_delay_minutes` into reserve.

2. **Shutdown-budget engine**
   - preserve current configured guest-budget math;
   - add conservative comparable-history inputs;
   - effective HOSTSYNC only when applicable;
   - host-tail fallback/evidence source;
   - expose component breakdown and unavailable reason.

3. **Pure software trigger evaluator**
   - current valid NUT sample only;
   - OB gate;
   - Trigger A and B independent;
   - first satisfied trigger commits;
   - commitment latched for current boot;
   - ONLINE before commitment simply makes software predicates false.

4. **Runtime integration**
   - evaluate after each successful UPS collection;
   - use active policy only, never draft;
   - local fixed FSD executor only; no MQTT passthrough;
   - distinguish shutdown reasons `charge_guard`, `runtime_guard`, `native_lb`, `manual_or_external_fsd`.

5. **Draft / review / confirm / apply backend**
   - VIEW -> EDIT_DRAFT -> CONFIRM -> APPLYING;
   - atomic App-state transaction and controlled restart;
   - durable old/new metadata and revision;
   - no-op/failure semantics.

6. **Discovery / HA controls**
   - canonical `dh_app_pve_ups_*` numbers/buttons/status;
   - draft-only controls;
   - derived budget/readiness sensors;
   - no generic SET/FSD controls.

7. **Events / HAOS UX**
   - `config_changed` on existing UPS diagnostic Event entity after verification;
   - OLD -> NEW payload;
   - pending block disappears after successful Apply;
   - site notification delivery remains HAOS-owned.

8. **Migration / docs / CI / deploy**
   - remove v1 timer product surface and tombstone legacy Discovery topics;
   - preserve unrelated administrator NUT/upssched content;
   - full CI and diff review;
   - deploy exact reviewed SHA to home PVE;
   - non-destructive validation only.

## Safety gate

Never use ordinary implementation validation to perform:

```text
FSD
upsmon -c fsd
UPS load/output off
mains unplug
deep discharge
HA-side host shutdown
arbitrary shell/upscmd over MQTT
```
