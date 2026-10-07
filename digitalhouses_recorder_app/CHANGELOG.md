# Changelog

## 0.1.23
- Add `sensor.dh_recorder_app_db_previous_hour_records` as a scalar `measurement` for the previous completed local hour, calculated from Home Assistant timezone boundaries converted to epoch.
- Keep `db_yesterday_records` as the previous completed local calendar-day measurement and define it, together with the new previous-hour sensor, as the source for Recorder-backed historical bar charts.
- Keep `db_current_hour_records` and `db_today_records` as live period-to-date diagnostics rather than historical chart sources.
- Calculate the previous-hour count inside the existing bounded medium SQL aggregation for both MariaDB and PostgreSQL, without adding a separate database query.
- Add regression coverage for closed previous-hour boundaries, SQL aggregation and MQTT Discovery.

## 0.1.22
- Add `share_percent` to every Top Recorder entity row, calculated directly by MariaDB/PostgreSQL against all rows in the same ranking window before the Top-N limit is applied.
- Make the 24-hour ranking an explicit rolling epoch window `now - 86400 <= last_updated_ts < now`, independent of calendar day and timezone.
- Keep the all-time ranking over all retained Recorder rows and preserve absolute `records` values.
- Add regression coverage for the shared SQL percentage calculation and bounded rolling-24h query.

## 0.1.21
- Restore `db_current_hour_records` and `db_today_records` to `state_class: measurement`; these values are database-computed period measurements, not Home Assistant cumulative counters.
- Use the Home Assistant Supervisor timezone only to calculate local hour/day boundaries, convert those boundaries to Unix epoch, and pass explicit half-open `[start, end)` ranges to both MariaDB and PostgreSQL.
- Aggregate rolling-hour, current-hour and current-day Recorder counts in one bounded SQL scan per refresh, independent of the database server/session timezone.
- Add regression coverage for Asia/Almaty UTC conversion, DST-aware local-day boundaries and backend-neutral epoch SQL.

## 0.1.20
- Mark the current-hour and current-day Recorder row counters as `total_increasing` so Home Assistant treats their hourly/daily drops as counter resets instead of carrying the previous period's maximum into the new period.
- Keep the existing local-time boundary calculations and database queries unchanged; the fix is limited to Home Assistant statistics semantics for these two resettable counters.
- Add regression and product validation coverage for the reset-aware state classes.

## 0.1.19
- Require explicit statistics collection consent via `telemetry_enabled` (product name, version, installation ID) without changing the protocol-v1 payload or transport.
- When `false`, stop Recorder before initializing database/MQTT connections or sending statistics; an explicit `true` allows normal startup. Preserve existing configuration values during upgrades.
- Add CI regression tests covering denied consent, allowed startup, and the configuration contract.

## 0.1.18
- Publish absolute Recorder row counts in both Top entities ranking sensors instead of rounded thousands, so table consumers receive exact values directly from the ranking payload.
- Keep `top_entities_limit` behavior unchanged while changing ranking Discovery units from `K records` to `records`; other graph-oriented Recorder count sensors remain normalized to thousands.

## 0.1.17
- Add scalar-only `sensor.dh_recorder_app_db_current_hour_records` and `sensor.dh_recorder_app_db_today_records`, refreshed with the five-minute medium metrics group.
- Normalize Recorder row-count presentation to thousands: `K records` for counts and `K rec/h` for the rolling-hour rate, including yesterday and ranking values.
- Keep graph-oriented numeric sensors free of dynamic JSON attributes so Recorder history stores only their changing scalar state.
- Add `top_entities_limit` App configuration with default 10 and supported range 1..100; apply the limit in both PostgreSQL/MariaDB ranking SQL and the published ranking snapshot.
- Rename the ranking list attribute from fixed `top_10` to `top_entities` and publish the active `limit`.
- Remove the user `timezone` option; source local timezone from Home Assistant Supervisor through `bashio::supervisor.timezone` with no silent UTC fallback.

## 0.1.16
- Complete the controlled HA/MQTT identity migration and make runtime publication/subscriptions canonical-only.
- Stop publishing the legacy `DigitalHouses/Global/db_monitoring` state/event/control mirror and stop subscribing to legacy command topics.
- On first MQTT connection, delete retained legacy state/availability/ranking/threshold topics and publish an empty retained Discovery payload for `digitalhouses_db_monitoring`.
- Require QoS 1 broker acknowledgement for every retained cleanup publish before writing `phase=completed` to `/data/ha_mqtt_identity_migration.json`.
- Keep cleanup idempotent and retry while MQTT remains connected; a failed cleanup does not advance the migration marker.
- Preserve rollback safety: bridge release 0.1.15 reads the completed marker and does not resurrect legacy identity after cleanup.
- Record completed live acceptance for canonical HA/MQTT identity, protocol-v1 telemetry, authenticated deletion, and partial App backup/restore of persistent telemetry identity.

## 0.1.15
- Start the controlled HA/MQTT identity migration with canonical MQTT base `DigitalHouses/Global/digitalhouses_recorder_app`, device ID `digitalhouses_recorder_app`, canonical `dh_recorder_app_*` entities and canonical unique IDs.
- Keep the released `DigitalHouses/Global/db_monitoring` / `digitalhouses_db_monitoring` / `dh_db_*` contract alive as a temporary bridge, preserving its released unique IDs and command/event topics so existing dashboards and automations can be migrated without interruption.
- Persist HA/MQTT migration state in `/data/ha_mqtt_identity_migration.json`; once a later cleanup release marks migration complete, rollback to this bridge release does not resurrect the legacy identity.
- Add required diagnostic `sensor.dh_recorder_app_version` and `sensor.dh_recorder_app_started_at`; Version, Discovery `device.sw_version` and `origin.sw_version` now share the same strict release value.
- Remove synthetic Version fallbacks and fail visibly when `APP_VERSION` is missing or invalid.
- Add Contract Data validation for required runtime diagnostics, static database identity and event-specific machine payload fields; startup no longer publishes an unobserved synthetic Recorder-writing state.
- Add canonical database-type diagnostic and explicit availability gates for first DB observation and required static DB identity.
- Add immutable production image metadata `ghcr.io/digitalhouses/digitalhouses_recorder_app`; release automation publishes versioned multi-arch GHCR images and digest/commit provenance.
- Add opt-in protocol-v1 telemetry for `digitalhouses_recorder_app`, default OFF, with persistent UUIDv4/token state in `/data/telemetry.json`, immediate first-enable/new-release heartbeat, 24h jittered cadence, one-hour failure backoff, five-second HTTP timeout and authenticated deletion.
- Keep telemetry isolated from Recorder monitoring and restrict the heartbeat payload to protocol fields only; no DB host/name/user, HA identity, hostname, IP, storage path, SSH data or metrics are sent.
- Canonicalize the PostgreSQL client `application_name` to `digitalhouses_recorder_app`.
- Add regression coverage for canonical identity, exact legacy bridge compatibility, diagnostics, Contract Data failures, telemetry persistence/protocol, migration rollback state and immutable image metadata.

## 0.1.14
- Add App-owned `number.dh_db_disk_usage_threshold` with persistent runtime state under `/data`.
- Add `event.dh_db_diagnostic` and event schema v2 for database connectivity, Recorder writing and storage-usage transitions.
- Establish startup baselines without synthetic alert/recovery events.
- Reevaluate storage state immediately when the disk threshold changes.
- Publish current authoritative state before transition events and publish events with QoS 1 / `retain=false`.
- Replace legacy DB Monitoring wording in startup/origin presentation with DigitalHouses Recorder App.
- Keep MQTT base/device identity and all existing `dh_db_*` sensor/binary-sensor IDs unchanged.

## 0.1.13
- Finalize the completed Home Assistant App slug migration after canonical acceptance and removal of the legacy `digitalhouses_db_monitoring` installation.
- Remove the temporary writable `/share` mapping, `DH_SLUG_MIGRATION_MODE`, migration startup/shutdown hooks and slug-migration runtime module.
- Keep the canonical Supervisor slug `digitalhouses_recorder_app` as the permanent App identity.
- Keep MQTT base topic `DigitalHouses/Global/db_monitoring`, MQTT device/unique IDs and all existing `dh_db_*` Home Assistant entities unchanged.
- Leave any already-created migration bundle under `/share` and completed marker under `/data` as inert historical artifacts; runtime no longer reads or writes them.

## 0.1.12
- Close Paramiko SSH command stdin/stdout/stderr streams explicitly before closing the SSH client.
- Prevent the intermittent Paramiko shutdown traceback `AttributeError: 'NoneType' object has no attribute 'time'` after SSH-backed storage collection.
- Keep the canonical Supervisor slug, migration completion state, MQTT/device identity and existing `dh_db_*` entities unchanged.

## 0.1.11
- Complete Phase 2 of the controlled Home Assistant App slug migration by switching the Supervisor slug to `digitalhouses_recorder_app`.
- Import the verified bridge bundle produced by legacy-slug Recorder App 0.1.10 before normal runtime starts.
- Apply migrated App options through Supervisor; when the new options are not yet mounted into `/data/options.json`, stop cleanly once and complete the import on the next canonical App start.
- Restore optional `ssh_known_hosts` only after the migrated options are active, then write the idempotent migration-complete marker.
- Keep MQTT base topic `DigitalHouses/Global/db_monitoring`, MQTT device/unique IDs and all existing `dh_db_*` Home Assistant entities unchanged.
- Keep the legacy `digitalhouses_db_monitoring` installation only as a stopped rollback target during migration acceptance.

## 0.1.10
- Publish the controlled Home Assistant App slug-migration bridge as the first accepted bridge release after the incomplete 0.1.9 delivery attempt.
- Keep the legacy Supervisor slug `digitalhouses_db_monitoring` while exporting `/data/options.json` and optional `/data/ssh_known_hosts` to the verified migration bundle under `/share/digitalhouses_recorder_app/slug-migration-v1/`.
- Refresh the bridge bundle at App startup and graceful shutdown; migration export failures remain isolated from Recorder monitoring.
- Keep MQTT base topic, device identity, unique IDs and existing `dh_db_*` Home Assistant entities unchanged.
- Do not treat 0.1.9 as a production release; its partially published GHCR artifact is intentionally not reused.

## 0.1.9
- Add the controlled bridge phase for the Home Assistant App slug migration from `digitalhouses_db_monitoring` to `digitalhouses_recorder_app`.
- Export `/data/options.json` and optional `/data/ssh_known_hosts` to an atomic SHA-256-validated migration bundle under `/share/digitalhouses_recorder_app/slug-migration-v1/`.
- Refresh the bridge bundle at App startup and graceful shutdown without allowing migration-export failures to interrupt Recorder monitoring.
- Keep MQTT base topic, device identity, unique IDs and existing `dh_db_*` Home Assistant entities unchanged.

## 0.1.8
- Added `sensor.dh_db_last_refresh` with the timestamp of the last successful manual full refresh.
- Added `sensor.dh_db_disk_used` and `sensor.dh_db_disk_total`.
- Storage collection now publishes free, used, total, and used-percentage values for both Supervisor and SSH sources.
- A manual refresh updates `db_last_refresh` only when all enabled refresh groups complete successfully.

## 0.1.7
- Added diagnostic `button.dh_db_refresh` for an on-demand full refresh of DB Monitoring data.
- A manual refresh immediately recollects fast, medium, slow, static, storage, Top Recorder 24h, and Top Recorder all-time data.
- Manual refresh requests are executed by the main application loop so expensive database queries do not block the MQTT callback thread.
- Duplicate refresh requests are ignored while a refresh is already pending or running.
- Existing background polling intervals remain unchanged and are not reset by a manual refresh.

## 0.1.6
- Added `sensor.dh_db_top_entities_24h` with Top 10 Recorder entities for the last 24 hours.
- Added `sensor.dh_db_top_entities_all_time` with Top 10 Recorder entities across retained history.
- Added `top_entity`, `top_records`, `generated_at`, `period` and `top_10` attributes.
- Refresh the 24-hour ranking once per hour and the all-time ranking once per day.
- Ranking failures keep the previous successful MQTT state and do not interrupt core database monitoring.
- Publish rankings on dedicated retained MQTT topics only when recalculated, avoiding minute-by-minute Recorder churn.
## 0.1.5

- Fix PostgreSQL storage autodetection when multiple clusters are installed.
- Select only the online PostgreSQL cluster matching the configured database port.
- Ignore stopped clusters on other ports.

## 0.1.4

- Made `Filesystem path` a true optional override for SSH storage monitoring.
- Added SSH-side PostgreSQL/MariaDB storage path auto-detection when the DB user cannot read the server data directory.
- Added `/` as a safe final fallback and log output showing the resolved storage path.
## 0.1.3

- Added `sensor.dh_db_disk_free`.
- Added `sensor.dh_db_disk_used_percentage`.
- Added automatic HAOS data disk monitoring for Supervisor MariaDB.
- Added SSH disk monitoring for external PostgreSQL and MariaDB databases.
- Added automatic PostgreSQL/MariaDB data directory detection for SSH storage checks.
- Added separate MQTT storage availability tracking.
## 0.1.2

- Renamed the MQTT device to `DH Recorder`.
- Shortened database version values, for example `PostgreSQL 17.5`.
- Retained MQTT state so entities recover immediately after Home Assistant or App restart.

## 0.1.1

- Standardized entity IDs with the `dh_db_*` prefix.
- Improved entity names with the `DB` prefix.
- Replaced technical polling controls with a single publish interval in minutes.

## 0.1.0

- Initial PostgreSQL and MariaDB Recorder monitoring release.
