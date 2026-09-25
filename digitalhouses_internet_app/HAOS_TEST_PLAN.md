# DigitalHouses Internet App — HAOS validation plan

This plan covers the current released product and the controlled Home Assistant App slug migration.

## 1. Safe first start

Before starting the App:

- set `router_ip` to the actual LAN router address;
- keep `recovery.enabled: false`;
- leave all five `traffic.*` mappings empty;
- set `speedtest.periodic_enabled: false` for the first start;
- keep `telemetry_enabled: false` for the initial functional test;
- confirm an MQTT service is installed and available to Supervisor.

Expected result after start:

- one MQTT device named **DigitalHouses Internet App**;
- all created entity IDs use the `dh_internet_app_` prefix;
- Version matches the installed released App version;
- Started at is a valid timestamp;
- Internet, Google, Cloudflare and Router connectivity update normally;
- no recovery action can execute.

## 2. Manual Speedtest

Press `button.dh_internet_app_run_speedtest`.

Verify:

- status changes from `idle` to `running`, then returns to `idle`;
- Download, Upload and Ping contain numeric values;
- Jitter and Packet loss are populated when supplied by Ookla;
- `last_result` becomes `success` and provider/server/result metadata appear on Speedtest status;
- Recent Results gains one record.

Change one threshold temporarily so the last result violates it, then restore the threshold.

Verify:

- the matching problem binary changes;
- aggregate Performance problem changes;
- schema-v2 performance events are emitted;
- restoring the threshold clears the current problem without rewriting the historical Recent Results snapshot.

## 3. Server catalog

Press `button.dh_internet_app_refresh_servers`.

Verify:

- the operation happens only on demand;
- Available servers receives a refreshed timestamp and server list;
- no periodic server-catalog polling appears in the App log.

## 4. Outage and persistence

With Recovery still disabled, create a controlled Internet outage.

Verify after the configured failed-check count:

- Internet changes to unavailable;
- one active current-month outage appears;
- the outage has `to: null` while active;
- a `connection_lost` MQTT Event is emitted.

Restart the App while the outage is still active.

Verify:

- the same outage remains active;
- its original/current-month start is preserved;
- no duplicate outage record is created.

Restore Internet.

Verify:

- the outage closes once;
- duration and monthly availability update;
- the Outages sensor still contains every outage recorded in the current month; only dashboard presentation may limit the visible rows;
- `connection_restored` is emitted.

## 5. Notification presentation

Install exactly one local notification package.

Verify that each supported `event.dh_internet_app_event` machine event activates the matching `trigger.id` branch and calls the final delivery action directly. The Russian site package must call `script.write2log` directly; the English example uses `persistent_notification.create`.

Verify there is no secondary `dh_internet_app_notification` event, Notification Envelope, adapter layer or duplicated machine-schema validation. Notification text must read required event data directly from `trigger.to_state.attributes`.

## 6. Optional Router and traffic bindings

Configure only Router WAN/current-rate mappings first.

Verify:

- only the configured optional MQTT entities are created;
- if a mapped source becomes unavailable, the corresponding MQTT entity becomes unavailable and disappears from the reference auto-entities card.

Then configure both cumulative counters together.

Verify:

- first sample is a baseline, not counted usage;
- later counter growth adds only the delta;
- current-month totals grow correctly;
- Traffic history is populated;
- App restart does not duplicate usage.

Remove an optional mapping and restart the App.

Verify the previously discovered optional MQTT component is removed.

## 7. Product telemetry

With `telemetry_enabled: false`, restart the App and verify no heartbeat request is logged or observed.

Then explicitly enable `telemetry_enabled: true` and restart the released App. Verify one heartbeat is accepted immediately by DigitalHouses Stats with product `digitalhouses_internet_app` and the current App version. Restart the App again within one hour and verify it does not create a restart heartbeat storm. After a successful heartbeat, disable telemetry and restart once, then enable it again before the normal 24-hour interval is due: verify exactly one new immediate heartbeat is accepted. If that immediate attempt is forced to fail, restart the App and verify the one-hour failure backoff is preserved.

Press `button.dh_internet_app_delete_telemetry` and verify the server-side installation record is removed. Disable telemetry again if the installation should stop reporting.

## 8. Slug migration bridge

On legacy slug `digitalhouses_internet`, update to bridge release `0.1.12`.

Verify:

- startup log reports `Slug migration bridge bundle ready`;
- `/share/digitalhouses_internet_app/slug-migration-v1/bundle.tar.gz` exists;
- the bundle manifest identifies product `digitalhouses_internet_app`, source slug `digitalhouses_internet`, target slug `digitalhouses_internet_app`, and source version `0.1.12`;
- options, `telemetry.json`, and all existing explicit runtime files are represented by SHA-256 entries;
- telemetry `installation_id` in the source state is recorded for later equality verification.

Create a Home Assistant backup while the bridge App is still installed. Then stop the bridge App cleanly and verify the shutdown log reports `Slug migration bridge bundle refreshed`.

Do not uninstall the bridge App. It remains the immediate rollback target until the canonical-slug installation has passed migration acceptance.

## 9. Canonical slug import

With the legacy `0.1.12` bridge App stopped, reload the App store and install/start `digitalhouses_internet_app` version `0.1.13`.

Verify:

- startup log reports `Slug migration bundle imported successfully: digitalhouses_internet -> digitalhouses_internet_app`;
- the canonical App starts normally after import;
- current App options match the bridge source rather than the package defaults;
- `telemetry.json` keeps the same installation ID and reports version `0.1.13` after its version-change heartbeat;
- outage, recent-results, recovery, server, speedtest, threshold and traffic state are present;
- existing MQTT Discovery entities remain the same `dh_internet_app_*` identities with no duplicates.

Restart the canonical App once.

Verify:

- startup log reports no second state import for the same bundle;
- state created after the first canonical start is not overwritten by the old bridge snapshot.

Before deleting the legacy App, prove rollback once: stop canonical, start legacy `0.1.12`, confirm its prior state is intact, stop legacy again, then start canonical. Never run both simultaneously.

Create a new Home Assistant backup after the canonical App is accepted and verify that backup/restore preserves the canonical slug and installation state.

## 10. Recovery — only after read-only tests pass

Use known-good Home Assistant `button.*` or `switch.*` recovery entities.

First test `smart`:

- Internet down + Router up -> ONT only;
- Internet down + Router down -> Router only;
- no automatic escalation to both devices.

Then test `both`:

- every cycle executes ONT, then Router.

For a switch target:

- confirm the configured power-off interval;
- press Stop Recovery while the switch is off and confirm power is restored;
- repeat with a normal HAOS App Stop/Restart and confirm the switch is restored before the App exits.

Restart the App during an active recovery incident.

Verify:

- Stop Recovery remains stopped for the same outage;
- completed cycle budget is not reset;
- active cooldown is not bypassed;
- a restart between cycles waits through a retry guard before another power action.

## 11. Pass criteria

The first HAOS test passes when:

- App installation/start is clean;
- MQTT Discovery creates only canonical entities;
- connectivity, Speedtest, thresholds, Events and current-month outage state work;
- App restart preserves outage/recovery/traffic state correctly;
- optional mappings appear/disappear cleanly;
- switch recovery cannot be left off by a normal Stop/Restart path;
- the reference dashboard and notification package load without legacy Speedtest entities.

Production release remains a separate milestone: immutable GHCR delivery, telemetry integration and release hardening are not required to begin this HAOS functional test.
