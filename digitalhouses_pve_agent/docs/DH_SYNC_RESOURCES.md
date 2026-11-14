# DigitalHouses PVE Agent — DH Sync resources

**Normative standard:** [DH Sync Resources Standard](../../docs/standards/DH_SYNC_RESOURCES_STANDARD.md).
**Consumer:** DigitalHouses Sync App 0.4.0 or newer, automatic synchronization.

## Published resources

Only these three files under the product directory are published for DH Sync:

| Source in `digitalhouses_pve_agent/` | Identity | Content |
| --- | --- | --- |
| `dashboards/ru/10_pve_proxmox.yaml` | Lovelace `path: dh_pve_agent` | CORE v3 Proxmox view, icon-only navigation, FAN RPM/% graphs |
| `dashboards/ru/11_pve_ups.yaml` | Lovelace `path: dh_pve_agent_ups` | CORE v3 UPS view, icon-only navigation |
| `packages/common/dh_pve_agent_package.yaml` | Top-level `dh_pve_agent_package:` | Recorder, Logbook, UPS policy editor helpers |

The views are standalone Lovelace views, not a complete `ui.yaml` or
`lovelace:` dashboard. Each view `path` is unique. The common package
keeps its existing stable top-level key, HA entity IDs, script IDs and
automation IDs.

**Nothing under `examples/` is published by DH Sync.** The older sample
dashboards and notification examples remain for reference only. No unverified
English resources or empty placeholder YAML are published.

## Russian notification variants — intentionally local

There is currently **no** file under `packages/locales/ru/`.

The two existing notification examples use the same top-level key,
`dh_pve_agent_notification_local_package`, but different delivery: portable
`persistent_notification.create` versus site-dependent
`script.write2admins`. Publishing one of those examples would automatically
replace existing local packages sharing that key, potentially altering
notification delivery on houses with custom scripts. Therefore neither is
canonical yet. Both stay in `examples/`; publication requires a separate
product-level migration and review of the chosen portable behavior.

Do not publish site-specific delivery, `notify.*`, IPs, passwords or
house names as a canonical notification package. If a portable Russian
notification package is approved later, its unique top-level key and
automation IDs must be explicitly checked for collisions before publication.

## Discovery and automatic sync

The **existing** PVE Agent v0.5.89 publishes retained QoS 1 metadata on
`DigitalHouses/Global/digitalhouses_pve_agent/<instance_id>/sync` every
successful MQTT connect/reconnect. Its payload declares the canonical GitHub
repository and product path. No change to the Agent executable or MQTT
protocol is needed for the new resources standard.

After discovery and hourly, DH Sync reads the public DigitalHouses Git
repository's default-branch snapshot and automatically synchronizes
published RU views and common packages. It resolves existing local views by
Lovelace `path`, packages by top-level YAML key, **preserves their existing
filenames/locations**, backs up replacements, and skips ambiguous duplicates
or Storage collisions. No manual Apply or version-range gate is used.

New views: `/config/dashboards/dh/views/`.
New packages: `/config/packages/dh/`.
Existing packages: remain in their original location under `/config/packages/`.

GitHub YAML changes can propagate **after merge** without further approval;
review the canonical resources before merging. Removing a source file does
not delete an already-installed HA resource. DH Sync never edits `.storage`,
agent binaries or local MQTT credentials, and does not restart Home Assistant.
A changed package may require a normal HA restart to take effect.

Agent releases remain independent of YAML revisions: do not bump the Linux
Agent `VERSION` to publish dashboards or packages.

## Verification

Run:

```bash
PYTHONPATH=digitalhouses_pve_agent python -m pytest digitalhouses_pve_agent/tests -q
python scripts/validate_repository.py
```

`test_dh_sync_resources_standard.py` guards published view paths and
package keys and verifies that incompatible local notification variants
remain outside the auto-synced directories. The previously accepted CORE v3
view bodies remain protected by `test_dh_sync_canonical_resources.py`.
