# Changelog

## 0.1.3

- Remove the unnecessary Supervisor timezone API lookup that can log `Unable to access the API, forbidden` during App startup. Preserve least-privilege `homeassistant_api: true` access to the Core GPS API.
- Use the DigitalHouses local `Asia/Almaty` timezone for startup logs without a privileged Supervisor call.
- Diagnose Home Assistant Core API authorization/status failures separately from MQTT connectivity and report tracker freshness/status changes without revealing coordinates.
- Disclose that experimental telemetry is not implemented even when `telemetry_enabled` is set to true.
- Add regression tests for startup permissions, Core API HTTP error detail and safe telemetry disclosure.

## 0.1.2

- Apply HA MQTT Select mode commands immediately instead of waiting for the next GPS polling interval.
- Ignore retained MQTT commands so reconnecting to the broker cannot overwrite a persisted operator choice.
- Keep one-field tracker registration and App Configuration → MQTT Select precedence unchanged.

## 0.1.1

- Register each resident using a single GPS `device_tracker` entity ID in App Configuration; names are read from Home Assistant tracker attributes.
- Keep one selected phone tracker per resident: logging in on an iPad under the same Home Assistant account does not automatically enroll the tablet.
- Add native MQTT Select `select.dh_presence_app_mode` for immediate `gps` / `wifi` / `hybrid` mode changes via HA Devices/UI.
- Configuration mode is the initial/default choice. HA UI choice persists across App restarts; changing the configuration value explicitly resets the UI override.
- Wi-Fi-only remains unavailable until trusted Wi-Fi evidence is implemented; Hybrid continues with GPS-only measurements. Switching mode never fabricates arrival/departure.
- Retained confirmed state uses tracker-based identity and persistent schema v2. Existing legacy user-ID state is not guessed into a new tracker (safe re-baseline).
- `exclude_users` remains honored for legacy mapped four-field configuration; a tracker-only roster with nonempty `exclude_users` is rejected until an authoritative user-device binding exists.
- Extend unit tests for mode persistence, invalid commands and tracker isolation.

## 0.1.0

- First installable **experimental** Home Assistant App for development and pilot use.
- Supervisor configuration, local Docker build, MQTT broker discovery, version and started-at diagnostics.
- GPS input through Home Assistant Core REST API for explicitly configured Companion trackers.
- Retained per-resident and aggregate logical presence. Unknown/expired GPS data is not interpreted as absent.
- Individual GPS binary sensors and straight-line distance sensors, structured non-retained machine events.
- Durable last-confirmed presence across App restart, safe source freshness handling and MQTT resynchronization.
- Wi-Fi presence, trusted automatic Mobile Companion registration and App UI remain **unimplemented**, and are not used for absence decisions.
- Initial runtime does not connect to DigitalHouses telemetry (unreleased experimental pilot).
