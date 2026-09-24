# DigitalHouses Recorder App

[![CI](https://github.com/DigitalHouses/home-assistant-apps/actions/workflows/validate.yml/badge.svg)](https://github.com/DigitalHouses/home-assistant-apps/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
![Type: Home Assistant App](https://img.shields.io/badge/type-Home%20Assistant%20App-41BDF5.svg)

Home Assistant App for monitoring the health, size, retained history, write activity and storage footprint of the database used by Home Assistant Recorder.

[Quick start](#quick-start) · [Technical documentation](DOCS.md) · [Changelog](CHANGELOG.md) · [Issues](https://github.com/DigitalHouses/home-assistant-apps/issues)

![DigitalHouses Recorder dashboard](images/dh_db_monitor.png)

## Quick start

1. In Home Assistant open **Settings → Apps → App store → Repositories**.
2. Add:

```text
https://github.com/DigitalHouses/home-assistant-apps
```

3. Install the Recorder monitoring App, currently listed in Home Assistant package metadata as **DigitalHouses DB Monitoring**.
4. Select `PostgreSQL` or `MariaDB`, configure the database connection, and optionally enable storage monitoring.
5. Start the App. MQTT credentials are obtained automatically from the Home Assistant Supervisor MQTT service.

The public product name is **DigitalHouses Recorder App**. Existing HAOS slug, MQTT topics, device identity and entity IDs remain unchanged for compatibility.

## What it monitors

DigitalHouses Recorder App replaces a collection of manually maintained SQL sensors with one reusable App and one MQTT Discovery device.

It monitors:

- database connectivity and Recorder write activity;
- earliest/latest retained state and history depth;
- state-record volume and hourly write rate;
- database size, database name/user and server version;
- previous-day Recorder writes;
- optional database-filesystem free, used, total and used percentage;
- Top 10 Recorder entities for the last 24 hours and all retained history;
- on-demand full refresh with the timestamp of the last successful refresh.

## Supported databases

- **PostgreSQL** — manual database connection.
- **MariaDB Supervisor App** — automatic Supervisor MySQL service connection.
- **External MariaDB** — manual database connection.

The App reads Recorder data and database metadata; it does not modify Recorder tables.

## MQTT integration

MQTT is obtained through Home Assistant Supervisor service discovery. No MQTT host, username or password is required in the App configuration when a compatible MQTT service is available.

All entities are grouped under the existing Home Assistant device:

```text
DH Recorder
```

## Home Assistant entities

Core entities:

| Entity ID | Purpose |
| --- | --- |
| `sensor.dh_db_app_version` | Running Recorder App release version |
| `sensor.dh_db_started_at` | Timestamp when the current App process started |
| `sensor.dh_db_start` | Earliest retained Recorder state |
| `sensor.dh_db_last` | Latest Recorder state |
| `sensor.dh_db_depth` | Retained history depth in days |
| `sensor.dh_db_records_per_hour` | State records written during the last hour |
| `sensor.dh_db_records` | Total Recorder `states` rows, reported in thousands |
| `sensor.dh_db_size` | Database size |
| `sensor.dh_db_version` | Database server/version |
| `sensor.dh_db_yesterday_records` | State records written during the previous local day |
| `sensor.dh_db_name` | Recorder database name |
| `sensor.dh_db_user` | Database user used by the monitor |
| `binary_sensor.dh_db_connected` | Database connectivity |
| `binary_sensor.dh_db_recorder_writing` | Whether Recorder is actively writing |
| `sensor.dh_db_last_age` | Age of the latest Recorder state |
| `sensor.dh_db_top_entities_24h` | Top Recorder entities during the last 24 hours |
| `sensor.dh_db_top_entities_all_time` | Top Recorder entities across retained history |
| `button.dh_db_refresh` | Run a full on-demand refresh |
| `sensor.dh_db_last_refresh` | Last successful full manual refresh |

When storage monitoring is enabled, the App also exposes:

| Entity ID | Purpose |
| --- | --- |
| `sensor.dh_db_disk_free` | Free filesystem space |
| `sensor.dh_db_disk_used` | Used filesystem space |
| `sensor.dh_db_disk_total` | Total filesystem size |
| `sensor.dh_db_disk_used_percentage` | Used filesystem percentage |

## Polling strategy

Recorder health is refreshed at the configured `publish_interval_minutes` interval, which defaults to one minute. More expensive work is internally rate-limited:

| Metric group | Interval |
| --- | ---: |
| Recorder health/latest state | Configured publish interval |
| Database size/hourly activity | 5 minutes |
| Storage metrics | 5 minutes |
| History depth/total records | 1 hour |
| Top entities — 24h | 1 hour |
| Top entities — all retained history | 1 day |
| Static database information | Startup/reconnect |

A manual refresh collects every enabled group immediately without changing the normal background intervals. The last successful manual refresh timestamp is published on its own retained MQTT topic, so normal one-minute state publications do not generate missing-field template warnings and the last real refresh time is restored after Home Assistant reconnects.

## PostgreSQL configuration

Example:

```yaml
database_type: postgresql

postgresql:
  host: "db.example.local"
  port: 5432
  database: homeassistant
  username: recorder_monitor
  password: "CHANGE_ME"
```

The PostgreSQL account only needs read access to the Recorder tables and metadata required by the monitor.

## MariaDB configuration

For the Home Assistant MariaDB App:

```yaml
database_type: mariadb

mariadb:
  connection: supervisor
```

For an external MariaDB server:

```yaml
database_type: mariadb

mariadb:
  connection: manual
  host: "db.example.local"
  port: 3306
  database: homeassistant
  username: recorder_monitor
  password: "CHANGE_ME"
```

## Recorder health

`binary_sensor.dh_db_recorder_writing` compares the timestamp of the latest Recorder state with the current time.

The default stale threshold is:

```text
300 seconds
```

It can be changed through the App option `recorder_stale_seconds`.

## Storage monitoring

Storage collection can be automatic, explicit SSH, or disabled.

For the Home Assistant MariaDB App, automatic mode uses Supervisor host storage information. For an external PostgreSQL or MariaDB server, storage can be collected over SSH using a normal user that can log in and run `df`; root access is not required.

See [Technical documentation](DOCS.md) for storage path autodetection and PostgreSQL cluster selection details.

## Top Recorder entities

The App publishes two retained ranking sensors:

- `sensor.dh_db_top_entities_24h`;
- `sensor.dh_db_top_entities_all_time`.

Their state is the record count of the highest-ranked entity. Attributes include the current Top 10 list, generation timestamp and period. Ranking failures keep the previous successful ranking and do not interrupt normal Recorder monitoring.

## Security

The App does not require privileged container access, Docker socket access, Home Assistant configuration-directory access, `secrets.yaml`, or a Home Assistant API token.

Database credentials remain in Home Assistant App configuration and are never published to MQTT.

For an external database, use the least-privileged database account and SSH account that satisfy the documented read-only requirements.

## Support and license

Report reproducible bugs or feature requests through the repository [Issues](https://github.com/DigitalHouses/home-assistant-apps/issues). Security-sensitive reports follow the repository [security policy](../.github/SECURITY.md).

DigitalHouses Recorder App is provided under the repository [MIT License](../LICENSE).
