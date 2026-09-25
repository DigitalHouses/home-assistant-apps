# Changelog

## 0.1.10

- Add explicit opt-in DigitalHouses Telemetry Protocol v1 support with `telemetry_enabled: false` by default.
- Persist a random per-installation UUID/token and heartbeat schedule in `/data/telemetry.json`; send only protocol version, policy version, `digitalhouses_internet_app`, App version and installation UUID.
- Send normal heartbeats every 24 hours ±30 minutes with one-hour failure backoff in an isolated worker so telemetry cannot affect Internet monitoring or recovery.
- Add authenticated telemetry deletion through `button.dh_internet_app_delete_telemetry`.
- Admit `digitalhouses_internet_app` to the shared telemetry protocol/stats-server allowlist and distinguish it from the legacy `digitalhouses_speedtest_app` product in the Stats dashboard.
- Block the built-in `*-local` development version from sending production telemetry.

## 0.1.9

- Reduce Home Assistant Recorder churn from `sensor.dh_internet_app_problems` by removing the per-publish `updated_at` attribute; the entity now changes only when the problem count/list changes.
- Reduce Recorder churn from `sensor.dh_internet_app_availability_month` by exposing only the stable `month` attribute and rounding the HA entity state to two decimals.
- Keep the full outage payload and exact `elapsed_seconds`, `online_seconds`, `offline_seconds` and outage durations on the App-owned outage MQTT payload; only the Recorder-facing availability entity is made low-noise.

## 0.1.8

- Simplify Home Assistant notifications to the same direct model used by `dh_pve_app`: machine event → `trigger.id` → `choose` → direct local action.
- Replace the Notification Envelope / secondary `dh_internet_app_notification` layer with `dh_internet_app_notification_local_package.yaml`.
- English example calls `persistent_notification.create` directly; the Russian site-local package calls `script.write2log` directly.
- Remove duplicated machine-event schema validation and `contract_error` presentation logic from Home Assistant. Required machine-event correctness remains producer-owned.
- Keep the Internet App machine-event schema and MQTT Event entity unchanged.

## 0.1.7

- Guard Router Download/Upload one-decimal MQTT templates against optional `null` telemetry values so an unavailable mapped source becomes unavailable cleanly instead of rendering an invalid numeric template.

## 0.1.6

- Simplified Speedtest runtime status to `idle | running`; the last attempt outcome is now exposed separately as `last_result=success|error|no_connectivity` while successful measurements remain persistent.
- Rounded Router Download/Upload rate entity states to one decimal place.
- Expanded the Recorder whitelist with Speedtest status metadata, quality thresholds, recovery state/cycle, aggregate Problems and Router WAN state while keeping rich list/history entities out of Recorder.
- Explicitly regression-tested that the current-month outage sensor publishes the complete monthly outage list without truncation.
- Restored a robust one-row-per-result Markdown pattern for the Recent Speedtests reference table.

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
