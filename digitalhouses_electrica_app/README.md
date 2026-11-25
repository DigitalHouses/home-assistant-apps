# DigitalHouses Aqara Switch App

## Target architecture (planned)

See [DigitalHouses Electrica App — target architecture v0.3.0](docs/ELECTRICA_TARGET_ARCHITECTURE.md). The current Aqara 0.2.x release remains unchanged.

## 0.2.x — Ingress configuration

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
  First startup creates an empty binding store; old Supervisor YAML is ignored.
  Enter assignments manually in Ingress. Existing JSON bindings are preserved.
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
When upgrading from 0.1.19, old YAML assignments are not imported. Configure
new assignments manually in Ingress; until then, the App sends no button-based
commands and does not enable new Mode Keeper policies. Only system parameters
remain in Supervisor options. Keep a backup if you need the old configuration.

The existing telemetry opt-in remains unchanged. HA Core is required to read
entity metadata and execute HA-native targets; verified direct Z2M routes can
operate while HA Core is unavailable as long as MQTT/Z2M/App are working.
No additional service, database, broker or HA Automation is introduced.

## Verification

```sh
PYTHONPATH=digitalhouses_electrica_app/rootfs/app \
python -m unittest discover -s digitalhouses_electrica_app/tests -v
python -m compileall -q digitalhouses_electrica_app/rootfs/app
node --check digitalhouses_electrica_app/rootfs/app/aqara_switch/web/app.js
python scripts/validate_repository.py
```

Historical releases and previous configuration examples are retained in Git
history and the [changelog](CHANGELOG.md). The LAB package remains opt-in under
`examples/packages/`. See [DOCS.md](DOCS.md) for historical engineering notes.
