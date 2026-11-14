# PVE Agent — canonical Home Assistant resource provenance

The active publication rules are defined **only** by
[DH Sync Resources Standard](../../docs/standards/DH_SYNC_RESOURCES_STANDARD.md).
For PVE's exact resources, see [DH Sync resources](DH_SYNC_RESOURCES.md).

**This is a historical record of the working CORE v3 dashboards**, not a
source-admission or manual installation policy. DH Sync 0.4.0+ synchronizes
published YAML automatically. The older manual Apply, fixed Git SHA/version
ranges, dashboard registration changes and confirmation procedures no longer
apply. PVE Agent v0.5.89 remains compatible without a new binary release.

## Accepted CORE v3 baselines (2026-11-14)

| Original CORE view | Original SHA-256 |
| --- | --- |
| `10_pve_proxmox.yaml` | `e41b1f9fe0736f8cf80f31e58214d3e1483200b091f4d8dee086e02e8966626d` |
| `11_pve_ups.yaml` | `5aef50ab9e4d5db307e1c66a2924a20f38638a77ebd70d06311aa697fd082f96` |

The published source views preserve the original bodies except for
informational headers, icon-only navigation and the approved UPS icon
change. The product regression tests reverse those differences and verify
the original hashes. The original FAN% graph, FAN labels, dynamic VM/LXC
collections, Recorder entities, UPS/NUT cards and controls are preserved.

## Published files and runtime dependencies

The published RU views are
`dashboards/ru/10_pve_proxmox.yaml` (`path: dh_pve_agent`) and
`dashboards/ru/11_pve_ups.yaml` (`path: dh_pve_agent_ups`).
The published non-localized package is
`packages/common/dh_pve_agent_package.yaml` with stable top-level key
`dh_pve_agent_package`.

The views use the existing Home Assistant frontend resources:
`auto-entities`, `button-card`, `entity-progress-card-template`,
`mini-graph-card`, Mushroom cards and `phu:proxmox`. DH Sync does not
automatically install those frontend dependencies. It never updates agent
binaries, restarts HA, edits `.storage` or removes previously synchronized
resources when they disappear from GitHub.

Notification variants stay local under `examples/` until a portable
Russian package is reviewed. GitHub publication of resources is independent
of the PVE Agent binary `VERSION`; YAML-only changes must not create a
new Agent release.
