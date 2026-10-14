# Changelog

## 0.1.12
- Add administrator-only registration diagnostics in the native Ingress UI: resident, device, GPS tracker, enrollment IP/MAC, GPS state and last reported timestamp.
- Require a verified active Home Assistant administrator group via the existing authenticated Supervisor-to-Core WebSocket for every private debug request. Deny ordinary users and fail closed on errors.
- Remove IP/MAC from the regular resident status endpoint; retain addresses only in the private on-disk registry and secure admin debug API.
- Add an optional admin-only Lovelace launcher and preserve the previously approved narrow LAN/NET_RAW permission scope.
- This is enrollment debugging only: Wi-Fi presence and absence remain unavailable.

## 0.1.11 (draft — single-install acceptance pending)

- Add a native **Supervisor Ingress** interface to the DH Presence Home Assistant App. Installation is through the App Store alone; no `custom_components`, frontend resource, HACS dependency or manual HA configuration is required for registration.
- Use Supervisor-authenticated Ingress user headers to obtain authoritative HA user ID and display name. Extract the actual Core transport peer from the appended proxy chain; require a direct local HA URL.
- Let the phone user explicitly choose their GPS `device_tracker`; do **not** infer user ownership or phone authenticity from a shared HA login. Require a fresh on-link active ARP reply for IP→MAC, never a stale neighbour-cache entry or browser-supplied identity.
- Save the private user/device/IP/MAC binding atomically in the App's own `/data` and auto-enroll its resident with the original stable MQTT identity; the card shows `Имя жильца (Устройство)` without `resident_names`.
- Preserve legacy pilot configuration and prevent excluded HA users from registering. No Wi-Fi absence handling or alarm integration is enabled.
- Host LAN network + only `NET_RAW` are explicitly authorized for this 0.1.11 experimental pilot and guarded by restrictive validator tests; live HAOS client-IP and ARP acceptance is still pending.


## 0.1.10

- Use the last valid HA GPS state and coordinates for a stationary iPhone even after days without new GPS reports; age alone no longer marks the GPS and distance sensors unavailable.
- Publish the genuine source observation timestamp as `gps_reported_at` and the configured age-warning threshold as diagnostic metadata.
- Label aged readings as last-known and show their original report date on both dashboards.
- Manual Refresh succeeds on valid last-known HA observations and acknowledged MQTT publication; it never asserts that the phone acquired a fresh location.
- Keep invalid/unknown source handling and the no-fabricated-events guarantee; leave the Wi-Fi engine unimplemented.
- Cover two-day GPS silence, retained distance, timestamp provenance and repeated observations in regression tests.


## 0.1.9

- Rename the existing MQTT device display name to **DH Presence** without changing its stable identifier, unique IDs or topic base.
- Prefer fresh Home Assistant `last_reported` when available over `last_updated`, which stays unchanged for identical state reports. Stale data remains unavailable and distance still requires coordinates.
- Discover an individual Wi-Fi binary sensor for each registered phone, with source-specific availability deliberately offline until the independently verified Wi-Fi engine exists.
- Add actual runtime Refresh/Check Version controls, runtime-owned operation card, last-refresh and latest-release diagnostics; retain Supervisor installation/restart ownership.
- Bring standalone and full dashboard cards into parity with the unified DigitalHouses control standard.
- Expand regression tests and clarify feature gates.


## 0.1.8

- Use the site's `script.write2log(title, message)` as the only notification action for arrival, departure, verified Wi-Fi connection and disconnection. Remove duplicate `logbook.log` and `persistent_notification.create`; Recorder may retain the original MQTT Event state.
- Allow an optional once-only `resident_names` App Configuration mapping from a registered GPS tracker to a person's name. Persistent Supervisor settings preserve names across App updates; invalid/unregistered/duplicate bindings are rejected.
- Add `user_name` (nullable) and `device_name` to machine events and `user_name` to aggregate resident attributes, retaining legacy `resident_name` and all existing MQTT entity identities.
- Update dynamic Lovelace residents list to show user/device labels; add migration, mapping and notification regression tests.
- No new MQTT devices, independent name service, Wi-Fi engine, or alarm integration.

## 0.1.7

- Arrival/departure machine events now include authoritative `first_arrival`, `last_departure`, `residents_home_after` and `device_tracker` identity, without changing event types, QoS1 or retained-state ordering.
- Strict first/last flags are determined by whole-house transitions in the engine, including multiple resident changes during a single poll and uncertainty-safe handling.
- Update native Russian local HA Package for Recorder-backed Logbook recording and notifications on arrival/departure, and future verified Wi-Fi connection/disconnection.
- Remove the older example's extra invalid top-level package wrapper. No new MQTT Device, entity or invented local notification protocol.

## 0.1.6

- Compare the MQTT Device Discovery envelope and publication sequence with functioning DigitalHouses Internet App and Recorder App.
- After MQTT broker acknowledgment, perform a read-only, rate-limited check through HA Core API for the MQTT integration and Presence entity IDs; report discrepancies in App logs.
- Preserve the native MQTT Device Discovery contract, single MQTT device, resident sensors and non-destructive workflow. An absent entity ID does not conclusively prove discovery rejection when users can rename entities.

## 0.1.5

- Install the owner-approved rectangular glossy blue Presence App banner as `logo.png` (250×100).
- Preserve the already approved square GPS icon and all runtime MQTT/presence behavior unchanged.
- Bump the App metadata version so existing HA installations can apply the artwork through the normal App update workflow.

## 0.1.4

- Instrument MQTT Device Discovery and first state publication with broker QoS1 acknowledgment logging, including the exact topic and component count.
- Retry failed MQTT Discovery automatically and republish on Home Assistant MQTT birth and at bounded five-minute intervals.
- Clarify in diagnostics: broker acknowledgment is distinct from HA MQTT integration accepting a Discovery payload.
- Refresh 3D blue GPS-location icon and catalog banner consistent with other DigitalHouses Apps.
- Add regression tests for topic shape, HA birth triggers and unchanged stable component identifiers.

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
