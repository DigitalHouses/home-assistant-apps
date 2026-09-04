# DigitalHouses DB Monitoring

Monitors the Home Assistant Recorder database and exposes the main database and write-health metrics through MQTT Discovery.

## PostgreSQL

Select `postgresql` and configure the Recorder database connection manually.

Example:

```yaml
database_type: postgresql
postgresql:
  host: 192.168.11.32
  port: 5432
  database: hassio
  username: hauser
  password: your_password
```

## MariaDB

When the official Home Assistant MariaDB App provides the Supervisor `mysql` service, use:

```yaml
database_type: mariadb
mariadb:
  connection: supervisor
  database: homeassistant
```

The App obtains host, port, username and password from Supervisor automatically.

For an external MariaDB server, select `manual` and provide all connection fields.

## MQTT

MQTT connection details are obtained automatically from the Supervisor `mqtt` service. No MQTT credentials are configured in this App.

## Metrics

The App creates one MQTT device named **DH Recorder Database** with `dh_*` entities for database size, history depth, row counts, newest/oldest Recorder records, database metadata, connection state and Recorder write activity.

## Polling

Default intervals:

- fast metrics: 60 seconds;
- medium metrics: 300 seconds;
- slow metrics: 3600 seconds.

`recorder_stale_seconds` controls how old the newest `states` record may be before `binary_sensor.dh_recorder_writing` turns off.

## Timezone

Leave `timezone` empty to use the container timezone when available. Set an explicit IANA timezone such as `Asia/Almaty` if required.
