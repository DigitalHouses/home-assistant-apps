# DigitalHouses Electrica App

## Target architecture (planned)

See [DigitalHouses Electrica App — target architecture v0.3.0](docs/ELECTRICA_TARGET_ARCHITECTURE.md). The previously published Aqara 0.2.3 release remains unchanged. This branch is development toward Electrica v0.3.0, not a published Electrica release.

## 0.2.x — Ingress configuration

Electrica App consumes events from supported logical keys across MQTT
Zigbee2MQTT instances and dispatches explicitly configured light/switch/cover/climate/media_player actions.
It is independent of any Home Assistant dashboard.

- **Ingress:** list of discovered devices with compact action-to-target summaries;
  the entire device row opens the editor. Display Z2M friendly name followed
  by the distinct HA device name (user-assigned name first), refreshed on Scan.
  Names are display metadata, never binding keys.
  Every bound target in the device list displays the full domain-qualified
  entity_id followed by its distinct HA friendly name, for all domains.
  Missing targets retain the full ID and a warning; no invented names.
  The reusable Entity Picker provides room, domain, integration and availability
  filters, search by entity/device name or ID, usage hints and multi-selection.
  Existing selections remain visible outside filters or when missing. Their
  operation and parameters are preserved. The engineer's explicit **Тест**
  button in the picker and assigned light row queues a single light toggle
  through the existing verified output engine, with observed state and a
  TEST log entry. No configuration write or input-key emulation; global
  Maintenance, unknown/offline targets and pending commands block the test.
  Selection changes the editor draft,
  not HA; Save applies
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
- **Home profiles:** smart lights use ON/OFF, Fixed (Day / Night / Custom),
  or Day/Night. Media volume can reference the same global profiles.
  Only Custom displays local parameters. Day, Night and current are
  references, resolved from System Globals retained night_mode/state (on/off)
  and night_mode/profiles (day/night) under DigitalHouses/Global/.
  The System Globals module owns all
  profile values. Missing/invalid snapshots block profile ON/volume, not
  OFF or independent assignments. No global settings are persisted here.
  Nulls are unset; zero brightness means OFF, zero volume means mute.
  CCT/RGB are mutually exclusive; unsupported color is omitted.
  Profile edits alone do not trigger a transition. App option auto_day_night (default false) enables adaptation
  on a real mode transition for active dynamic-only targets. Skip ambiguous
  fixed/dynamic overlaps, offline targets and groups without all members
  confirmed ON. No retained startup replay or playback start. HA light
  state-check and parameter call are not atomic; live hardware tests remain.
- **Sensors (DEV):** discover HA binary_sensor
  motion/occupancy/presence and same-device illuminance in lx. Sensor rows
  use the existing versioned JSON bindings store alongside legacy switch rows.
  Ingress configures explicit light/switch ON, per-target profiles and optional
  OFF delay after absence. Lux thresholds are validated; raw/foreign Lux is
  not accepted. Read-only HA state_changed events feed the existing execution
  queue. Only observed OFF→ON presence may activate an observed-off target;
  already-on lights remain untouched. Confirmed ownership and absence
  deadlines are persisted and checked on reconnect/restart. Manual commands
  cancel ownership; observable external changes cancel it as well. Verified Z2M
  groups use one multicast command with all-member OFF/ON checks and persistent
  member-level ownership; mixed, unverified or overlapping target sets are
  skipped. Manual changes to one member cancel the group timer. Native HA
  groups remain excluded pending route verification. Hardware
  acceptance, key/physical relay timers and readiness integration remain.
- **Cover:** select Toggle, Open, Close, Stop or Position according to the HA
  capability flags. Toggle resolves from a known settled state; moving or
  unknown state does not imply a direction. Optional window/door/opening
  binary sensors protect every assignment of the same cover (union of saved
  guards, including disabled or missing input keys). Read HA state before
  dispatch; missing, open or unavailable guard blocks movement, never Stop.
  Guard metadata is not sent to HA services. No automatic replay on closure.
  Position is confirmed in LOG only by a newer settled matching position;
  Stop is service acceptance only. This is supplemental to hardware safety.
- **Climate:** Toggle/ON/OFF require the advertised HA feature flags, HVAC mode
  comes from the device's hvac_modes list, and single target temperature uses
  HA's configured unit, supported bounds and step. Revalidate the live state,
  registry and temperature unit before dispatch. Unknown or unavailable
  targets are skipped. No automatic mode selection by Electrica and no HVAC
  algorithm or DH Climate changes. Target ranges and presets are not exposed
  in this stage; the temperature request never includes a mode change.
  LOG confirms only a newer matching mode/setpoint, not physical heating.
- **Media player:** Play/Pause, Play, Pause, Stop, Next/Previous, volume
  0–100% and media selection from the HA Media Browser, subject to advertised
  capabilities. Play/Pause resolves from the observed playback state. Volume
  does not issue a play or power-on command and skips off/standby. Selection
  uses the read-only HA browser; only the configured Action starts playback.
  Media references and titles remain in the existing JSON assignments.
  LOG verifies newer playing/paused states or volume reports; Stop, track
  changes and play_media are service acceptance only (no false confirmation).
- **Mode Keeper:** preserve existing explicit decoupled/ON policies and
  maintenance semantics. Per-key policies in Ingress:
  physical (`control_relay`; no Actions or forced relay state) or logical
  (`decoupled`; separately choose **Удерживать ON/OFF**).
  Persist `decoupled/ON` or `decoupled/OFF` for the explicit hold policy.
  Legacy `decoupled` without hold and unconfigured channels remain unchanged
  until explicitly configured. No automatic relay-state migration. A key
  cannot be made physical while retaining assignments, including disabled
  assignments. Only verified
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
