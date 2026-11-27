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

## DH Sync 0.6 canonical resources

Recorder publishes a retained QoS 1 product source on each MQTT
connect/reconnect at `DigitalHouses/Global/digitalhouses_recorder_app/sync`.
The JSON contains `schema`, `product_id`, `type`, `version`,
`repository`, `product_path`; the running version is informational.

The canonical resources are:

- [English view](dashboards/en/10_recorder.yaml) and [Russian view](dashboards/ru/10_recorder.yaml), both with stable `path: recorder`. DH Sync 0.6.5 selects Russian; the English view can be imported manually.
- [Common Recorder package](packages/common/dh_recorder_app.yaml).
- Optional [English](packages/locales/en/dh_recorder_app_notification_package.yaml) and [Russian notification packages](packages/locales/ru/dh_recorder_app_notification_package.yaml) for sites with the local notification script.

DH Sync discovers canonical YAML from the repository default branch.
Dashboard placement is owned by DH Sync, not the Recorder App. Resource changes
must remain compatible with installed App versions. DH Sync is optional.
See the [current standard](../docs/standards/DH_SYNC_DEVELOPER_STANDARD.md).

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

## Compact status and control card

The canonical Recorder device also exposes the App-owned UI operation contract:

```text
sensor.dh_recorder_app_card
button.dh_recorder_app_check_updates
sensor.dh_recorder_app_latest_version
binary_sensor.dh_recorder_app_update_available
```

The existing `button.dh_recorder_app_db_refresh` remains the authoritative full
refresh control. Its execution is surfaced through `sensor.dh_recorder_app_card`
as `running -> success/error` with operation timestamps and duration.

Release checks query published stable GitHub Releases for tags matching
`digitalhouses_recorder_app-vMAJOR.MINOR.PATCH`. Drafts, prereleases and other
product tags are ignored. The same isolated check runs on demand and every
24 hours; a GitHub/API failure does not affect Recorder monitoring.

App installation and restart remain Supervisor-owned. The maintained compact
card uses the standard Supervisor update entity with backup-before-update and
`hassio.app_restart`; the Recorder App does not gain additional Supervisor
permissions.

## Database support

- SQLite: read-only default Home Assistant Recorder database.
- PostgreSQL: manual database connection.
- MariaDB Supervisor App: automatic MySQL service discovery.
- External MariaDB: manual database connection.

`sensor.dh_recorder_app_database_type` exposes the configured database engine.

Required static database identity consists of:

- database name;
- database user (not applicable to SQLite);
- database version.

All applicable values share a dedicated availability gate. If one cannot be read,
the static DB diagnostics stay unavailable instead of receiving a fabricated
fallback.

Database connectivity has a separate first-observation availability gate.
Before the first real connection attempt, `binary_sensor.dh_recorder_app_db_connected`
does not claim an OFF state.

Recorder writing requires a successful current DB observation. A DB read
failure therefore makes Recorder-writing data unavailable instead of changing
it to synthetic `false`.


## SQLite read-only operation

The App mounts Home Assistant configuration at `/homeassistant` read-only and opens
`home-assistant_v2.db` using Python sqlite3 with URI `mode=ro`, query-only mode,
normal WAL locking, a short busy timeout and a two-second query progress-handler
budget. A missing file is never created. Live WAL/SHM sidecars must be readable
while Recorder is operating; startup may temporarily fail if they are absent.
No immutable flag, checkpoint, schema or data writes are used. Connections are
closed after each query, including on errors. Query timeout limits are best-effort
at the SQLite VM level, not a hard OS I/O deadline.

The Top-N query aggregates metadata IDs before joining names. It uses the existing
Recorder indexes and does not create indexes. Expensive queries can be interrupted
on a large or busy database. Successful metric-group timestamps and previous
results remain available; no failed query publishes a fabricated count. The WAL
size is separate from the main database size. An inactive leftover SQLite file
cannot be distinguished reliably by its presence; select the actual Recorder
database engine. Recorder-write health is derived from its newest state.

## Timezone ownership

Recorder App has no user-configurable timezone. At startup, `run.sh` reads the
Home Assistant Supervisor timezone through `bashio::supervisor.timezone` and
exports it as `TZ`. Local-hour, previous-hour, local-day and previous-day
boundaries all use that authoritative timezone. The App converts those local boundaries to Unix epoch
values before querying Recorder, so SQLite, MariaDB and PostgreSQL use the same numeric
`last_updated_ts` ranges and do not depend on the database session timezone. There
is no silent UTC fallback.

## Recorder count metrics

Recorder row counts exposed for UI graphs are scalar-only sensors: their
changing data is carried only in the entity state, never in dynamic JSON
attributes. Counts are normalized to thousands with one decimal place.

- `db_current_hour_records`: since the start of the current local hour, `K records`;
- `db_today_records`: since local midnight, `K records`;
- `db_records`: all retained Recorder rows, `K records`.

The current-hour and current-day counters refresh every five minutes. Total
retained-row count remains in the hourly slow group.

For Recorder activity bar charts, use the live period counters directly:
`db_current_hour_records` grouped by hour and `db_today_records` grouped by
date. The canonical Lovelace view uses `mini-graph-card` with
`aggregate_func: delta`; the current incomplete period remains visible and
empty history buckets render as zero.

## Storage monitoring

When storage monitoring is enabled:

- `sensor.dh_recorder_app_db_disk_free` — free filesystem space in GB;
- `sensor.dh_recorder_app_db_disk_used` — used filesystem space in GB;
- `sensor.dh_recorder_app_db_disk_total` — total filesystem size in GB;
- `sensor.dh_recorder_app_db_disk_used_percentage` — used percentage.

### Automatic

SQLite reads filesystem metrics via `statvfs` on the database directory. No SSH is required.

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

#### Standard SSH storage account (new sites)

For external PostgreSQL/MariaDB running on a Linux host or LXC, create
the dedicated `dh_recorder` account **inside that database host/container**,
not on the Proxmox host. Run the repo-maintained setup script as root:

```bash
curl -fsSLo /tmp/dh-recorder-storage-user.sh \
  https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_recorder_app/scripts/create_storage_ssh_user.sh &&
bash /tmp/dh-recorder-storage-user.sh
```

The script creates a normal Linux login with its own group, asks interactively
for a password (without printing or storing it), and verifies `df -h /` using
that account. It does not grant sudo/root, change PostgreSQL, or modify
the SSH daemon.

The script is **idempotent**: an existing `dh_recorder` account is left
unchanged. To intentionally change its password, run:

```bash
bash /tmp/dh-recorder-storage-user.sh --reset-password
```

Recorder App configuration for an external database:

| Option | Value |
| --- | --- |
| `storage.source` | `ssh` |
| `storage.ssh_host` | Database host IP or empty (reuse DB host) |
| `storage.ssh_port` | `22` |
| `storage.ssh_username` | `dh_recorder` |
| `storage.ssh_password` | Password chosen during provisioning |
| `storage.path` | Empty (automatic detection) |

SSH must already be running on the database host and allow password
authentication for the dedicated account. The setup script intentionally
does not weaken or override the site's SSH security policy.
Check SSH access separately if the App reports authentication errors.
Use the password for the **Linux SSH account**, never the PostgreSQL
database password.

### Disabled

Disabled omits the four storage entities.

## Publishing and polling

`number.dh_recorder_app_publish_interval_minutes` controls Recorder health/state refresh and retained MQTT state publication. Runtime values are migrated from the old optional Supervisor keys to `/data/runtime_settings.json` and updated through MQTT number entities without restart. The disk threshold and all user values survive migration. Expensive operations are rate-limited.

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

`number.dh_recorder_app_top_entities_limit` controls both rankings. It defaults to `10` and accepts
values from `1` through `100`. The SQL query itself uses this limit, so a
larger user-selected value changes both query result size and the published
ranking payload.

Ranking sensors are presentation data sources for the Top entities tables. Their
state (`top_records`) and every `top_entities[].records` value use absolute
Recorder row counts with the `records` unit; they are not scaled to thousands.
Each `top_entities[]` item also contains `share_percent`, calculated by the
database against all Recorder rows in the same ranking window before the Top-N
limit is applied. The 24-hour ranking is a rolling epoch window
`generated_at - 86400 <= last_updated_ts < generated_at`; it is not tied to a
calendar day or timezone. The all-time share uses all retained Recorder rows.
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

Consent is controlled by the existing Home Assistant App configuration option:

```yaml
telemetry_enabled: false
```

Option description: `Consent to collect statistics (product name, version, installation ID).`

- `false` or an absent key: log `Statistics collection consent not granted. Stopping application.` and stop before creating DB, MQTT or telemetry clients;
- `true`: normal operation and telemetry;
- upgrades preserve the existing setting; consent is never enabled automatically;
- telemetry server failures do not affect Recorder monitoring.

Persistent state after consent:

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

- default OFF (runtime blocked until consent);
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


## Canonical Home Assistant entities

Core diagnostics and controls include:

| Entity ID | Purpose |
| --- | --- |
| `sensor.dh_recorder_app_version` | Running Recorder App release |
| `sensor.dh_recorder_app_started_at` | Current App process start timestamp |
| `sensor.dh_recorder_app_database_type` | SQLite, PostgreSQL or MariaDB |
| `sensor.dh_recorder_app_db_start` | Earliest retained Recorder state |
| `sensor.dh_recorder_app_db_last` | Latest Recorder state |
| `sensor.dh_recorder_app_db_depth` | Retained history depth |
| `sensor.dh_recorder_app_db_current_hour_records` | Recorder writes since the start of the current local hour, K records |
| `sensor.dh_recorder_app_db_today_records` | Recorder writes since local midnight, K records |
| `sensor.dh_recorder_app_db_records` | Total Recorder state rows, K records |
| `sensor.dh_recorder_app_db_size` | Database size |
| `sensor.dh_recorder_app_db_version` | Database server/version |
| `sensor.dh_recorder_app_db_name` | Database name reported by the server |
| `sensor.dh_recorder_app_db_user` | Database user reported by the server (not applicable to SQLite) |
| `binary_sensor.dh_recorder_app_db_connected` | Database connectivity after the first real observation |
| `binary_sensor.dh_recorder_app_recorder_writing` | Recorder write activity |
| `sensor.dh_recorder_app_db_last_age` | Age of the latest Recorder state |
| `sensor.dh_recorder_app_db_top_entities_24h` | Top Recorder entities for 24h |
| `sensor.dh_recorder_app_db_top_entities_all_time` | Top Recorder entities across retained history |
| `button.dh_recorder_app_db_refresh` | Full on-demand refresh |
| `sensor.dh_recorder_app_card` | Compact-card operation state and timing |
| `button.dh_recorder_app_check_updates` | Check the latest published stable Recorder App release |
| `sensor.dh_recorder_app_latest_version` | Latest published stable Recorder App version |
| `binary_sensor.dh_recorder_app_update_available` | Stable Recorder App update availability |
| `sensor.dh_recorder_app_db_last_refresh` | Last successful full manual refresh |
| `number.dh_recorder_app_db_disk_usage_threshold` | App-owned storage threshold |
| `number.dh_recorder_app_publish_interval_minutes` | Health check interval |
| `number.dh_recorder_app_recorder_stale_seconds` | Recorder stale threshold |
| `number.dh_recorder_app_top_entities_limit` | Ranking size |
| `sensor.dh_recorder_app_db_wal_size` | SQLite WAL physical size (MiB; SQLite only) |
| `sensor.dh_recorder_app_db_medium_observed_at` | Last successful period counter collection |
| `sensor.dh_recorder_app_db_slow_observed_at` | Last successful history collection |
| `event.dh_recorder_app_diagnostic` | Machine transition events |
| `button.dh_recorder_app_delete_telemetry` | Authenticated deletion of this installation's telemetry record |

When storage monitoring is enabled:

- `sensor.dh_recorder_app_db_disk_free`
- `sensor.dh_recorder_app_db_disk_used`
- `sensor.dh_recorder_app_db_disk_total`
- `sensor.dh_recorder_app_db_disk_used_percentage`

## Contract Data behavior

Required product facts are validated before publication.

- Version is a strict semantic release value and is shared by the Version sensor, `device.sw_version` and `origin.sw_version`.
- Started at is created once per App process and is timezone-aware ISO8601.
- Database type is required configuration-derived state.
- Database name, applicable database user and database version are available only after all required static database fields were read successfully. SQLite has no database user.
- DB connectivity remains unavailable until the first actual connection observation.
- Recorder-writing state is not synthesized as `false` when DB state is unknown.
- Event payloads are validated by event-specific required-field contracts.

Optional metrics may remain absent/null where their schema allows it, for example when Recorder contains no state rows yet.

## Metric collection schedule

Recorder health uses the MQTT number `number.dh_recorder_app_publish_interval_minutes`, default one minute. The other runtime numbers set the stale threshold (300 seconds), ranking size (10) and disk threshold (80%). Existing configuration values migrate to `/data/runtime_settings.json` before deprecated options are removed. Settings are applied without an App restart; ranking size takes effect at the next scheduled collection or manual refresh. Expensive work is rate-limited:

| Metric group | Interval |
| --- | ---: |
| Recorder health/latest state | Configured publish interval |
| Database size/current record counters | 5 minutes |
| Storage metrics | 5 minutes |
| History depth/total records | 1 hour |
| Top entities — 24h | 1 hour |
| Top entities — all retained history | 1 day |
| Static database information | Startup/reconnect until successful |

The five-minute database metric group is aligned to local five-minute clock boundaries after its immediate startup collection. The hourly history-depth/total-record group is aligned to the local top of the hour instead of drifting from App startup time.

A manual refresh collects every enabled group immediately without changing the normal background schedule.

For Recorder activity bar charts, use the live period counters directly:
`db_current_hour_records` grouped by hour and `db_today_records` grouped by
date. The maintained dashboard uses `mini-graph-card` with
`aggregate_func: delta`, which keeps the current incomplete hour/day visible
while empty history buckets render as zero.

Top-entity ranking rows include the absolute record count and the entity's percentage
share of all Recorder rows in the same ranking window. The 24-hour ranking uses a
rolling `now - 24h .. now` epoch window; the all-history ranking uses all retained
Recorder rows.

## Configuration examples

SQLite (fresh-install default):

```yaml
database_type: sqlite
storage:
  source: automatic
telemetry_enabled: false
```

Enable telemetry only after reviewing the current policy, otherwise the App does not start.
The unused PostgreSQL and MariaDB groups may be left empty. No credentials
are needed for SQLite. Supervisor may display unused optional fields in its
configuration UI.

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

## Backup and restore

Product-persistent state lives under `/data`, including telemetry identity, runtime settings, SSH known-host state where applicable and HA/MQTT migration state. It is App data, not a container image copy.

Production image delivery is external through versioned GHCR releases. Release automation records the immutable image digest and source merge commit, so a historical App release can resolve its historical registry image rather than embedding a duplicate image in App backup data.

HA/MQTT cleanup was enabled only after live partial App backup/restore acceptance confirmed persistent telemetry identity under `/data`.

## Security

The App does not require privileged container access, Docker socket access or a
Home Assistant API token. SQLite requires the read-only Home Assistant
configuration-directory mount declared in the App manifest; it reads the
standard Recorder database and its WAL/SHM sidecars.
Database and SSH credentials remain in the App configuration and are never
published to MQTT or telemetry. Use least-privileged database and SSH accounts.

## HA/MQTT identity migration

Release 0.1.15 provided the controlled compatibility bridge from the released
legacy contract to the canonical Recorder App identity. Live acceptance
confirmed the canonical device/entities, local package migration, telemetry,
and App-data backup/restore before cleanup.

Release 0.1.16 completes that migration. Runtime publication and command/event
handling are canonical-only:

```text
MQTT base:    DigitalHouses/Global/digitalhouses_recorder_app
device ID:    digitalhouses_recorder_app
entity prefix dh_recorder_app
```

On the first 0.1.16 MQTT connection, the App removes retained state under the
former `DigitalHouses/Global/db_monitoring` namespace and publishes an empty
retained Discovery payload for `digitalhouses_db_monitoring`. Each retained
delete uses QoS 1 and must be acknowledged by the broker before cleanup is
marked complete.

Migration state is persisted in:

```text
/data/ha_mqtt_identity_migration.json
```

After the marker reaches `phase=completed`, rolling back to bridge release
0.1.15 does not resurrect the legacy identity. Releases 0.1.14 and older
predate this completed-marker behavior and are not safe rollback targets after
cleanup.

Historical Supervisor slug migration is separate and remains complete. The
Supervisor slug is:

```text
digitalhouses_recorder_app
```
