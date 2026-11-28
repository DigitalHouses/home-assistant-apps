# Changelog

## 0.1.9
- DH Journal 1.0.3: SQLite is the only event store. Remove RAM fallback. On database failure stop journal writes until App restart, show storage unavailable, and disable export/clear; do not delete existing history.

## 0.1.8
- DH Journal 1.0.2: isolate malformed diagnostic events, bound event size and nesting, reject non-durable clear in RAM, atomically persist clear marker, optimize full-journal rendering and verify standard version in CI.

## 0.1.7
- DH Journal 1.0.1: show product name and App version in startup markers and LOG header; library version remains in technical details. Localize historical readiness reasons and operation/state labels in RU/EN, remove duplicate emoji, and classify initial readiness probes as pending with a bounded 20-second grace period. Preserve existing history.

## 0.1.6
- Pilot DH Journal 1.0.0: full-screen RU/EN Ingress LOG, local SQLite history of the latest 3000 immutable events, restart markers, incremental updates, search, level filters, and localized .log export. Readiness, lifecycle and configuration transitions only; no added MQTT entities or polling.

## 0.1.5
- Remove display and indicator brightness from profiles, storage, MQTT and HA Dashboard. Migrate existing settings without changing remaining values. Simplify Ingress RGB editing to a color picker and clear action, without a visible HEX text input.

## 0.1.4
- Store independent CCT and RGB values simultaneously in both day/night profiles. Remove the global color-mode selector, migrate existing state and imports, and expose independent Ingress and MQTT Discovery controls. Update MQTT contract and dashboard; consumers choose a supported color mode per device.

## 0.1.3
- Send one immediate best-effort heartbeat at every activated process startup, including restart after HTTP failure and version upgrade. Preserve installation identity, daily jitter and hourly in-process failure backoff. Log each startup attempt.

## 0.1.2
- Make MQTT and Home Assistant mandatory for System Ready without configuration switches. Keep only require_z2m as an optional readiness dependency; discover and monitor every Zigbee2MQTT namespace independently even when optional.
- Invalidate a timed-out bridge health transaction immediately and preserve independent readiness diagnostics.

## 0.1.1
- Remove manual Zigbee2MQTT base-topic configuration. Discover arbitrary-depth bridge namespaces on the connected broker, track independent health transactions, and require fresh evidence from all discovered bridges.

## 0.1.0
- Initial experimental System Globals App: autonomous day/night schedule, manual commands, durable validated profiles, mutually exclusive CCT/RGB and retained MQTT contracts.
- Add dynamic MQTT/HA/Z2M readiness checks, session-scoped live lease, transient machine events, observed HA lifecycle diagnostics, Ingress and MQTT Discovery.
- Add canonical Russian View, Recorder package, DH Sync source announcement and canonical version/operation entities.
- Preserve legacy publishers until an explicit migration; no changes to Presence or Electrica. Full HAOS/Z2M hardware acceptance and public telemetry legal clearance are not implied by this source release candidate.
- Verify telemetry policy v2, persisted installation identity, cadence, failure backoff and authenticated deletion; secure atomic credential persistence and handle HTTP 404 idempotently. No real telemetry is sent by tests.
