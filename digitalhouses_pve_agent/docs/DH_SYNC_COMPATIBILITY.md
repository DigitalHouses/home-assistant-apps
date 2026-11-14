# DH PVE Agent → DH Sync v1: canonical YAML contract

Status: product-team candidate. This change **does not deploy** to HAOS, install
DH Sync, update Linux Agent, or grant permission for automatic adoption.

## Product identity and MQTT detection

- Canonical product ID: `digitalhouses_pve_agent`, registry type `agent`
  (`digitalhouses-stats/digitalhouses_stats/product_registry.json`).
- Product-level MQTT availability:
  `DigitalHouses/Global/digitalhouses_pve_agent/<instance_id>/availability`.
  The existing PVE `build_topics` derives `instance_id` from host identity;
  **do not** assume one universal fixed instance suffix.
- The agent publishes retained `online` with QoS 1 after connecting.
  Existing Last Will publishes retained `offline` with QoS 1. UPS subsystem
  availability `.../<instance_id>/ups/availability` is **not** an agent
  installation or uninstall signal.
- Existing retained MQTT Discovery topic:
  `homeassistant/device/dh_pve_agent_<instance_id>/config`, preserving the
  existing device identifiers, `unique_id` and entity IDs.
- Existing release diagnostic: `sensor.dh_pve_agent_version`; existing
  process timestamp: `sensor.dh_pve_agent_started`. Both are defined by the
  established PVE MQTT Discovery contract.
- Offline, MQTT reconnect and UPS-not-configured **never** mean uninstall.
  DH Sync should retain the last known product and both managed views.
  A removal of DH Sync-managed files needs an explicitly confirmed uninstall,
  with backup. No new MQTT heartbeat or identity protocol is introduced here.

## Canonical views (RU only)

| File, relative to `digitalhouses_pve_agent/` | Revision | View path | Navigation |
| --- | --- | --- | --- |
| `dashboards/ru/10_pve_proxmox.yaml` | `DH-View-Version: 1.0.0` | `dh_pve_agent` | `mdi:server`, icon-only |
| `dashboards/ru/11_pve_ups.yaml` | `DH-View-Version: 1.0.0` | `dh_pve_agent_ups` | `mdi:power-plug-battery`, icon-only |

- `DH-View: dh_pve_agent`; `DH-View-Date: 2026-11-14`.
- `DH-Compatible-Agent: >=0.5.88,<0.5.89` is deliberately narrow:
  CORE Linux Agent v0.5.88 was confirmed active and MQTT CONNECTED via
  `dh-pve-agent status` on 2026-11-14. The existing CORE v3 views were
  operator-confirmed to work with this agent. This is **not** proof that DH
  Sync's new update/rollback mechanism has passed live acceptance.
- HA view revisions are independent of the Linux Agent binary release.
  Do **not** release a new Agent version for navigation-only YAML changes.
- English UI has **not** been verified or translated; no placeholder EN files
  are supplied. Existing `examples/` remain in place for legacy users but
  **are not** the approved v3 source.
- No `packages/` have been changed here. The existing PVE Recorder, global
  helpers and localized notifications need a separate product-led audit
  before they can be made canonical; do not silently co-install a second
  Recorder package.

## Provenance — exact working CORE v3 source

The original **read-only** snapshots were retrieved on 2026-11-14 from
CORE HA VM2242, `/mnt/data/supervisor/homeassistant/dashboards/dh/views/`.
Their SHA-256 values were independently checked in the guest:

- `10_pve_proxmox.yaml`:
  `e41b1f9fe0736f8cf80f31e58214d3e1483200b091f4d8dee086e02e8966626d`
- `11_pve_ups.yaml`:
  `5aef50ab9e4d5db307e1c66a2924a20f38638a77ebd70d06311aa697fd082f96`

Only approved differences from those working CORE files:

1. Add DH Sync **comment** metadata headers.
2. In both views, `show_icon_and_title: true` → `false` to show the icon,
   not the text, in the DigitalHouses tab bar; preserve each view's `title`.
3. In the UPS view only, use `mdi:power-plug-battery` instead of
   `mdi:power-plug-battery-outline`.

The original Proxmox graph's simple `auto-entities` FAN % filter and
FAN 1/FAN 3 presentation, dynamic VM/LXC/disks, entity IDs, section order,
actions, Jinja, Recorder contract and UPS/NUT protection remain **byte-for-byte
the same otherwise**. Product tests reverse these approved changes and
validate the exact baseline SHA-256 to prevent accidentally publishing the
older, broken v2 graph.

HACS/frontend dependencies found in the actual views:
`auto-entities`, `button-card`, `entity-progress-card-template`,
`mini-graph-card`, Mushroom cards (`template`, `entity`, `number`,
`chips`, `title`) and `phu:proxmox` icon support. DH Sync may warn about
missing frontend resources, but must not silently install HACS dependencies.

## Safe adoption and in-place update on CORE HA

Existing dashboard registration is owned by the central DigitalHouses panel:

```yaml
title: DigitalHouses
views: !include_dir_list views/
```

Existing live files (do **not** change them in this PR):

- `/config/dashboards/dh/views/10_pve_proxmox.yaml`
- `/config/dashboards/dh/views/11_pve_ups.yaml`

1. DH Sync must pin the **immutable merged Git commit SHA containing these
   YAML assets**, independently of the Linux Agent v0.5.88 release tag.
   Never install unreviewed branch `main` by default.
2. Preflight: confirm registered `digital-houses` YAML dashboard and
   `!include_dir_list views/`, matching two paths, no duplicate views,
   installed compatible Agent version, required frontend dependencies,
   and compare each existing view to the known v3 baseline ignoring only
   header comments and the three explicitly approved navigation differences.
   If locally customized or unknown: display diff, **stop**, ask operator.
3. Do **not** register a new sidebar, overwrite `ui.yaml`, edit `.storage`,
   change either view `path`, rename files, or create duplicates.
4. On explicit approval, snapshot exact bytes, owner/mode and SHA-256 of the
   existing two files. Stage two new YAML files, validate syntax and selected
   content/paths, and replace **only** the two corresponding paths in place.
   Do not touch unrelated cards/packages or alter local users' files.
5. Validate Home Assistant config and dashboard loading, then have the
   operator verify icon-only Proxmox/UPS tabs and the graph + UPS controls.
   If validation fails, restore the exact backups and verify their hashes.
   Preserve the backup/journal until acceptance. Do not auto-restart HA.
6. Retain both tabs on agent `offline` or UPS not configured. Uninstall
   requires an explicit user action and removes only DH Sync-managed assets.

No end-to-end CORE HA deployment, live icon rendering, adoption rollback or
cross-HA regression has been run in this product PR. Those are acceptance
gates for the **DH Sync** implementation, not permissions to edit CORE now.

## Validation

```bash
PYTHONPATH=digitalhouses_pve_agent python -m pytest digitalhouses_pve_agent/tests/test_dh_sync_canonical_resources.py -q
python scripts/validate_repository.py
```

The product regression tests assert metadata, YAML parsing, unique existing
paths, icon-only navigation, exact v3 body hashes, FAN graph markers and
absence of fake EN files. Existing agent/executable code, MQTT, Recorder and
UPS/NUT protection files are intentionally untouched.
