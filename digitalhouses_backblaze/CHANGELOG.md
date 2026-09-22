# Changelog

## 0.1.6

- Reduce the daily Total used chart history window from 30 days to the proven 10-day DB Monitoring pattern.
- Keep daily grouping, max aggregation, and bar rendering unchanged to avoid long mini-graph-card history loads.

## 0.1.5

- Add a reusable Home Assistant Backblaze dashboard example.
- Add a 30-day daily bar chart for account Total used using Recorder history.
- Add dynamic per-bucket storage, files, and stored-version cards.
- Add a narrow Home Assistant package that records only Total used and Total files.

## 0.1.4

- Rename the account file-count sensor to Total files.
- Add a one-time retained MQTT Device Discovery reset so existing Home Assistant entity-registry categories are re-read.
- Preserve existing MQTT unique IDs and entity IDs while moving primary metrics out of Diagnostics and controls into Configuration.

## 0.1.3

- Rename the account aggregate storage sensor to Total used.
- Keep Total used in the normal Sensors group.
- Explicitly consume the pre-aggregated account storage total so dashboards never need to sum bucket sensors.

## 0.1.2

- Display account and per-bucket storage in GiB with one decimal place.
- Remove bucket state attributes from storage entities.

## 0.1.1

- Split Home Assistant entities into primary metrics, configuration controls, and diagnostics.
- Keep account totals and per-bucket storage/file/version metrics in the normal device entity group.
- Move Refresh and telemetry deletion controls to the configuration category.
- Keep API, Last update, App version, and Started at in diagnostics.

## 0.1.0

- Initial DigitalHouses Backblaze Home Assistant App.
- Monitor every B2 bucket visible to the configured application key.
- Publish total stored bytes plus per-bucket stored bytes, current files, and stored versions through MQTT Discovery.
- Add API connectivity, last update, manual refresh, App version, and process started-at diagnostics.
- Use Backblaze B2 Native API v4 with listBuckets and listFiles capabilities only.
- Add opt-in DigitalHouses product telemetry, disabled by default, with persistent installation identity, 24-hour jittered heartbeat scheduling, failure isolation, and authenticated deletion.
