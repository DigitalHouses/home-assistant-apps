# Changelog

## 0.1.0

- Created DigitalHouses Internet App as a new Home Assistant App product with canonical `dh_internet_app_` MQTT/Home Assistant identity.
- Added Internet/router reachability, current-month outage history and App-owned monthly availability calculation.
- Added `smart` and `both` recovery modes with guarded `button` / `switch` actions, countdown, Stop control and structured events.
- Added Version and Started-at runtime diagnostics.
- Added official Ookla Speedtest with periodic/manual execution, Download, Upload, Ping, Jitter, Packet loss and compact status metadata.
- Added persistent quality thresholds, low download/upload/high ping evaluation, aggregate Problems diagnostics and schema-v2 performance events.
- Added Recent Results persistence with the latest 20 successful tests and per-test quality thresholds.
- Added optional cumulative router traffic accounting with current-month totals and 12-month history.
- Added optional WAN state and current Router Download/Upload rate bindings while keeping the total external HA binding contract at seven including recovery.
