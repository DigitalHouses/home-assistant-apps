# Changelog
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
