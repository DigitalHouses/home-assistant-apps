# Internet App controlled HA App slug migration

Status: completed and retired from current runtime.

Canonical product:

```text
digitalhouses_internet_app
```

Migration:

```text
legacy HA App slug:    digitalhouses_internet
canonical target slug: digitalhouses_internet_app
```

The repository directory and product/release/telemetry identities are already canonical. MQTT and Home Assistant identities remain `dh_internet_app`; this migration changes only the Supervisor App identity.

The migration was completed and accepted on the canonical installation. Version `0.1.16` removed the temporary migration runtime, writable `/share` mapping and migration environment mode from the current App. This document is retained as the historical migration record; releases `0.1.12`–`0.1.15` contain the implementation used during the transition.

## Why this is a controlled reinstall

Home Assistant Supervisor keys an installed App and its persistent `/data` by the App slug. Changing `config.yaml -> slug` therefore creates a different installed App instead of renaming the existing installation.

The migration must not depend on copying Docker/container internals and must not create new MQTT or Home Assistant entity identities.

## Phase 1 — bridge release

The final release using the legacy slug:

```text
digitalhouses_internet
```

mounts Home Assistant `/share` read-write and automatically writes:

```text
/share/digitalhouses_internet_app/slug-migration-v1/bundle.tar.gz
```

The bundle is atomic, mode 0600 where supported, and contains only the explicit persistent contract:

```text
/data/options.json
/data/telemetry.json
/data/runtime/outages.json
/data/runtime/speedtest.json
/data/runtime/thresholds.json
/data/runtime/traffic.json
/data/runtime/recent_results.json
/data/runtime/servers.json
/data/runtime/recovery.json
/data/runtime/discovery.json
```

Missing optional state files are allowed. `options.json` is mandatory.

The bridge refreshes the bundle at startup and again during graceful shutdown. The shutdown snapshot is the migration source of truth.

The manifest records:

- canonical product ID;
- source and target slug;
- bridge App version;
- export timestamp;
- exact file list, sizes and SHA-256 hashes;
- best-effort Supervisor settings: boot mode, auto-update and watchdog.

## Phase 2 — canonical slug release

Version `0.1.13` introduced the first canonical slug release. Version `0.1.14` fixed the import sequencing for Supervisor's options lifecycle. Version `0.1.15` makes completed migration state authoritative after rollback refreshes the shared bridge bundle. The canonical App uses:

```yaml
slug: digitalhouses_internet_app
```

During the migration window, canonical releases kept the `/share` migration mapping and ran in `DH_SLUG_MIGRATION_MODE=import`. These temporary controls were removed in `0.1.16` after acceptance.

Before normal runtime starts it:

1. detects the bridge bundle;
2. validates product, source slug, target slug, member allowlist and every SHA-256;
3. compares the mounted `/data/options.json` with the bridge options;
4. if they differ, applies the old options through `/addons/self/options`, writes an options-pending marker and stops cleanly;
5. on the next start, verifies that Supervisor mounted the expected options;
6. atomically restores all other App-owned state;
7. writes the completed import marker under the new `/data`;
8. starts the normal Internet App runtime.

If the options were already persisted by the failed `0.1.13` attempt, `0.1.14` detects that state and proceeds directly to final import without applying them again.

A successfully completed migration is never applied twice. Once the completed marker is valid, the canonical App ignores later bridge bundle changes entirely; this is required because a rollback start/stop of legacy `0.1.12` regenerates that shared bundle with a new timestamp/hash.

A fresh canonical installation starts normally. From `0.1.16` onward there is no migration-bundle handling in the production runtime.

## Telemetry identity

`/data/telemetry.json` is copied byte-for-byte. Therefore the canonical-slug App keeps the same:

- `installation_id`;
- installation token;
- telemetry enable state;
- last success/attempt scheduling state.

The new product version is still reported normally after migration because the telemetry client detects the release-version change.

## Historical operator sequence

1. Update the legacy-slug App to the bridge release.
2. Confirm the bridge log reports a ready migration bundle.
3. Create a Home Assistant backup while the legacy App is still installed.
4. Stop the legacy App. Do not uninstall it.
5. Confirm the shutdown log reports a refreshed migration bundle.
6. Reload the App store and install/update the canonical-slug App `digitalhouses_internet_app` to version `0.1.15`.
7. Start it. If the log says migrated options were applied and a restart is required, start the App once more. Then verify the log reports successful bundle import before normal runtime.
8. Verify options, telemetry identity, Internet state, thresholds, outage/traffic history and HA/MQTT entities.
9. Restart the canonical App once and verify the bundle is not re-imported.
10. Create a backup of the canonical-slug App and verify restore.
11. Prove rollback once by stopping the canonical App and starting the still-installed legacy bridge App, then stop legacy again and return to canonical. The legacy bridge will refresh the shared bundle; canonical must ignore it because migration is already complete.
12. Only after acceptance uninstall the stopped legacy App.

The two Apps must never run at the same time because they intentionally share the same MQTT client/device/entity identities.

## Historical rollback

Before acceptance, rollback is deliberately simple:

1. stop the canonical-slug App;
2. start the still-installed legacy bridge App.

No MQTT/entity migration is required because both releases use the same `dh_internet_app` namespace.

The pre-migration Home Assistant backup is disaster-recovery protection, not the primary immediate rollback mechanism.

## Recorded acceptance criteria

Migration is complete only after verifying:

- canonical App slug is installed;
- legacy App remains stopped during verification;
- options are equal to the bridge export;
- all explicit `/data` state is restored;
- telemetry installation ID/token are unchanged;
- no duplicate telemetry installation appears server-side;
- existing `dh_internet_app_*` entities remain the same identities;
- new canonical-slug backup restores successfully;
- rollback to the stopped bridge App is proven before legacy uninstall.

## Cleanup release

Version `0.1.16` finalized the migration cleanup:

- removed the writable `/share` mapping;
- removed `DH_SLUG_MIGRATION_MODE`;
- removed `slug_migration.py` and migration-only tests;
- removed bridge export hooks from shutdown;
- kept canonical slug `digitalhouses_internet_app` as the only supported current App identity;
- kept MQTT/device/entity identities unchanged under `dh_internet_app`.
