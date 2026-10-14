# Presence App — proposed MQTT contract (design draft)

Shared device: `DigitalHouses Presence App`.
Canonical product: `digitalhouses_presence_app`.
Entity prefix: `dh_presence_app`.
MQTT base: `DigitalHouses/Global/dh_presence_app`.
Discovery: `homeassistant/device/dh_presence_app/config` (one device config).

| Kind | HA entity | Meaning |
| --- | --- | --- |
| Binary sensor | `binary_sensor.dh_presence_app_residents_home` | ON if at least one included resident is confirmed home, OFF only when every included resident is confirmed not_home; unknown if no safe aggregate determination |
| Binary sensor | `binary_sensor.dh_presence_app_<stable_resident_key>_gps_home` | GPS source only, independent of final Hybrid decision |
| Sensor | `sensor.dh_presence_app_<stable_resident_key>_distance` | GPS great-circle distance in km, without extra attributes |
| Event | `event.dh_presence_app_event` | Machine-readable resident/source transitions |
| Diagnostic sensors | `sensor.dh_presence_app_version`, `sensor.dh_presence_app_started_at` | Common DigitalHouses runtime diagnostics |

Use stable resident keys based on HA user IDs, **not mutable display names**, for entity unique IDs. Dynamic removal/exclusion requires MQTT Discovery cleanup (tombstones) as well as entity removal on first synchronization.

The aggregate entity exposes `mode`, `residents`, `residents_total`, `residents_home`; include resident display names and each confirmed status, but no sensitive identifiers or locations. Public attributes should be deliberately bounded and should not update on every probe tick.

Events: `arrival`, `departure`, `wifi_in`, `wifi_out`, `gps_in`, `gps_out`.
Pilot payload fields: `schema_version: 2`, `event_type`, stable `resident_id`, non-localized resident `resident_name`, `source`, mode and ISO-8601 `observed_at`. Further event-specific fields must be explicitly schema-validated.
Payloads are facts, not translated messages. Events: QoS 1, `retain=false`. Discovery configuration and authoritative current state may be retained. On a transition, retained state must be synchronized **before** publishing the transient event. No startup or MQTT reconnect event replay.

In GPS mode, Wi-Fi source events do not alter aggregate presence. In Wi-Fi mode, source events must not duplicate an arrival/departure notification; presentation policy belongs to the local HA package.

MQTT Discovery, retained state, and transient event publishing are implemented in the experimental pilot. Tests currently validate pure logic and payload shape; real HA / MQTT integration acceptance remains pending.
