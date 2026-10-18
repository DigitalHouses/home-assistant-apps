# Changelog

## 0.1.1

- Automatically discover Zigbee2MQTT instances via coordinator-verified retained
  `bridge/devices` and `bridge/info` MQTT topics (1–3 level base topics).
- Remove required per-network settings from HAOS App configuration.
- Persist coordinator IEEE / stable network ID / current base topic in SQLite;
  rediscover on reconnect and during read-only refresh.
- Preserve existing 0.1.0 manual network IDs as compatibility hints where possible.
- Avoid displaying fictitious network count zero before any network is detected.

## 0.1.0

- Experimental initial release of DigitalHouses Zigbee Monitor App.
- Support multiple independent Zigbee2MQTT base topics and IEEE-based identity.
- Read-only inventory, Z2M availability and retained-aware MQTT activity counting.
- Home Assistant MQTT Discovery with separate Recorder-safe numeric metrics and detailed UI entities.
- SQLite minute aggregation, limited historical rankings (1h / 24h / 7d).
- Supervisor MQTT credentials, standard status card operations and mandatory privacy consent/telemetry.
- Offline transitions/incident notifications and anomaly spam classification are **not yet implemented**;
  their HA entities remain unavailable instead of fabricating zero values.
