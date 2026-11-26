# Changelog

## 0.1.1
- Remove manual Zigbee2MQTT base-topic configuration. Discover arbitrary-depth bridge namespaces on the connected broker, track independent health transactions, and require fresh evidence from all discovered bridges.

## 0.1.0
- Initial experimental System Globals App: autonomous day/night schedule, manual commands, durable validated profiles, mutually exclusive CCT/RGB and retained MQTT contracts.
- Add dynamic MQTT/HA/Z2M readiness checks, session-scoped live lease, transient machine events, observed HA lifecycle diagnostics, Ingress and MQTT Discovery.
- Add canonical Russian View, Recorder package, DH Sync source announcement and canonical version/operation entities.
- Preserve legacy publishers until an explicit migration; no changes to Presence or Electrica. Full HAOS/Z2M hardware acceptance and public telemetry legal clearance are not implied by this source release candidate.
- Verify telemetry policy v2, persisted installation identity, cadence, failure backoff and authenticated deletion; secure atomic credential persistence and handle HTTP 404 idempotently. No real telemetry is sent by tests.
