# Changelog — DigitalHouses Aqara Switch App

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
