# Recorder App controlled HA App slug migration

Status: Phase 1 bridge active.

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

## Phase 2 — canonical slug

A subsequent release will switch to:

```yaml
slug: digitalhouses_recorder_app
```

The already-tested importer will validate the bridge bundle, apply legacy App
options through Supervisor, wait for the next canonical App start when required,
restore `ssh_known_hosts`, and write an idempotent completion marker.

Phase 2 is not active in version `0.1.10`.

## Compatibility boundary

Version `0.1.9` does not change:

- MQTT base topic `DigitalHouses/Global/db_monitoring`;
- MQTT device ID `digitalhouses_db_monitoring`;
- MQTT unique IDs;
- existing `dh_db_*` Home Assistant entity IDs;
- Recorder database/storage behavior.

MQTT/device/entity identity migration, if desired, is a separate product
migration and must not be mixed with the Supervisor slug migration.
