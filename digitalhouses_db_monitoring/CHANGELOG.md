# Changelog

## 0.1.1

- Standardized entity names with the `DB` prefix.
- Renamed the default Recorder writing entity ID to `binary_sensor.dh_db_recorder_writing`.
- Replaced technical fast/medium/slow polling options with `publish_interval_minutes`.
- Kept database-intensive query cadences internal at 5 and 60 minutes.
- Added automatic cleanup of the legacy `poll` option during upgrade.

## 0.1.0

- Initial Home Assistant OS App implementation.
- PostgreSQL Recorder monitoring.
- MariaDB monitoring with Supervisor service discovery or manual connection.
- MQTT Device Discovery with stable `dh_*` entity IDs.
- Fast, medium and slow polling groups.
- Database connection and Recorder write-health binary sensors.
