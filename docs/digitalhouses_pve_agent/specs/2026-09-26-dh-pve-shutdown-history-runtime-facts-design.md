# DH PVE shutdown history and guest runtime facts

Date: 2026-09-26  
Status: implemented design amendment  
Target: `dh_pve_app`

## Principle

Home Assistant is a presentation client. `dh_pve_app` owns shutdown acquisition,
history, calculations and derived status. Lovelace must not reconstruct historical
budgets from the current configuration or calculate shutdown durations from several
raw attributes.

## PVE shutdown history

Each completed PVE boot/shutdown cycle keeps the facts that belonged to that cycle.

Canonical presentation status:

```text
shutdown_status = correct | incorrect | unknown
```

The legacy/raw `shutdown_clean` boolean is retained for compatibility and parser
evidence. User-facing presentation should use `shutdown_status`.

A history record may contain:

```text
shutdown_class
shutdown_reason
shutdown_status
shutdown_at
actual_shutdown_seconds
actual_guest_shutdown_seconds

planned_shutdown_seconds
planned_guest_shutdown_seconds
planned_all_guest_shutdown_seconds
running_guests
shutdown_sequence
shutdown_budget_fingerprint
```

Historical planned values are snapshots. They are never reconstructed later from
the current configuration, so changing VM/LXC timeouts must not turn an old history
row into "plan changed".

## Current shutdown plan

The operational shutdown budget uses only guests that are actually running in the
current PVE runtime cache.

Separately, the App calculates
`all_configured_guest_budget_seconds` from all configured non-template VM/LXC,
including guests that are currently stopped. This is diagnostic data and does not
inflate the active UPS shutdown budget.

`shutdown_sequence` is App-calculated from the same running guest set and current
shutdown order. It is published as ordered groups. A group with more than one ID
represents guests in the same shutdown-order group; presentation may render it
compactly rather than recreating the Proxmox UI.

## Guest facts

The normal VM/LXC status entity also exposes `onboot`. Presentation may render:

```text
🚀 = onboot true
✋ = onboot false
```

No separate autostart entity is required.

Per-guest last shutdown facts are independent from PVE shutdown history. The App
reconstructs completed guest shutdown operations from the current boot journal and
updates them after a running/paused -> stopped transition. This allows a single
`qm shutdown <id>` or `pct shutdown <id>` to update the guest's factual shutdown
duration without rebooting PVE.

A standalone guest shutdown does not create a PVE shutdown-history entry.

## Publication contract

The App publishes already calculated values. HA may format seconds, dates, labels
and emoji, but must not:

- rebuild historical plan from current timeout/order;
- sum raw timeout values to invent a budget;
- derive correct/incorrect from several unrelated entities;
- infer shutdown order from the entity registry.

The App remains the authority for shutdown facts and calculations.
