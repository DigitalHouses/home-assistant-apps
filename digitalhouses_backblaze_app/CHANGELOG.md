# Changelog

## 0.1.14

- Force a one-time MQTT Device Discovery schema reset after the GiB-to-GB storage-unit migration.
- Recreate Backblaze storage sensors from the GB-native Discovery contract so Home Assistant does not preserve the previous GiB display unit in the entity registry.
- Keep existing entity IDs, MQTT topics, Recorder scope, decimal GB values, and storage-tree semantics unchanged.

## 0.1.13

- Display account Total used and all per-bucket used sensors in decimal GB (`bytes / 1,000,000,000`) to match the Backblaze B2 web UI and the storage tree.
- Preserve all existing entity IDs, MQTT topics, Recorder scope, and one-decimal display precision.
- Keep the storage-tree raw attributes in absolute bytes and its dashboard presentation in decimal GB/MB/KB.

## 0.1.12

- Add one `sensor.dh_backblaze_storage_tree` overview entity with bucket and first-level folder data in attributes.
- Aggregate current bytes, current visible file count, and latest B2 upload timestamp for every first-level folder during the existing full file-version scan without an additional B2 listing pass.
- Align manual Refresh with the DigitalHouses Manual Refresh Standard: retained `idle/updating/error` operation state, timestamps, duration, error detail, duplicate suppression, and success-only `last_refresh`.
- Persist the last successful manual Refresh under `/data/runtime_state.json` so restart and supported backup/restore keep its meaning.
- Keep periodic scans independent from manual Refresh state and `last_refresh`.
- Add a Markdown storage tree dashboard view and PVE-style live Refresh presentation while keeping the previous successful snapshot visible during an in-progress scan.

## 0.1.11

- Persist the dynamic MQTT Device Discovery manifest under /data and reconcile removed bucket components across App restarts.
- Require broker-confirmed Discovery cleanup before advancing the persisted manifest.
- Keep storage/file/version metrics unavailable until a successful Backblaze scan and after scan failures, preventing stale retained values from appearing current.
- Require a strict released APP_VERSION with no local/unknown fallback.
- Fail visibly on malformed required Backblaze bucket/file-version contract data instead of coercing missing values to zero or empty strings.
- Advance the one-time Discovery schema bridge to v4 and correct the Discovery support URL to the canonical repository directory.
- Restore the native daily Total used history example to 30 days.


## 0.1.10

- Perform a one-time MQTT Device Discovery schema reset on upgrade so bucket entities that were already stale before 0.1.9 are removed immediately.
- Re-publish the current Backblaze device discovery after the reset, preserving the existing device identity and entity IDs for buckets that still exist.

## 0.1.9

- Remove Home Assistant MQTT entities for buckets that disappear from Backblaze after a refresh.
- Publish explicit MQTT Device Discovery removal stubs before the updated device config, as required for dynamic component removal.
- Clear retained per-bucket MQTT state topics when buckets are removed to prevent stale broker state.

## 0.1.8

- Promote DigitalHouses Backblaze App from experimental to stable.
- Deliver the Home Assistant App from the immutable GHCR repository `ghcr.io/digitalhouses/digitalhouses_backblaze_app`.
- Preserve the existing Home Assistant App slug, MQTT device identity, entity IDs, configuration, and persistent `/data` state.

## 0.1.7

- Replace the custom mini-graph-card daily storage chart with Home Assistant's native statistics-graph.
- Render Total used as daily max bars for the last 10 days.
- Allow the chart to render naturally while history is still sparse on a new installation.

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
