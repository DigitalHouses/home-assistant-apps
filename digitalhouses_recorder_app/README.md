# DigitalHouses Recorder App

[![CI](https://github.com/DigitalHouses/home-assistant-apps/actions/workflows/validate.yml/badge.svg)](https://github.com/DigitalHouses/home-assistant-apps/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
![Type: Home Assistant App](https://img.shields.io/badge/type-Home%20Assistant%20App-41BDF5.svg)

Home Assistant App for monitoring the health, retained history, write activity, size and storage footprint of the database used by Home Assistant Recorder.

[Quick start](#quick-start) · [Technical documentation](DOCS.md) · [HA/MQTT migration](#hamqtt-identity-migration) · [Changelog](CHANGELOG.md) · [Issues](https://github.com/DigitalHouses/home-assistant-apps/issues)

Canonical product and Home Assistant App identity:

```text
digitalhouses_recorder_app
```

Canonical MQTT/HA identity introduced by the controlled 0.1.15 bridge:

```text
MQTT base:    DigitalHouses/Global/digitalhouses_recorder_app
device ID:    digitalhouses_recorder_app
entity prefix dh_recorder_app
```

![DigitalHouses Recorder dashboard](images/dh_db_monitor.png)

## Quick start

1. In Home Assistant open **Settings → Apps → App store → Repositories**.
2. Add:

```text
https://github.com/DigitalHouses/home-assistant-apps
```

3. Install **DigitalHouses Recorder App**.
4. Select PostgreSQL or MariaDB, configure the database connection, and optionally enable storage monitoring.
5. Start the App. MQTT credentials are obtained from the Home Assistant Supervisor MQTT service.

The production App uses the versioned GHCR image family:

```text
ghcr.io/digitalhouses/digitalhouses_recorder_app
```

## What it monitors

Recorder App publishes one canonical MQTT Discovery device with:

- database connectivity and Recorder write activity;
- earliest/latest retained state and history depth;
- hourly and total Recorder state-row volume;
- database size, type, database name/user and server version;
- previous-day Recorder writes;
- optional filesystem free, used, total and used percentage;
- Top 10 Recorder entities for the last 24 hours and all retained history;
- on-demand full refresh and last successful refresh timestamp;
- App-owned disk-usage threshold;
- machine events for DB/Recorder/storage transitions;
- common runtime diagnostics: App Version and Started at.

## Supported databases

- **PostgreSQL** — manual database connection.
- **MariaDB Supervisor App** — automatic Supervisor MySQL service connection.
- **External MariaDB** — manual database connection.

The App reads Recorder data and database metadata; it does not modify Recorder tables.

## Canonical Home Assistant entities

Core diagnostics and controls include:

| Entity ID | Purpose |
| --- | --- |
| `sensor.dh_recorder_app_version` | Running Recorder App release |
| `sensor.dh_recorder_app_started_at` | Current App process start timestamp |
| `sensor.dh_recorder_app_database_type` | PostgreSQL or MariaDB |
| `sensor.dh_recorder_app_db_start` | Earliest retained Recorder state |
| `sensor.dh_recorder_app_db_last` | Latest Recorder state |
| `sensor.dh_recorder_app_db_depth` | Retained history depth |
| `sensor.dh_recorder_app_db_records_per_hour` | Recorder state rows written during the last hour |
| `sensor.dh_recorder_app_db_records` | Total Recorder state rows, in thousands |
| `sensor.dh_recorder_app_db_size` | Database size |
| `sensor.dh_recorder_app_db_version` | Database server/version |
| `sensor.dh_recorder_app_db_yesterday_records` | Previous local-day Recorder writes |
| `sensor.dh_recorder_app_db_name` | Database name reported by the server |
| `sensor.dh_recorder_app_db_user` | Database user reported by the server |
| `binary_sensor.dh_recorder_app_db_connected` | Database connectivity after the first real observation |
| `binary_sensor.dh_recorder_app_recorder_writing` | Recorder write activity |
| `sensor.dh_recorder_app_db_last_age` | Age of the latest Recorder state |
| `sensor.dh_recorder_app_db_top_entities_24h` | Top Recorder entities for 24h |
| `sensor.dh_recorder_app_db_top_entities_all_time` | Top Recorder entities across retained history |
| `button.dh_recorder_app_db_refresh` | Full on-demand refresh |
| `sensor.dh_recorder_app_db_last_refresh` | Last successful full manual refresh |
| `number.dh_recorder_app_db_disk_usage_threshold` | App-owned storage threshold |
| `event.dh_recorder_app_diagnostic` | Machine transition events |
| `button.dh_recorder_app_delete_telemetry` | Authenticated deletion of this installation's telemetry record |

When storage monitoring is enabled:

- `sensor.dh_recorder_app_db_disk_free`
- `sensor.dh_recorder_app_db_disk_used`
- `sensor.dh_recorder_app_db_disk_total`
- `sensor.dh_recorder_app_db_disk_used_percentage`

## HA/MQTT identity migration

Release 0.1.15 is a controlled compatibility bridge, not a blind rename.

Canonical identity is published as the primary contract. The already released legacy contract is temporarily mirrored so existing installations can move dashboards and automations without interruption:

```text
legacy MQTT base: DigitalHouses/Global/db_monitoring
legacy device ID: digitalhouses_db_monitoring
legacy entities:  dh_db_*
```

The bridge preserves the released legacy MQTT unique IDs, command topics and event topic. Migration state is persisted in:

```text
/data/ha_mqtt_identity_migration.json
```

A later cleanup release is activated only after live acceptance and local references have moved to canonical entities. That release removes retained legacy state, publishes a Discovery tombstone for the legacy device and marks the migration completed. The completed marker prevents rollback to the bridge release from resurrecting legacy discovery.

Historical slug migration is separate and already complete. The Supervisor slug remains:

```text
digitalhouses_recorder_app
```

## Machine events and notifications

Recorder App publishes transient MQTT Events through:

```text
event.dh_recorder_app_diagnostic
```

Event types:

- `db_connection_lost`
- `db_connection_restored`
- `recorder_writing_stopped`
- `recorder_writing_restored`
- `storage_usage_high`
- `storage_usage_normal`

Events use QoS 1 and `retain=false`. State is published before the transition event. The App establishes a startup baseline without synthetic alert/recovery events.

Local Home Assistant notification logic should remain:

```text
machine event
→ trigger.id
→ choose
→ direct action
```

The public product has no dependency on `notify.*`, Telegram, site-specific helpers or any private delivery service.

## Contract Data behavior

Required product facts are validated before publication.

- Version is a strict semantic release value and is shared by the Version sensor, `device.sw_version` and `origin.sw_version`.
- Started at is created once per App process and is timezone-aware ISO8601.
- Database type is required configuration-derived state.
- Database name, database user and database version are considered available only after all required static database fields were read successfully.
- DB connectivity remains unavailable until the first actual connection observation.
- Recorder-writing state is not synthesized as `false` when DB state is unknown.
- Event payloads are validated by event-specific required-field contracts.

Optional metrics may remain absent/null where their schema allows it, for example when Recorder contains no state rows yet.

## Telemetry

Telemetry is opt-in and disabled by default:

```yaml
telemetry_enabled: false
```

When enabled, protocol v1 sends only:

- schema;
- telemetry policy version;
- persistent installation UUID;
- product `digitalhouses_recorder_app`;
- running release version.

It does not send database host/name/user, Home Assistant identity, hostname, IP, storage path, SSH information, metrics or country.

Installation identity and a 256-bit token are stored in:

```text
/data/telemetry.json
```

A first enable or new released version is reported immediately, then approximately every 24 hours with deterministic jitter. Failures are isolated from Recorder monitoring and use one-hour retry backoff. The delete button performs authenticated deletion through the telemetry service.

## Polling strategy

Recorder health uses `publish_interval_minutes`, default one minute. Expensive work is rate-limited:

| Metric group | Interval |
| --- | ---: |
| Recorder health/latest state | Configured publish interval |
| Database size/hourly activity | 5 minutes |
| Storage metrics | 5 minutes |
| History depth/total records | 1 hour |
| Top entities — 24h | 1 hour |
| Top entities — all retained history | 1 day |
| Static database information | Startup/reconnect until successful |

A manual refresh collects every enabled group immediately without changing the normal background intervals.

## Configuration examples

PostgreSQL:

```yaml
database_type: postgresql
postgresql:
  host: "db.example.local"
  port: 5432
  database: homeassistant
  username: recorder_monitor
  password: "CHANGE_ME"
telemetry_enabled: false
```

Supervisor MariaDB:

```yaml
database_type: mariadb
mariadb:
  connection: supervisor
telemetry_enabled: false
```

External MariaDB:

```yaml
database_type: mariadb
mariadb:
  connection: manual
  host: "db.example.local"
  port: 3306
  database: homeassistant
  username: recorder_monitor
  password: "CHANGE_ME"
telemetry_enabled: false
```

## Storage monitoring

Storage collection can be automatic, explicit SSH, or disabled.

For Supervisor MariaDB, automatic mode uses Home Assistant OS host storage information. For external PostgreSQL/MariaDB, storage can be collected through a normal SSH user that can log in and run `df`; root access is not required.

See [Technical documentation](DOCS.md) for path autodetection and PostgreSQL cluster selection.

## Backup and restore

Product-persistent state lives under `/data`, including telemetry identity, runtime threshold, SSH known-host state where applicable and HA/MQTT migration state. It is App data, not a container image copy.

Production image delivery is external through versioned GHCR releases. Release automation records the immutable image digest and source merge commit, so a historical App release can resolve its historical registry image rather than embedding a duplicate image in App backup data.

Backup/restore persistence still requires live acceptance for each migration release before cleanup is declared complete.

## Security

The App does not require privileged container access, Docker socket access, Home Assistant configuration-directory access, `secrets.yaml` or a Home Assistant API token.

Database credentials remain in Home Assistant App configuration and are never published to MQTT or telemetry. Use least-privileged database and SSH accounts that satisfy the documented read-only requirements.

## Support and license

Report reproducible bugs or feature requests through repository [Issues](https://github.com/DigitalHouses/home-assistant-apps/issues). Security-sensitive reports follow the repository [security policy](../.github/SECURITY.md).

DigitalHouses Recorder App is provided under the repository [MIT License](../LICENSE).
