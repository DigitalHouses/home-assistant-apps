# DigitalHouses Aqara Switch App

## 0.2.0 — Ingress configuration

Aqara Switch App consumes events from supported Aqara logical keys across MQTT
Zigbee2MQTT instances and dispatches explicitly configured light/switch actions.
It is independent of any Home Assistant dashboard.

- **Ingress:** list of discovered devices with compact action-to-target summaries;
  open an individual device to edit its actual actions and per-target operations.
  Light capabilities come from HA; switch targets are optional. Save applies
  without restarting. Disabled and missing assignments remain stored.
- **Scan:** startup after a verified Z2M inventory, periodic via
  `auto_scan_interval` (minutes, default 60, zero disables periodic scans),
  or manual in the Ingress header. Scan does not issue physical writes.
  Newly discovered devices stay disabled until explicitly configured/enabled.
- **Engine:** retain verified direct Z2M MQTT routes for physical lights;
  HA REST for verified native lights and explicitly selected switch targets.
  Protected Aqara input relays are excluded from switch assignments.
  Grouped light toggles retain the shared ON/OFF decision; switch toggles
  are grouped separately. Offline/unverified targets are skipped.
- **Mode Keeper:** preserve existing explicit decoupled/ON policies and
  maintenance semantics. New observed decoupled keys become eligible for
  assignment; saving the assignment explicitly enables the needed policy.
- **Storage:** `/data/bindings.json` is the single user-binding source;
  `/data/adopted_switches.json` holds hardware metadata and verified routes.
  First startup imports legacy Supervisor options, then ignores obsolete YAML.
  Atomic writes; no destructive repair of an invalid existing file.
- **Dashboard:** standard DigitalHouses product card, problems, last action,
  compact device tree. No Scan button or binding controls. State and assignments
  are published by the App. Reported state is not physical confirmation.
- **DH Sync:** unchanged product ID `digitalhouses_aqara_switch_app`;
  retained QoS 1 /sync on MQTT connect/reconnect;
  `dashboards/ru/aqara.yaml`, stable `path: aqara`. No panel edits.
  LAB examples are not automatic Packages.

## Installation and upgrade

Install via the DigitalHouses Home Assistant Apps repository. Use the App's
**Open Web UI** / DH Aqara Switch Ingress sidebar to configure bindings.
Backup existing App data before upgrading from 0.1.19. The migration reads
legacy options from the own Supervisor options/info API before creating the
JSON file. The original legacy option is not an editable field in 0.2.0.

The existing telemetry opt-in remains unchanged. HA Core is required to read
entity metadata and execute HA-native targets; verified direct Z2M routes can
operate while HA Core is unavailable as long as MQTT/Z2M/App are working.
No additional service, database, broker or HA Automation is introduced.

## Verification

```sh
PYTHONPATH=digitalhouses_aqara_switch_app/rootfs/app \
python -m unittest discover -s digitalhouses_aqara_switch_app/tests -v
python -m compileall -q digitalhouses_aqara_switch_app/rootfs/app
node --check digitalhouses_aqara_switch_app/rootfs/app/aqara_switch/web/app.js
python scripts/validate_repository.py
```

Historical releases and previous configuration examples are retained in Git
history and the [changelog](CHANGELOG.md). The LAB package remains opt-in under
`examples/packages/`. See [DOCS.md](DOCS.md) for historical engineering notes.
