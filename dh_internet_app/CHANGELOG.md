# Changelog

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
