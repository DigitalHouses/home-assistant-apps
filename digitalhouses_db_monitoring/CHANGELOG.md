# Changelog

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
