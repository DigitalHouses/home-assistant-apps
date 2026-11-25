# DigitalHouses Electrica App

## Target architecture (planned)

See [DigitalHouses Electrica App — target architecture v0.3.0](docs/ELECTRICA_TARGET_ARCHITECTURE.md). The previously published Aqara 0.2.3 release remains unchanged. This branch is development toward Electrica v0.3.0, not a published Electrica release.

## 0.2.x — Ingress configuration

Electrica App consumes events from supported logical keys across MQTT
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
  maintenance semantics. Per-key policies in Ingress:
  `control_relay` (physical; no Actions and no forced relay ON),
  `decoupled` (logical; no forced relay state) and
  `decoupled/ON` (logical with explicitly maintained relay power).
  Unmanaged channels are untouched. A key cannot be made physical while
  retaining assignments, including disabled assignments. Only verified
  Aqara mode capabilities are currently managed; other vendors may be
  adopted as relay-free event-only inputs with declared Z2M actions.
  An aggregate exposed power measurement in W is displayed at device level;
  unknown/unavailable values are shown as a dash, never as per-key power.
- **Storage:** `/data/bindings.json` is the single user-binding source;
  `/data/adopted_switches.json` holds hardware metadata and verified routes.
  First startup creates an empty binding store; old Supervisor YAML is ignored.
  Enter assignments manually in Ingress. Existing JSON bindings are preserved.
  Atomic writes; no destructive repair of an invalid existing file.
- **JSON compatibility:** the public export/import and local binding document
  use the same `{"schema": 1, "rows": [...]}` contract as Aqara v0.2.3.
  All supported action formats and optional per-device settings are retained.
  Missing devices/targets stay configured for recovery; unknown fields,
  unsupported schema versions and duplicate JSON keys are rejected rather
  than silently discarded. No installation or Supervisor-option migration.
- **Dashboard:** standard DigitalHouses product card, problems, last action,
  compact device tree. No Scan button or binding controls. State and assignments
  are published by the App. Reported state is not physical confirmation.
- **DH Sync:** target product ID `digitalhouses_electrica_app`;
  retained QoS 1 /sync on MQTT connect/reconnect;
  `dashboards/ru/electrica.yaml`, stable `path: electrica`. Panel integration is coordinated separately.
  LAB examples are not automatic Packages.

## Installation and upgrade

Install via the DigitalHouses Home Assistant Apps repository. Use the App's
**Open Web UI** / DH Electrica Ingress sidebar to configure bindings.
When upgrading from 0.1.19, old YAML assignments are not imported. Configure
new assignments manually in Ingress; until then, the App sends no button-based
commands and does not enable new Mode Keeper policies. Only system parameters
remain in Supervisor options. Keep a backup if you need the old configuration.

For the planned transition from Aqara v0.2.3 to Electrica v0.3.0:
export JSON from Aqara, stop Aqara and disable its autostart, install Electrica,
import the JSON, verify the bindings and only then remove Aqara. Do not run
both controllers against the same devices. No automatic migration is provided.
This development branch is not yet suitable for production cutover.

The existing telemetry opt-in remains unchanged. HA Core is required to read
entity metadata and execute HA-native targets; verified direct Z2M routes can
operate while HA Core is unavailable as long as MQTT/Z2M/App are working.
No additional service, database, broker or HA Automation is introduced.

## Verification

```sh
PYTHONPATH=digitalhouses_electrica_app/rootfs/app \
python -m unittest discover -s digitalhouses_electrica_app/tests -v
python -m compileall -q digitalhouses_electrica_app/rootfs/app
node --check digitalhouses_electrica_app/rootfs/app/electrica/web/app.js
python scripts/validate_repository.py
```

Historical releases and previous configuration examples are retained in Git
history and the [changelog](CHANGELOG.md). The LAB package remains opt-in under
`examples/packages/`. See [DOCS.md](DOCS.md) for historical engineering notes.
