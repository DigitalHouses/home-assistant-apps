# Changelog

## 0.1.21 — Prevent duplicate Wi-Fi arrival notifications

- Keep the most recent decisive Wi-Fi evidence (verified registered-MAC HOME or completed debounced ARP NOT_HOME) separately from temporary `unavailable` source status.
- Do not emit another `wifi_in` when ARP recovers after a probe error, MAC mismatch or temporary freshness timeout if the previous decisive state was already HOME.
- Preserve a real `wifi_out` followed by `wifi_in` when consecutive valid negative probes establish NOT_HOME, including transitions interrupted by technical probe errors; no fictitious departure is emitted solely because ARP fails.
- Add regression tests for unknown/recovery and real out/in sequences. MQTT event names/topics, Recorder, Home Assistant notification package and owner notification switches are unchanged.


## 0.1.20 — DigitalHouses branding alignment

- Replace `icon.png` (128 × 128) and `logo.png` (250 × 100) with the approved dark-navy neon-blue house + resident + red magnifier design, matching Internet and Recorder Apps.
- Preserve image aspect ratios and the canonical Supervisor App asset paths. Presence runtime behavior, MQTT entity/event contracts, GPS/Wi-Fi logic, notifications and privileges are unchanged.


## 0.1.19 — Cleaner operational logging

- Move scheduled five-minute MQTT Discovery re-announcement messages from INFO to DEBUG, keeping initial synchronization, reconnection and recovery visible at INFO. MQTT payloads, retained QoS1 delivery, and resynchronization cadence are unchanged.
- Log successfully published transient presence events (arrival/departure, GPS, Wi-Fi) at INFO, without publishing extra MQTT events or altering source decisions.
- Classify intermittent HA Core API gateway errors (HTTP 502/503/504) as WARNING rather than ERROR, retain a deduplicated message and log tracker recovery at INFO. Other API failures remain ERROR.
- Report the configured Wi-Fi absence period in startup/mode logs instead of assuming 15 minutes. Startup warnings about experimental ARP and unsupported telemetry remain visible.


## 0.1.18 — MQTT notification switches per household

- Add three independent persistent MQTT switches in the existing DH Presence device: Notify · Presence, Notify · GPS, Notify · Wi-Fi. Defaults ON/OFF/OFF respectively to preserve core arrival/departure notices without duplicating notifications.
- Route `arrival`/`departure`, `gps_in`/`gps_out`, and `wifi_in`/`wifi_out`/`wifi_lost` through HA package `script.write2log` only when their corresponding MQTT switch is ON. MQTT events, source checks, mode decision engine and Recorder are never filtered.
- Persist switches under `/data/presence_notifications.json`, reject stale retained and invalid MQTT commands, publish authoritative retained ON/OFF states and restore on restart.
- Provide updated packages for both `!include_dir_named` and `!include_dir_merge_named`. No additional HA helpers or security privileges.


## 0.1.17 — Hybrid Wi-Fi network-reachability pilot and Mushroom residents

- Interpret only successfully completed local `arping` probes with explicit zero-reply summary as negative observations; route/interface/permission/command errors and conflicting MACs yield `unavailable` and restart the negative streak.
- After 15 minutes of consecutive negative ARP probes (60s poll), publish resident Wi-Fi OFF, `wifi_out`, and in `hybrid` mode override stale GPS HOME with NOT_HOME / `departure`; matching-MAC ARP reply restores HOME / `wifi_in` / `arrival`. Pure GPS mode does not use network absence.
- Publish per-resident status transition timestamps for final decision, GPS, and Wi-Fi in the existing retained MQTT roster (no extra entities). Preserve final decision timestamp across restarts when available; never claim old timestamps are current observations.
- Display dynamically generated per-resident Mushroom cards with localized timestamps. Update administrator diagnostics and truthful `script.write2log` Wi-Fi wording for ARP reachability rather than confirmed radio disconnection.
- **Pilot warning:** an iPhone may sleep through ARP while still associated with Wi-Fi. `off` is network unreachability, not proof that the Wi-Fi toggle is off. Observe behavior for several days before approving this method for presence/alarm control.


## 0.1.16 — MQTT unknown-state fix

- Preserve UNKNOWN/UNAVAILABLE as a distinct state in GPS, Wi-Fi and aggregate MQTT binary sensor value templates. A sleeping iPhone must not be temporarily displayed as a confirmed OFF before HA applies source availability.
- Publish per-source and aggregate availability before each retained snapshot so Home Assistant Recorder does not see a false OFF edge before a true unavailable transition.
- Keep stable SHA-256 resident IDs, person labels, Recorder entity IDs, event contracts, Wi-Fi positive-only evidence, 15-minute grace and the exact approved network privileges unchanged.
- Wi-Fi notifications are driven by the independent MQTT Event entity and the HA notification package, not by every `binary_sensor` state transition. Verify the automation is active before diagnosing a missed notification.

## 0.1.15 — Wi-Fi notifications through write2log

- Emit `wifi_in` on a **real** matching-MAC Wi-Fi reappearance after a startup baseline; never emit a synthetic connection solely because the App restarted.
- Emit `wifi_lost` once when positive Wi-Fi evidence expires after the configured 15-minute window. Preserve UNKNOWN/UNAVAILABLE semantics: no fake `wifi_out`, resident departure or security-mode action.
- Update the native HA notification package to send `script.write2log` for both events with user/device labels from the app and truthful Russian text.
- Extend MQTT Event Discovery with `wifi_lost`; retain `wifi_out` only for future independently verified disconnection. No new HA entities or notification services.
- Add tests for startup suppression, repeated ARP misses, single lost/reconnect notification and lack of false departure.

## 0.1.14 — Wi-Fi positive-evidence pilot

- Use the existing one-time Ingress registration IP/MAC to verify a resident phone locally via fresh active ARP every 60 seconds; no Nmap, NetAlertX, router API or additional integration.
- Matching MAC sets the resident's existing Wi-Fi MQTT binary sensor to HOME and may correct a GPS away observation in hybrid mode. IP mismatch, ARP silence, failed probe or missing registration never produce NOT_HOME.
- After 15 minutes without another positive Wi-Fi reply, stop asserting Wi-Fi HOME and report unavailable, preserving the last confirmed household state. This is **not** verified absence; no wifi_out or last-departure event from silent iPhones.
- Expose non-identifying last successful Wi-Fi observation and probe reason on the existing MQTT resident state and show them in administrator Ingress diagnostics; keep IP/MAC private.
- Fix hybrid decision-time calculations when an iOS GPS tracker reports an old but valid timestamp: current Wi-Fi evidence must not be ignored by time-travelling to GPS report time.
- Preserve GPS as default mode and maintain exact previously approved host_network/NET_RAW privileges. Wi-Fi-only can confirm HOME; absence remains unavailable until independent negative evidence is designed and field-tested.

## 0.1.13

- Compact the native registration and administrator diagnostic interfaces for mobile screens.
- Translate admin GPS, Wi-Fi and registration state labels to Russian status chips.
- Read HA Core configured time zone and show the last GPS report in it; fall back explicitly to UTC.
- Add per-device Copy actions for IP and MAC captured at enrollment, without exporting addresses through MQTT or the normal resident API.
- Keep admin-only server authorization, registration, GPS states and previously reviewed narrow network rights unchanged.

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
