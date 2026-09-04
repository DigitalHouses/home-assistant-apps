# DigitalHouses DB Monitoring

DigitalHouses DB Monitoring publishes Home Assistant Recorder database health and storage metrics through MQTT Discovery.

## Database support

- PostgreSQL: manual database connection.
- MariaDB Supervisor App: automatic MySQL service discovery.
- External MariaDB: manual database connection.

## Storage monitoring

The App can publish:

- `sensor.dh_db_disk_free` — free space on the filesystem that stores the Recorder database, in GB.
- `sensor.dh_db_disk_used_percentage` — used disk percentage.

### Automatic

For MariaDB running as a Home Assistant OS App, `Automatic` reads the HAOS data disk metrics from the Supervisor Host API. No SSH configuration is required.

For an external PostgreSQL or MariaDB server, `Automatic` enables SSH storage monitoring when an SSH username and password are configured. If SSH credentials are empty, database monitoring continues normally and storage sensors are not created.

### SSH

For external databases, choose `SSH` and configure a Linux user on the database server. The user only needs permission to log in and run `df`; sudo/root access is not required.

`SSH host` can be left empty to reuse the database host.

`Filesystem path` is optional and acts as a manual override. If it is empty, the App resolves a usable storage path automatically:

1. It first asks the database for its data directory (`SHOW data_directory` for PostgreSQL or `SELECT @@datadir` for MariaDB).
2. If the DB user cannot read that setting, it detects the database path over SSH (`pg_lsclusters` and common PostgreSQL paths, or common MariaDB data paths).
3. If no database-specific path can be detected, it falls back to `/`.

The resolved path is written to the App log. The first SSH host key is stored in `/data/ssh_known_hosts` and is checked on later connections.

### Disabled

Choose `Disabled` to omit the two storage entities.

## Publishing

`Publish interval, min` controls how often Recorder health/state is refreshed and MQTT state is published. More expensive database queries and storage checks are internally rate-limited.

### PostgreSQL cluster selection

When the SSH storage path is left empty, the App checks installed PostgreSQL clusters and selects the **online** cluster whose port matches the configured Recorder database port. Stopped clusters are ignored. If no matching cluster can be identified, the normal fallback detection is used.

## Top Recorder entities

The App publishes two diagnostic ranking sensors:

- `sensor.dh_db_top_entities_24h` — Top 10 entities by number of Recorder state rows during the last 24 hours. Refreshed once per hour.
- `sensor.dh_db_top_entities_all_time` — Top 10 entities across all retained Recorder history. Refreshed once per day.

Both rankings are generated immediately when the App starts. Their sensor state is the record count of the highest-ranked entity. Attributes include `top_entity`, `top_records`, `generated_at`, `period` and `top_10`. The `top_10` attribute is intended for dashboard rendering, for example with a Markdown card.

Ranking payloads use dedicated retained MQTT topics and are published only when a ranking is recalculated (or after MQTT reconnect). This avoids generating a new Home Assistant state write every minute for unchanged ranking attributes.

If a ranking query fails, the previous successful ranking remains published and normal database monitoring continues.
