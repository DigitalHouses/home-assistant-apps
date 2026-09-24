# Changelog

## 0.1.5

- Migrated Internet App notifications to the repository Events and Multilingual Notifications Standard and DigitalHouses Notification Envelope v1.
- Added strict event-specific schema validation before localization; malformed machine events now emit explicit `contract_error` notifications instead of receiving silent fallback values.
- Made English and Russian locale packages contract-identical, moved Russian presentation to the canonical `examples/packages/locales/ru/` layout, and removed raw machine-payload forwarding.
- Kept notification delivery installation-owned: reusable locale packages stop at the transport-neutral `dh_internet_app_notification` Home Assistant event.

## 0.1.4

- Persist pending Internet outage detection from the first failed connectivity check, including the debounce attempt count, so App restarts do not lose the true outage start time or restart confirmation from zero.
- Confirmed outages now start at the first failed check; transient failures that recover before confirmation are discarded.

## 0.1.3

- Backfilled Recent Results `updated_at` from the newest persisted `tested_at` when upgrading legacy runtime state created before 0.1.2.

## 0.1.2

- Fixed Recent Results `updated_at` so it changes only when the persisted Speedtest history changes, not on every MQTT state publish.

## 0.1.1

- Fixed startup on Home Assistant base images that provide paho-mqtt 1.x by adding runtime compatibility with both paho-mqtt 1.x and 2.x callback APIs.
- Kept the MQTT v2 callback API when available while accepting the legacy four-argument `on_connect` callback on paho-mqtt 1.x.

## 0.1.0

- Renamed repository directory to `dh_internet_app` while keeping HA App slug `digitalhouses_internet`.
- Fixed MQTT Event discovery to pass schema-v2 JSON events directly to Home Assistant.
- Preserved active outage state across App restarts and calendar-month rollover.
- Expanded EN/RU App configuration descriptions for all user-facing options using the official nested `fields` translation format.
- Hardened MQTT v2 connection callback handling and documented all dashboard card dependencies.
- Persisted Stop Recovery, completed recovery cycles and active cooldown across App restarts for the same outage.
- Hardened switch recovery so a power-restore attempt is made even if the turn-off API response fails.
- Marked optional Router telemetry unavailable when its mapped HA source is absent/unavailable and filtered it from the reference dashboard.
- Extended the HAOS shutdown timeout to protect switch power restoration during normal App Stop/Restart.
- Added explicit MQTT Device Discovery cleanup when optional Router/Traffic mappings are removed.
- Fixed Router traffic unit normalization so bit/s and byte/s units cannot collapse into the same lowercase key.

- Created DigitalHouses Internet App as a new Home Assistant App product with canonical `dh_internet_app_` MQTT/Home Assistant identity.
- Added Internet/router reachability, current-month outage history and App-owned monthly availability calculation.
- Added `smart` and `both` recovery modes with guarded `button` / `switch` actions, countdown, Stop control and structured events.
- Added Version and Started-at runtime diagnostics.
- Added official Ookla Speedtest with periodic/manual execution, Download, Upload, Ping, Jitter, Packet loss and compact status metadata.
- Added persistent quality thresholds, low download/upload/high ping evaluation, aggregate Problems diagnostics and schema-v2 performance events.
- Added Recent Results persistence with the latest 20 successful tests and per-test quality thresholds.
- Added optional cumulative router traffic accounting with current-month totals and 12-month history.
- Added optional WAN state and current Router Download/Upload rate bindings while keeping the total external HA binding contract at seven including recovery.
- Added preferred Ookla server IDs, automatic fallback and on-demand server list refresh.
- Added reusable Home Assistant Recorder, notification and dashboard presentation examples.
