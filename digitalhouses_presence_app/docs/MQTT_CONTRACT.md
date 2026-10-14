# Presence App — proposed MQTT contract (design draft)

Shared device: **DH Presence** (stable identifier `dh_presence_app`).
Canonical product: `digitalhouses_presence_app`.
Entity prefix: `dh_presence_app`.
MQTT base: `DigitalHouses/Global/dh_presence_app`.
Mode command: `DigitalHouses/Global/dh_presence_app/mode/set`, non-retained.
Mode state: `DigitalHouses/Global/dh_presence_app/mode/state`, retained.
Discovery: `homeassistant/device/dh_presence_app/config` (one device config).

| Kind | HA entity | Meaning |
| --- | --- | --- |
| Binary sensor | `binary_sensor.dh_presence_app_residents_home` | ON if at least one included resident is confirmed home, OFF only when every included resident is confirmed not_home; unknown if no safe aggregate determination |
| Binary sensor | `binary_sensor.dh_presence_app_<stable_resident_key>_gps_home` | GPS source only, independent of final Hybrid decision |
| Binary sensor | `binary_sensor.dh_presence_app_<stable_resident_key>_wifi_home` | Wi-Fi source only; unavailable until a verified Wi-Fi engine publishes evidence |
| Sensor | `sensor.dh_presence_app_<stable_resident_key>_distance` | GPS great-circle distance in km, without extra attributes |
| Event | `event.dh_presence_app_event` | Machine-readable resident/source transitions |
| Select | `select.dh_presence_app_mode` | GPS / Wi-Fi / Hybrid; MQTT command + retained state |
| Diagnostic sensors | `sensor.dh_presence_app_version`, `sensor.dh_presence_app_started_at` | Common DigitalHouses runtime diagnostics |
| Controls | `button.dh_presence_app_refresh`, `button.dh_presence_app_check_updates`, `sensor.dh_presence_app_card` | Actual runtime Refresh and stable-release check |
| Control diagnostics | `sensor.dh_presence_app_refresh_state`, `sensor.dh_presence_app_last_refresh`, `sensor.dh_presence_app_latest_version`, `binary_sensor.dh_presence_app_update_available` | Standard runtime operations and version reporting |

Use stable resident keys based on the explicitly registered `device_tracker` entity ID, **not HA user IDs or mutable display names**, for entity unique IDs. Dynamic removal/exclusion requires MQTT Discovery cleanup (tombstones) as well as entity removal on first synchronization.

The App's MQTT Select provides the operator's runtime mode; its retained state is derived from an independently persisted selection. When App Configuration mode changes, it overrides the previous UI selection at the next App restart.

The aggregate entity exposes `mode`, `residents`, `residents_total`, `residents_home`, and the informational `gps_freshness_seconds` threshold. Each resident also has the actual source `gps_reported_at` timestamp (or null); individual GPS binary sensors expose it as an attribute. A resident includes the source tracker's `name` (device label), App-configured `user_name` (optional/null), and each confirmed status. No GPS coordinates are exposed. Public attributes should be deliberately bounded and should not update on every probe tick.

Events: `arrival`, `departure`, `wifi_in`, `wifi_out`, `gps_in`, `gps_out`.
Pilot payload fields: `schema_version: 2`, `event_type`, stable `resident_id`, `resident_name` (legacy tracker-friendly label), `device_name` (same HA tracker-friendly label), `user_name` (App-configured name or JSON null), `device_tracker` (configured source entity ID), `source`, `mode`, and ISO-8601 `observed_at`. Names are mapped once in Supervisor App `resident_names` settings and reused in Events; local packages do not resolve Person at delivery. **Arrival/departure** events additionally include `first_arrival`, `last_departure` (booleans), and `residents_home_after` (non-negative integer). A first arrival is **only** asserted when the known overall household status transitions `not_home → home`; a last departure only when it transitions `home → not_home`. Unknown residents preclude claiming an empty household. With multiple residents changing in one poll, these flags are calculated by the engine for each transition, so there is exactly one first and one last transition. No flags are fabricated on GPS/Wi-Fi source-only events.
Payloads are facts, not translated messages. Events: QoS 1, `retain=false`. Discovery configuration and authoritative current state may be retained. On a transition, retained state must be synchronized **before** publishing the transient event. No startup or MQTT reconnect event replay.

In GPS mode, Wi-Fi source events do not alter aggregate presence. In Wi-Fi mode, source events must not duplicate an arrival/departure notification; presentation policy belongs to the local HA package.

MQTT Discovery, retained state, and transient event publishing are implemented in the experimental pilot. Tests currently validate pure logic and payload shape; real HA / MQTT integration acceptance remains pending.

Version 0.1.9 adds Wi-Fi placeholder availability topics and the runtime controls above. Existing identifiers, GPS distance, aggregate and MQTT event topics stay unchanged. No Wi-Fi transition events are emitted before verified Wi-Fi observations.

Version 0.1.10 trusts HA's last valid GPS status and coordinates irrespective of age. The configured GPS freshness interval controls a **display-only** old-data label, not MQTT GPS availability. Refresh reads/republishes last-known observations without implying new phone GPS data. Unknown/unavailable source states remain unavailable and cannot generate an absence. The original source timestamp is preserved; repeat polls of the same report do not emit events.
