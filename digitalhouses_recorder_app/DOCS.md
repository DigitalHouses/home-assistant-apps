# DigitalHouses Recorder App — Technical documentation

Recorder App publishes Home Assistant Recorder database health, storage metrics, runtime settings and machine events through MQTT Discovery.

## Runtime identity

Canonical product:

```text
digitalhouses_recorder_app
```

Canonical MQTT/Discovery contract:

```text
MQTT base:     DigitalHouses/Global/digitalhouses_recorder_app
Discovery:     homeassistant/device/digitalhouses_recorder_app/config
device ID:     digitalhouses_recorder_app
entity prefix: dh_recorder_app
```

Release 0.1.15 was the temporary compatibility bridge from
`DigitalHouses/Global/db_monitoring` / `digitalhouses_db_monitoring` /
`dh_db_*` to the canonical contract.

Release 0.1.16 is canonical-only at runtime. On its first MQTT connection it
deletes the retained legacy state topics and tombstones the retained legacy
Discovery payload. Cleanup publishes use QoS 1 and must receive broker ACKs
before the migration marker is advanced to `phase=completed`.

Migration state:

```text
/data/ha_mqtt_identity_migration.json
```

The completed marker is idempotent. Rolling back from 0.1.16 to bridge release
0.1.15 does not reactivate the legacy mirror. Releases 0.1.14 and older predate
the completed-marker behavior and are not safe rollback targets after cleanup.

## Common runtime diagnostics

Recorder App exposes:

```text
sensor.dh_recorder_app_version
sensor.dh_recorder_app_started_at
```

`Version` must equal the App release version used by both
`device.sw_version` and `origin.sw_version`. A missing or non-semver
`APP_VERSION` is a startup error.

`Started at` is generated once when the Python App process starts. It is a
timezone-aware ISO8601 timestamp with Home Assistant `device_class: timestamp`.

## Database support

- PostgreSQL: manual database connection.
- MariaDB Supervisor App: automatic MySQL service discovery.
- External MariaDB: manual database connection.

`sensor.dh_recorder_app_database_type` exposes the configured database engine.

Required static database identity consists of:

- database name;
- database user;
- database version.

Those three values share a dedicated availability gate. If one cannot be read,
the static DB diagnostics stay unavailable instead of receiving a fabricated
fallback.

Database connectivity has a separate first-observation availability gate.
Before the first real connection attempt, `binary_sensor.dh_recorder_app_db_connected`
does not claim an OFF state.

Recorder writing requires a successful current DB observation. A DB read
failure therefore makes Recorder-writing data unavailable instead of changing
it to synthetic `false`.


## Timezone ownership

Recorder App has no user-configurable timezone. At startup, `run.sh` reads the
Home Assistant Supervisor timezone through `bashio::supervisor.timezone` and
exports it as `TZ`. Local-hour, local-day and previous-day boundaries all use
that authoritative timezone. There is no silent UTC fallback.

## Recorder count metrics

Recorder row counts exposed for UI graphs are scalar-only sensors: their
changing data is carried only in the entity state, never in dynamic JSON
attributes. Counts are normalized to thousands with one decimal place.

- `db_records_per_hour`: rolling last 60 minutes, `K rec/h`;
- `db_current_hour_records`: since the start of the current local hour, `K records`;
- `db_today_records`: since local midnight, `K records`;
- `db_yesterday_records`: previous local calendar day, `K records`;
- `db_records`: all retained Recorder rows, `K records`.

The rolling-hour/current-hour/current-day counters refresh every five minutes.
Total and previous-day counters remain in the hourly slow group.

## Storage monitoring

When storage monitoring is enabled:

- `sensor.dh_recorder_app_db_disk_free` — free filesystem space in GB;
- `sensor.dh_recorder_app_db_disk_used` — used filesystem space in GB;
- `sensor.dh_recorder_app_db_disk_total` — total filesystem size in GB;
- `sensor.dh_recorder_app_db_disk_used_percentage` — used percentage.

### Automatic

For MariaDB running as a Home Assistant OS App, Automatic reads Home Assistant
OS data-disk metrics from the Supervisor Host API. No SSH configuration is
required.

For an external PostgreSQL or MariaDB server, Automatic enables SSH storage
monitoring only when SSH credentials are supplied. Without them, database
monitoring continues and storage entities are omitted.

### SSH

For external databases, choose SSH and configure a normal Linux user that can
log in and run `df`; sudo/root access is not required.

`SSH host` may be empty to reuse the database host.

`Filesystem path` is an optional override. If empty, Recorder App:

1. asks the database for its data directory;
2. if necessary, detects a database path over SSH;
3. if no database-specific path is available, uses `/` as the explicit
   filesystem fallback for the storage collector.

The first SSH host key is stored in `/data/ssh_known_hosts` and verified on
later connections.

### Disabled

Disabled omits the four storage entities.

## Publishing and polling

`publish_interval_minutes` controls Recorder health/state refresh and retained
MQTT state publication. Expensive operations are rate-limited.

### PostgreSQL cluster selection

When SSH storage path is empty, the App selects the online PostgreSQL cluster
whose port matches the configured Recorder connection. Stopped clusters are
ignored.

## Top Recorder entities

Canonical ranking sensors:

- `sensor.dh_recorder_app_db_top_entities_24h`;
- `sensor.dh_recorder_app_db_top_entities_all_time`.

The 24-hour ranking refreshes hourly. All-time ranking refreshes daily. Each
uses a dedicated retained MQTT topic and is republished after MQTT reconnect.

`top_entities_limit` controls both rankings. It defaults to `10` and accepts
values from `1` through `100`. The SQL query itself uses this limit, so a
larger user-selected value changes both query result size and the published
ranking payload.

Ranking sensors are presentation data sources for the Top entities tables. Their
state (`top_records`) and every `top_entities[].records` value use absolute
Recorder row counts with the `records` unit; they are not scaled to thousands.
The payload also includes `limit`, `top_entity`, `generated_at` and `period`.

A ranking query failure preserves the previous successful retained ranking.
The DB availability topic still distinguishes a current DB outage from a fresh
ranking observation.

## Runtime disk threshold

Canonical control:

```text
number.dh_recorder_app_db_disk_usage_threshold
```

Its value is persisted in:

```text
/data/runtime_settings.json
```

Contract:

- default: 80%;
- minimum: 1%;
- maximum: 98%;
- step: 1%;
- invalid persisted state is an explicit runtime-settings error;
- changing the Number reevaluates the latest storage measurement immediately.

During the historical 0.1.15 bridge the released legacy Number and its MQTT command/state topics were mirrored. Release 0.1.16 no longer subscribes to or publishes those legacy topics.

## Machine event contract

Canonical event entity/topic:

```text
event.dh_recorder_app_diagnostic
DigitalHouses/Global/digitalhouses_recorder_app/event/diagnostic
```

Event schema version: `2`.

Supported event types:

- `db_connection_lost`
- `db_connection_restored`
- `recorder_writing_stopped`
- `recorder_writing_restored`
- `storage_usage_high`
- `storage_usage_normal`

Common required event fields:

- `schema_version`;
- `event_type`;
- timezone-aware `observed_at`.

Each event type then has its own required fields. Database events require engine
and database identity; restore requires outage duration. Recorder-writing
events require stale threshold while last-record fields are nullable when the
database contains no Recorder rows. Storage events require current usage,
capacity, threshold and cause.

Invalid required fields prevent event publication. Machine events do not
contain localized title/message presentation.

Events use QoS 1 and `retain=false`. Authoritative current state is published
before a transition event.

During the bridge, the same valid machine payload is also published on the
legacy transient event topic. This preserves existing local notification
automations while they move to the canonical event entity.

Local notification architecture remains:

```text
machine event
→ trigger.id
→ choose
→ direct action
```

## Telemetry

Configuration:

```yaml
telemetry_enabled: false
```

State:

```text
/data/telemetry.json
```

The state contains a persistent UUIDv4 installation ID, a persistent random
256-bit-or-greater token, scheduler timestamps and the enabled state. Identity
survives normal restart/update and is part of the App's persistent `/data`.

Protocol-v1 heartbeat payload is exactly:

```json
{
  "schema": 1,
  "telemetry_policy_version": 1,
  "installation_id": "<uuid-v4>",
  "product": "digitalhouses_recorder_app",
  "version": "<release-semver>"
}
```

Client behavior:

- default OFF;
- first enable and new released version: immediate heartbeat;
- normal cadence: 24h with deterministic ±30m jitter;
- failure backoff: approximately one hour;
- HTTP timeout: 5s;
- unreleased/local version: no production telemetry;
- failure is isolated from Recorder monitoring;
- token is used only for authentication and is never logged.

No database host/name/user, Home Assistant UUID, hostname, IP, storage path,
SSH information, metrics or country is sent.

`button.dh_recorder_app_delete_telemetry` performs authenticated
`DELETE /v1/installation`.

## Immutable production delivery

`config.yaml` points Supervisor to:

```text
ghcr.io/digitalhouses/digitalhouses_recorder_app
```

For every App release, repository automation builds architecture-specific
images and then a versioned multi-arch release tag. Existing release image tags
are not overwritten.

GitHub release provenance records:

- product version;
- canonical release tag;
- merge/main commit;
- GHCR version tag;
- immutable image digest.

Container images are registry artifacts, not App `/data`; backups therefore
carry persistent App state rather than a duplicate image copy. Restore of a
historical App release is expected to resolve its historical versioned image
from GHCR and must be verified in live acceptance before migration cleanup.

## Bridge acceptance before cleanup

Before publishing the cleanup release, verify on real Home Assistant OS:

1. App starts from the GHCR production image.
2. Canonical device `digitalhouses_recorder_app` exists.
3. Canonical `dh_recorder_app_*` entities update correctly.
4. Legacy `dh_db_*` entities remain active only as bridge mirrors.
5. Dashboards/packages/automations have been changed to canonical entity IDs.
6. PostgreSQL and MariaDB supported paths still operate.
7. Canonical machine events arrive and local direct notification actions work.
8. Version and Started-at are correct.
9. With telemetry enabled, heartbeat reaches Stats with the same identity after
   restart.
10. Backup/restore preserves telemetry and migration identity.

Only after this acceptance should the cleanup release tombstone retained legacy
topics and remove the legacy Discovery device.

## Public integration boundary

The public App and documentation do not require customer-specific services,
private helper scripts, fixed site IPs or private notification adapters.
