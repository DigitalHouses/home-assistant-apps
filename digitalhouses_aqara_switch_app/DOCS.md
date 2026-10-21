# DigitalHouses Aqara Switch App — Design Contract

**Design specification, not yet implemented.** Version `0.1.0` establishes only a testable, inert scaffold.

## Source boundaries

- Product ID: `digitalhouses_aqara_switch_app`; HA entity prefix: `dh_aqara_switch_app`.
- Zigbee2MQTT MQTT: authoritative network/coordinator identity, device IEEE, model, available action capabilities and confirmed physical settings.
- Home Assistant Device Registry + Area Registry: authoritative room membership at first import. An unknown Area is shown as **Unassigned** in App configuration; never create a fake HA Area.
- Supervisor App Options: user-owned mapping `room -> device -> key / key-combination -> supported event -> action -> targets`, and saved desired physical modes.
- No HA template passports, inferred areas from `friendly_name`, or site-specific hard-coded bindings.

## Explicit scan

1. A user presses the future HA UI **Scan** control. It is a distinct foreground operation, not general Refresh and not invoked at startup or on a timer.
2. Discover multiple Zigbee2MQTT instances, verifying the coordinator IEEE. Enumerate **Aqara input devices** with proven action capabilities, including wired and battery switches/panels.
3. Resolve only *new* identity pairs (coordinator IEEE, device IEEE) against HA registries. Retrieve device capabilities/confirmed settings only from MQTT; never invent missing values.
4. Re-read App Options immediately before writing; merge **new** identities only. For an existing entry, do not change the room, name, model, modes, targets or actions.
5. Never remove missing devices. Preserve user edits on conflicts; if a safe merge is impossible, abort and report an explicit error.
6. Publish real counts: scanned / newly added / skipped / errors. Button and operation-state sensors follow DigitalHouses Operation UI Standard.

## Dispatcher

- Consume configured MQTT button/action topics only.
- Execute declaratively bound, allowlisted Home Assistant actions (lights, groups, fans, covers, switches, scripts, scenes); never provide generic conditional workflows.
- Do not offer actions unsupported by the device. Command accepted is distinct from confirmed physical state.
- Exactly one dispatcher must be active per device during legacy AQPM2 migration.

## Mode Keeper and Maintenance Mode

- In **Normal**, keep supported physical device settings aligned with **user-owned** configuration.
- In **Maintenance**, eligible relay keys temporarily use physical relay control for servicing or lamp pairing; suspend conflicting button dispatch for those keys. Do **not** modify saved user settings.
- On exit, **restore the exact per-key configured mode**, not blindly all keys to decoupled (a defect in legacy AQPM2).
- Never invoke unsupported relay commands on battery-only devices.
- Maintenance state and recovery across application/device restart must be persisted and validated before implementing physical writes.
- If restoration is unconfirmed, surface a problem. Do not report success.

## UI and observability

Future HA UI: single product status card, explicit Scan action and result, grouped areas/devices and key bindings, maintenance controls where supported, diagnostics and problem sensor. Supervisor owns App install/restart; UI has no business logic or invented states. Adhere to repository Manual Refresh, Operation UI, Product Status Card, Contract Data and Events/Notifications standards. App emits machine events only; local HA decides notification text and delivery.

## Release and safety gate

This scaffold intentionally has **no active MQTT subscriptions or commands**. It is registered with `telemetry_allowed=false` and `release=null` until the release and privacy contracts are implemented. A source Docker build is for CI validation only; no published production GHCR image. Tests for the eventual runtime must cover idempotence, HA Areas, multi-Z2M identity, relay-mode restoration, failure recovery, event mapping and single-controller migration.

## Current work in progress: first testable code

This revision adds:
- Pure `aqara_switch.catalog`: parse MQTT Zigbee2MQTT exposes, reject unknown
  physical setting values rather than fabricate defaults, idempotent append-only
  room/switch merge with HA Area lookup injected by caller.
- Pure `resolve_hardware`: exact match of saved logical ID and structural
  profile; unknown or incompatible replacements are surfaced, not applied.
- Pure `aqara_switch.actions`: validated HA service call plans for virtual
  lights, ordinary lights, switches, covers, fans, scripts and scenes.
- HA LAB package containing three virtual template lights with persistent
  input_boolean helpers; no live HA installation or hardware tests yet.

**Not yet implemented**: MQTT runtime subscriptions, HA registry adapter,
Supervisor options persistence/schema for nested rooms, HA UI Scan button,
Mode Keeper, Maintenance, Dispatcher transport and actual button-to-light E2E.
All remain out of scope until the foundation passes CI and the HA LAB works.
