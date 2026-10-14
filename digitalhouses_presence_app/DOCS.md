# DigitalHouses Presence App 0.1.0 — experimental pilot

## Configuration
The App Store's native **Configuration** tab is the supported installation and settings UI. This build deliberately does not register any custom Home Assistant frontend panel.

For every resident:
- `user_id`: permanent Home Assistant user identifier, not display name
- `name`: friendly label
- `device_id`: selected Mobile Companion device identifier (recorded but not cryptographically verified in this version)
- `gps_tracker`: exact HA `device_tracker.*` provided by that Companion device

`exclude_users` is a list of HA user IDs. Exclusion is explicit, not inferred from HA admin permissions.
`presence_mode=gps` is the functional pilot mode. `hybrid` has GPS input only; `wifi` has no Wi-Fi input and will preserve restored state or remain unknown. Any network presence decision requires additional safety validation.

## Source confidence and event semantics

Home Assistant Core is queried through `http://supervisor/core/api`, authorized by `SUPERVISOR_TOKEN`. The GPS entity must have a fresh timezone-aware `last_updated`. Stale, unknown or unavailable data cannot initiate a departure. The last *confirmed* state survives restart in `/data/presence_state.json`; corrupted existing persistence prevents start.

A source/aggregate transition is a machine event only after first real observation of the running process. MQTT retained state is synchronized before transient QoS1 events. Transient events are never replayed after reboot or reconnect. The initial state of an unconfigured home is **unavailable**, not off. Distance is computed from Home latitude/longitude and fresh GPS coordinates, with no additional attributes.

## Installation

Use Home Assistant **Settings → Apps → App Store** and the already configured DigitalHouses repository URL. Install the experimental App through the native menu. This initial version builds from the Dockerfile supplied in the repository; it does not require manually installing a zip or copying scripts. MQTT broker integration must be available to Supervisor (`mqtt:need`).

## Known limitations

Automatic registration from phone is not available until a minimum authorized HA Core custom integration is implemented and validated. The 14 October WebSocket proof of concept must not be misrepresented as an installed feature. Wi-Fi probing, 15+ minute iPhone sleep qualification and robust negative Wi-Fi verification remain unproven; no scanner or negative ARP result affects presence.

Telemetry is not emitted in this experimental preproduction pilot; the config flag is reserved for the eventual policy-compliant supported release. Do not deploy to Amir, and do not use the pilot to arm/disarm an alarm.

## Next acceptance milestones

See [testing plan](docs/TEST_PLAN.md), [requirements](docs/REQUIREMENTS.md), and [MQTT contract](docs/MQTT_CONTRACT.md).
