# Changelog

## 1.2.0

- Added `sensor.internet_outages_month` through MQTT Discovery.
- Added persistent monthly Internet outage history in `/data/outages.json`.
- Sensor state contains the number of completed outages in the current local calendar month.
- Sensor attributes contain the latest 10 outages with start, end and duration.
- Added monthly total outage duration in `total_duration` and `total_duration_seconds`.
- Outages spanning a month boundary are counted in the new month from local midnight.
- Added Supervisor timezone propagation to the App runtime.
- Added outage persistence, month rollover, MQTT Discovery and runtime regression tests.

## 1.1.1

- Added `number.internet_speed_periodic_interval` for changing the automatic
  Speedtest interval directly in Home Assistant.
- Added a 5–720 minute range, 5-minute UI step and box input mode.
- Changing the Number now immediately restarts the countdown to the next
  scheduled test without restarting the App.
- Added persistent `/data/schedule.json` storage.
- Preserved `periodic_test_interval_minutes` as a backward-compatible App
  option; an explicit option change is adopted on the next App restart.
- Added MQTT schedule state and command topics.
- Added Recorder and Lovelace entries for the new Number.
- Expanded runtime, discovery and repository validation tests.

## 1.1.0

- Changed the default periodic test interval for new configurations to 30 minutes.
- Added persistent MQTT Number thresholds:
  - Minimum download speed, default 10 Mbit/s;
  - Minimum upload speed, default 10 Mbit/s;
  - Maximum ping, default 200 ms.
- Added problem binary sensors:
  - Low download speed;
  - Low upload speed;
  - High ping;
  - Internet performance problem.
- Implemented strict comparison semantics: speed below minimum and ping above maximum are problems; equality is normal.
- Added immediate problem-sensor recalculation when a threshold changes.
- Added diagnostic Recent results with persistent storage, immutable historical thresholds, server context and prepared problem reasons.
- Added `recent_results_limit` option with range 5–50 and default 20.
- Added `/data/thresholds.json` and `/data/recent_results.json`.
- Added dedicated result-freshness availability so stale measurements and performance evaluations become unavailable reliably.
- Preserved previous measurements and evaluation after failed tests or missing connectivity.
- Kept packet-loss `null` as Home Assistant `unknown`.
- Preserved all 1.0.0 MQTT topics, device identifier, unique IDs and default entity IDs.
- Added Recorder and built-in Lovelace examples for the new entities.
- Excluded Recent results from Recorder to avoid storing the large result-array attribute.
- Expanded unit and discovery regression tests.
- Updated English and Russian documentation and feedback links.

## 1.0.0

- Published the first stable DigitalHouses Speedtest App.
- Verified installation and operation on Home Assistant OS `amd64`.
- Added official Ookla Speedtest CLI 1.2.0.
- Preserved the LXC prototype MQTT topics and existing entity unique IDs.
- Added manual and optional periodic speed tests.
- Added Google DNS and Cloudflare DNS connectivity binary sensors.
- Added suppression of speed tests when both connectivity targets are down.
- Added preferred server IDs and automatic server fallback.
- Added nearby Ookla server discovery with MQTT sensor attributes.
- Added persistent test state and server-list cache.
- Added an optional Recorder package.
- Added English and Russian documentation.
