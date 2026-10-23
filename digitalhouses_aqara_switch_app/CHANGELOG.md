# Changelog — DigitalHouses Aqara Switch App

## 0.1.14

- Fix v0.1.13 mixed virtual LAB + physical Z2M toggle regression
  (`ths_livingroom/single_minus`). Preflight eligible light states on both
  transports before publishing any light command. If ANY participating lamp
  is OFF, turn every available lamp ON; otherwise turn all available lamps OFF.
  No per-light blind toggle; no "disco" for mixed starting states.
- Cache LAB REST results (including failed reads) once per action outside the
  MQTT mutex. Recheck adopted Aqara switch authorization, Z2M bridge,
  hardware route, availability, fresh feedback and in-flight shadow.
  Fail closed if a Scan changes any toggle routing during dispatch.
- Actual Z2M lamps remain direct MQTT-only; absent/offline/unknown lamps
  are skipped, with no HA REST fallback. LAB is restricted to six exact
  virtual entity IDs. Never claim physical confirmation on MQTT publish.
- Remove ON-only brightness/color attributes when the synchronized LAB
  toggle resolves to OFF, preserving optional transition.
- Add mixed five-light regression tests for both mixed-state directions,
  all-ON, offline, unmapped and rapid repeat. No YAML migration or relay writes.

## 0.1.13

- Hotfix for v0.1.12 regression: explicitly support the **six fixed virtual
  `light.dh_aqara_lab_*` entities** using Home Assistant Core REST while
  keeping real Zigbee2MQTT lights on direct MQTT.
- Virtual LAB commands now first read the actual HA light state and skip
  `unavailable`/`unknown` rather than issuing a blind command. The existing
  per-light brightness, Kelvin, RGB and transition settings are preserved.
- Plain multi-LAB-light toggle is synchronized: any OFF -> turn all ON,
  all ON -> turn all OFF. A short-lived command shadow avoids rapid-press
  inversion based on a stale reported state. Never use `light.toggle`
  independently on individual LAB targets.
- Physical Z2M targets without verified routes remain skipped and **never**
  fall back to HA. Mixed virtual/physical group toggles are rejected rather
  than producing unsynchronized behavior; explicit ON/OFF may mix.
- Update tests for the reported `double_plus` -> virtual LAB night light
  error, offline handling, rapid presses and fallback safety. No YAML
  migration, relay writes, or modification to input/mode-keeper behavior.

## 0.1.12

- Replace HA Core REST light output with verified **direct Zigbee2MQTT
  MQTT** `[base]/[friendly_name]/set` commands. Existing button YAML
  syntax stays unchanged; HA Core is needed only for the explicit Scan
  entity-registry association, not at press time.
- Explicit Scan resolves `light.*` to Z2M IEEE/coordinator/topic via HA
  Device/Entity registries and stores the verified routing map privately in
  the existing Adopt profile. No guessed entity IDs, no new YAML fields.
- Subscribe to Z2M bridge online-state, per-light availability and state.
  Never send a light command to known offline/unknown or unverified devices.
  Unmapped/multi-endpoint lights fail closed, including HA-only virtual lamps.
  If Z2M device availability is disabled, no light writes are sent.\n  State-readable lamps are polled through rate-limited Z2M `/get` at startup\n  until an actual (non-retained) state report arrives.
- Plain multi-light YAML uses a **single synchronized decision**: if any
  available target is OFF, turn all available targets ON; if all are ON,
  turn them OFF. Send explicit ON/OFF, never individual TOGGLE.
- In-flight shadow tracks the intended target state for quick repeated
  button presses; missing confirmation after 5 seconds blocks the next
  ambiguous toggle rather than replaying stale states.
- Support optional per-lamp brightness, Kelvin, RGB (to Z2M XY/HS) and
  transition with capability/range validation. Never send to physical relay
  or unsupported attributes. Record skipped lamps and publish MQTT status
  `sent`, `partial`, or `skipped` without claiming physical confirmation.
- Keep selective Mode Keeper, scoped Maintenance, and input hardware identity
  checks; no changes to Aqara device control modes.
- This version supports Z2M light devices with one unambiguous HA MQTT
  `light.*` entity and single `state` endpoint. Device light groups and
  HA-only virtual lights are deliberately not auto-resolved; no unsafe
  fallback to HA when a Zigbee route cannot be confirmed.

## 0.1.11

- Harden v0.1.10 Mode Keeper: bind queued light jobs to the exact Zigbee
  base topic, coordinator IEEE and friendly name, then recheck adopted
  hardware and actual per-key decoupled/ON right before dispatch.
- Reject wired `*_both` and other button bindings in YAML when the required
  key(s) are not explicitly declared as `decoupled/ON`. Battery remotes
  remain exempt and work with action-only exposes.
- Do not interpret generic baseline settings or intentional Maintenance
  changes as a Mode Keeper diagnostic mismatch. No unmanaged key writes.
- Preserve v0.1.10 Supervisor settings, one-time Scan semantics and the
  read-only retained-state startup gate. Output light commands still use HA.

## 0.1.10

- Automatically adopt `keep_mode` **only** for wired Aqara keys observed in
  `decoupled` with a writable, reported relay channel; captured policy is
  `left: decoupled/ON`, `right: decoupled/ON`, or `main: decoupled/ON`.
  Unmanaged `control_relay` keys are absent; battery/remotes have NO
  `keep_mode` and can use all their supported action events.
- Global Supervisor App options `maintenance_mode: false` and
  `restore_delay: 0.6` (seconds, 0.1–30), with per-switch optional
  `maintenance_mode` inside the existing multiline `switches` YAML.
- Global/local Maintenance blocks all App light actions (including battery
  buttons), and changes only managed wired keys to `control_relay`.
  Relay state is **never** changed when entering Maintenance.
- On exiting Maintenance or detecting live drift, restore only explicit
  `keep_mode` keys: first `decoupled`, then `ON` after reported mode
  confirmation; delay and 60s per-key retry backoff avoid rapid writes.
  Following MQTT reconnect, request readable mode/relay state via Z2M `/get`
  and prohibit `/set` based solely on retained data.
- A physical key can drive App actions only when its required key(s) are
  confirmed `decoupled/ON`; `*_both` requires both. Unmanaged wired
  control_relay never receives App action commands. No hardware mode support
  means no mode gating, which is correct for battery buttons.
- Initial Scan is non-actuating and captures a keeper policy once; subsequent
  Scan never overwrites existing keep_mode or silently restores a manually
  deleted policy. Existing light configuration/actions remain compatible.
- Does NOT change the light output transport; bound lights continue using
  Home Assistant REST until the separate MQTT/Zigbee2MQTT output migration.

## 0.1.9

- Place optional brightness, color temperature, RGB and transition fields
  **under each individual light target**, not globally for all lights.
  YAML targets may now mix `- light.name` and `- light.name: {brightness_pct: ...}`.
- Preserve the existing `service: light.turn_on` / `targets:` action wrapper;
  `service` applies to the action, attributes apply only to the named lamp.
- Dispatch separates different light parameters into independent HA calls and
  coalesces ONLY targets with equal service and equal attribute payload.
- Validate the full batch before enqueue; maintain MQTT action deduplication,
  queue ordering, and never operate the Aqara physical relay.
- Backwards-compatible with plain light target lists and legacy shared
  v0.1.8 action parameters, but new configs should use per-target options.
- Existing output is Home Assistant REST; direct Zigbee2MQTT MQTT output is a
  separate proposed transport change and is **not** implied by this release.

## 0.1.8

- Expand Aqara button actions with native HA smart-light commands:
  `light.toggle`, `light.turn_on`, `light.turn_off`.
- Keep existing short YAML list syntax as identical `light.toggle` behavior.
- Rich action syntax accepts `service`, `targets`, optional
  `brightness_pct`, `brightness_step_pct`, `color_temp_kelvin`,
  `rgb_color`, `transition`, validated before dispatch and again by HA
  client; one allowed service call per press for 1–16 lights.
- Reject conflicting RGB/Kelvin, combined absolute/step brightness, invalid
  ranges, turn_off with color attributes, all other service domains,
  unrecognized options, duplicate and non-light targets.
- Keep existing manual Scan, hardware Adopt/Mode Keeper, Zigbee action
  whitelisting, duplicate/replay filtering, and no physical relay switching.
- Existing v0.1.7 App options remain valid; no options migration needed.

## 0.1.7

- Fix Scan ignoring Aqara battery buttons and climate sensors with press
  events when HA does not expose a switch.* entity for those devices.
- Keep all eligible Aqara devices under the same `switch.*` config keys:
  first reuse the exact existing HA switch entity when unambiguous, otherwise
  derive a stable **logical-only config key** from Zigbee2MQTT friendly_name.
  Logical-only keys DO NOT create or claim to be HA entities.
- Collision guard for multiple Zigbee2MQTT networks and similar friendly
  names: qualify the logical-only key with a network name or deterministic
  stable suffix, never a physical IEEE.
- Manual Scan/Adopt retains exact coordinator, IEEE, model, capability and
  captured physical mode baseline privately. No Zigbee writes on Scan.
- Compatible hardware replacement retains logical key and existing action
  bindings. Invalid replacement profiles fail closed.
- Repeat Scan is idempotent and restores a config row when the operator
  cleared the YAML while the device remained adopted.
- No migration is added: experimental installation can be uninstalled
  and reinstalled to reset hardware profiles.

## 0.1.6

- Clean-install experimental revision: drop v0.1.4/v0.1.5 migration and
  separate flat bindings list. User will uninstall and reinstall first.
- Short switch-keyed YAML mapping under App option `switches`, e.g.
  `- switch.livingroom_switch: {enabled: true, actions: {single: [light.l1, light.l2]}}`.
- Manual Scan reads HA Device, Area and Entity registries, resolving the
  **existing** unique switch.* entity_id via confirmed Zigbee IEEE/device_id;
  never invents an HA entity. No or ambiguous switch.* causes scan problem.
- Keep actual coordinator, physical IEEE, captured model/modes internal to
  /data; bind user assignments to stable HA switch entity_id.
- Each supported press toggles 1..16 explicit light.* targets in **one**
  light.toggle HA service request. No physical relay ON/OFF writes.
- Explicit Scan may re-adopt a compatible replacement whose HA switch entity
  ID remains the same, preserving existing actions.
- No automatically created button, event or switch entities in Home Assistant.
- Supervisor's native form cannot render dynamic multi-level YAML keys;
  switch assignments are therefore a compact multiline YAML string field.

## 0.1.5

- Replace the opaque, folded `configuration_yaml` text editor with two native
  Supervisor lists: **Выключатели** (IEEE, Zigbee2MQTT friendly name,
  enabled) and **Назначения** (switch IEEE, button press, light.*).
- Explicitly typed UI lists support editing, adding and removing mappings;
  one valid configured press executes only a single `light.toggle`.
- Keep adopted hardware fingerprint, model, area and physical mode settings
  as private persistent App data, not editable by the dashboard or Supervisor
  UI. New Scan/Adopt appends newly discovered buttons to the structured list.
- One-time startup migration of v0.1.4 nested room configuration using the
  raw own-App Supervisor API: back up the original YAML, preserve complete
  adopted profiles and existing valid light.toggle bindings before committing
  the new options. Abort without starting MQTT control if migration is unsafe.
- Never perform automatic Scan, edit physical relay state or trigger lights
  on installation. Existing App version source and image tag remain immutable.

## 0.1.4

- Fix Scan/Adopt failing with `HA WebSocket authorization failed` due to
  missing Supervisor Home Assistant Core API access permission.
- Declare `homeassistant_api: true` in the App manifest, required by
  `ws://supervisor/core/websocket` Device/Area Registry lookup and by
  `http://supervisor/core/api/services/light/toggle`.
- Retain least-privilege `hassio_role: default` and existing MQTT access.
  No changes to Zigbee device actions, saved adoption data or user bindings.
- Updating the App reloads its Supervisor permissions; no user tokens,
  MQTT secrets or Home Assistant configuration changes are necessary.

## 0.1.3

- First installable immutable Home Assistant App release, delivered through
  GHCR as `ghcr.io/digitalhouses/digitalhouses_aqara_switch_app:0.1.3`
  for amd64 and aarch64.
- Enable installation through the DigitalHouses repository in
  Home Assistant → Settings → Apps → App Store.
- Preserve explicit user-driven Scan/Adopt, saved physical settings Mode Keeper,
  and narrowly configured single-light `light.toggle` on Aqara button action.
- Safe initial options: `rooms: []`, no targets bound, no lighting action
  until the operator explicitly adds a binding. Manual App boot.
- Operational limitation: real physical Aqara button-to-light E2E and hardware
  light confirmation are still pending field acceptance. Existing automation
  of the same physical press must be disabled before binding a light.

## 0.1.2

- MVP: explicit Scan is Adopt of new Aqara switches and captures confirmed
  writable mode/settings values as immutable baseline in Supervisor Options.
- Mode Keeper observes newly reported drift and requests restoration of only
  those adopted writable configuration keys, with a 60s minimum retry spacing.
  Never rewrites a physical ON/OFF output or sets unknown settings.
- Bound event Dispatcher: accepts non-retained matching Aqara action only for
  the saved coordinator/IEEE/profile; serially calls HA light.toggle for one
  explicitly configured light entity. Ignores unbound, duplicate/replayed and
  non-Aqara events.
- HA diagnostic last_action sensor: queued, accepted (HA call), error.
  Accepted is NOT proof that the target light physically changed state.
- No Zigbee group verification, automatic assignment, HA UI binding editor,
  power recovery, or automatic physical relay control in this MVP.

## 0.1.1

- First executable manual-scan Home Assistant App pilot; boot remains manual.
- MQTT observes Zigbee2MQTT bridge inventory and device state without Zigbee writes.
- UI's explicit Scan button imports only new Aqara button devices; known entries are never overwritten.
- Home Assistant Device/Area Registry matching through Supervisor WebSocket proxy.
- Store one YAML tree in Supervisor App Options and save last scan results under /data.
- MQTT Discovery publishes version, scan button, operation state, tree details and problem details.
- Physical relay Mode Keeper, Maintenance Mode and button Dispatcher remain disabled.

## 0.1.0

- Create canonical HAOS App repository scaffold, translations, icons and test harness.
- Record manual-only, idempotent scan and declarative Aqara key/action configuration.
- Document HA Area grouping and the Mode Keeper / Maintenance Mode safety requirements.
- No active device scan or control in this version; not a functional published release.
