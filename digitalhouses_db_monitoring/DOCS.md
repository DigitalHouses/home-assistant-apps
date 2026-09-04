# DigitalHouses DB Monitoring

Monitors the Home Assistant Recorder database and exposes the main database and write-health metrics through MQTT Discovery.

## PostgreSQL

Select `postgresql` and configure the Recorder database connection manually.

Example:

```yaml
database_type: postgresql
postgresql:
  host: 192.168.11.31
  port: 5432
  database: homeassistant
  username: hauser
  password: your_password
publish_interval_minutes: 1
```

## MariaDB

When the official Home Assistant MariaDB App provides the Supervisor `mysql` service, use:

```yaml
database_type: mariadb
mariadb:
  connection: supervisor
  database: homeassistant
publish_interval_minutes: 1
```

The App obtains host, port, username and password from Supervisor automatically.

For an external MariaDB server, select `manual` and provide all connection fields.

## MQTT

MQTT connection details are obtained automatically from the Supervisor `mqtt` service. No MQTT credentials are configured in this App.

## Metrics

The App creates one MQTT device named **DH Recorder Database**. All Home Assistant entity IDs use the `dh_db_*` prefix.

## Publication interval

`publish_interval_minutes` controls how often the App checks Recorder health and publishes the combined MQTT state payload. The default is 1 minute.

Database size and hourly write-rate queries are internally limited to every 5 minutes. Expensive history-depth and total-row-count queries are internally limited to every 60 minutes.

`recorder_stale_seconds` controls how old the newest `states` record may be before `binary_sensor.dh_db_recorder_writing` turns off.

## Timezone

Leave `timezone` empty to use the container timezone when available. Set an explicit IANA timezone such as `Asia/Almaty` if required.
