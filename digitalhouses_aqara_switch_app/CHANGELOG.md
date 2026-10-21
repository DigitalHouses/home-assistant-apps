# Changelog — DigitalHouses Aqara Switch App

## 0.1.2

- Add optional, explicitly configured passive Zigbee2MQTT group monitor (one group per site) with live member expansion.
- Record MQTT-observed light/group states and recent events to a bounded /data JSONL log.
- Add HA MQTT Discovery diagnostic sensor for light group details and a Lovelace group tree.
- Preserve honest OBSERVED_UNVERIFIED semantics with optimistic=true; no GET/SET or relay controls.
- Keep manual-only scan and optional monitor disabled by default.

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
