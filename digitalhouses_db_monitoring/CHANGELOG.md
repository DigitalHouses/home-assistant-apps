# Changelog

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
