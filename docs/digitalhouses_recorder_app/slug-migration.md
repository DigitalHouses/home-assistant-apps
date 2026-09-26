# Recorder App controlled HA App slug migration

Status: completed; canonical slug accepted and legacy installation removed.

Canonical product:

```text
digitalhouses_recorder_app
```

Migration:

```text
legacy HA App slug:    digitalhouses_db_monitoring
canonical target slug: digitalhouses_recorder_app
```

The repository directory and product/release identities are already canonical.
MQTT, device, unique-id and Home Assistant entity identities intentionally remain
unchanged during this migration.

## Why this is a controlled reinstall

Home Assistant Supervisor keys an installed App and its persistent `/data` by
the App slug. Changing `config.yaml -> slug` creates a different installed App
instead of transparently renaming the existing installation.

The migration therefore uses a bridge release and an explicit persistent-state
bundle. The two App identities must never run at the same time because they
share the same MQTT/device/entity identities.

> Note: version `0.1.9` reached the repository and GHCR build stage but its release transaction did not complete. It is not an accepted production release and must not be deployed. The immutable artifact is left untouched; bridge delivery resumes with `0.1.10`.

## Phase 1 — bridge release 0.1.10

Version `0.1.10` keeps:

```yaml
slug: digitalhouses_db_monitoring
```

and writes:

```text
/share/digitalhouses_recorder_app/slug-migration-v1/bundle.tar.gz
```

The explicit Recorder persistent contract is:

```text
/data/options.json
/data/ssh_known_hosts
```

`options.json` is mandatory. `ssh_known_hosts` is optional.

No telemetry state is included because Recorder App does not yet implement the
production telemetry client.

The bundle is written atomically and its manifest records:

- schema version;
- canonical product ID;
- source and target slugs;
- source App version;
- export timestamp;
- exact file allowlist, sizes and SHA-256 hashes;
- best-effort Supervisor settings: boot mode, auto-update and watchdog.

The bridge refreshes the bundle at startup and again during graceful shutdown.
Export failure is isolated from normal Recorder monitoring and is logged as a
warning.

## Phase 2 — canonical slug release 0.1.11

Version `0.1.11` switches to:

```yaml
slug: digitalhouses_recorder_app
```

and activates:

```text
DH_SLUG_MIGRATION_MODE=import
```

The canonical App validates the bridge bundle created by legacy-slug version
`0.1.10`.

On the first canonical start:

1. validate product/source/target identity and every SHA-256;
2. compare the canonical App's current options with the bridge options;
3. if they differ, apply the bridge options through Supervisor, write the
   pending marker and stop cleanly with restart-required status;
4. on the next start, require the migrated options to be visible in
   `/data/options.json`;
5. restore optional `ssh_known_hosts`;
6. write the completed import marker.

The completed marker is authoritative and makes later starts idempotent.

## Phase 3 — cleanup release 0.1.13

After field acceptance of canonical versions `0.1.11` and `0.1.12`, including
restart idempotency, entity identity checks and an explicit rollback test, the
legacy `digitalhouses_db_monitoring` installation was removed.

Version `0.1.13` removes the temporary migration machinery:

- writable `/share` mapping;
- `DH_SLUG_MIGRATION_MODE`;
- migration startup/shutdown hooks;
- `slug_migration.py` and its dedicated tests.

Existing migration files are deliberately not deleted from user storage.
They are inert historical artifacts and the runtime no longer reads or writes
them.

## Compatibility boundary

Versions `0.1.10` through `0.1.13` do not change:

- MQTT base topic `DigitalHouses/Global/db_monitoring`;
- MQTT device ID `digitalhouses_db_monitoring`;
- MQTT unique IDs;
- existing `dh_db_*` Home Assistant entity IDs;
- Recorder database/storage behavior.

MQTT/device/entity identity migration, if desired, is a separate product
migration and must not be mixed with the Supervisor slug migration.
