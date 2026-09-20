# DH PVE Technical Debt

This document tracks confirmed implementation debt for `dh_pve_app`.
Items here are follow-up work, not changes to the current production contract.

## TD-001 — Stop unconditional legacy Device Discovery cleanup on every startup

**Status:** Open  
**Observed in production:** 2026-09-17 / 2026-09-18  
**Current production release:** 0.5.1

### Problem

Normal `dh_pve_app` startup still publishes retained tombstones for legacy PVE and
UPS Device Discovery topics even after those legacy devices have already been
removed.

Home Assistant therefore logs warnings such as:

- `No device components to cleanup for dh_pve_<instance_id>`
- `No device components to cleanup for dh_pve_ups_<instance_id>`

The warnings are harmless but repeat on normal App restarts and create
unnecessary log noise.

### Current implementation

- PVE startup cleanup is reached through
  `DhPveRuntime.startup() -> clear_legacy_state() -> clear_legacy_pve_discovery()`.
- UPS startup calls `clear_legacy_ups_discovery()` before
  `ups_runtime.startup()`.
- The legacy tombstones are therefore sent again on every fresh App process
  startup.

### Desired follow-up

Make legacy Discovery cleanup migration-aware / one-shot instead of an
unconditional normal-start operation.

Do not weaken the supported uninstall contract: uninstall MQTT cleanup must
continue to tombstone canonical and legacy PVE/UPS Device Discovery topics
unconditionally before local removal.

### Acceptance criteria

1. A normal restart after migration does not publish redundant legacy Device
   Discovery tombstones.
2. Home Assistant no longer logs `No device components to cleanup` for the
   retired `dh_pve_*` / `dh_pve_ups_*` device identities on each restart.
3. An installation upgrading from a legacy identity still receives the required
   one-time cleanup.
4. Canonical PVE and UPS Discovery/availability behavior is unchanged.
5. Supported uninstall still performs unconditional canonical + legacy
   Discovery cleanup and preserves its existing fail-safe behavior.
6. Regression tests cover both first migration cleanup and subsequent normal
   startup behavior.
