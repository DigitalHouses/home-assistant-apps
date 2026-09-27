# DigitalHouses Internet App — HAOS validation plan

This plan covers the current canonical DigitalHouses Internet App runtime.

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

## 8. Recovery — only after read-only tests pass

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

## 9. Immutable delivery, backup and restore

Install or update the current production App from the DigitalHouses App repository.

Verify:

- the installed App version matches the current released version;
- production delivery uses the published `ghcr.io/digitalhouses/digitalhouses_internet_app:<version>` artifact rather than a locally built production image;
- the GitHub Release records the canonical release tag, exact commit SHA, image name and image digest for the same version;
- the canonical Supervisor slug remains `digitalhouses_internet_app` and existing `dh_internet_app_*` entities are not duplicated or renamed.

Create a Home Assistant backup that includes the App and inspect the App backup.

Verify:

- installation-specific configuration and required persistent `/data` state are present;
- telemetry installation identity/state is included as persistent App data when it exists;
- the backup does not embed a large locally built copy of the reproducible application image.

Restore that current-production backup on a supported Home Assistant system.

Verify:

- the required published registry image can be obtained;
- App options and persistent `/data` state are restored;
- telemetry installation identity and documented runtime state survive the restore;
- the App starts cleanly with the same canonical MQTT/device/entity identities.

Historical-version restore or installing an older App release over a newer one is not part of this general acceptance test unless a separate product-specific migration procedure explicitly requires it.

## 10. Runtime contract compliance

After updating to the current production release, verify:

- Version equals the released App version and no startup log contains an `unknown`/local fallback version;
- immediately after a restart the connectivity entities do not invent a down state before the first successful probe observation;
- after observation, Internet/Google/Cloudflare/Router report the real current result;
- the App starts with the existing canonical `dh_internet_app_*` identities and creates no duplicate device/entities;
- persisted thresholds, outage count/history, recovery state, Recent Results and traffic totals remain intact across restart/update;
- the first start of a new released version may send one telemetry heartbeat with that version, while another ordinary restart does not create a heartbeat storm;
- App logs contain no `Contract data error`, `Configuration error`, traceback or unexpected probe failure.

Corruption and malformed-event negative cases are covered by automated repository tests; do not damage production `/data` files to reproduce them during routine live acceptance.

## 11. Pass criteria

The HAOS validation passes when:

- App installation/start is clean;
- MQTT Discovery creates only canonical entities;
- connectivity, Speedtest, thresholds, Events and current-month outage state work;
- App restart preserves outage/recovery/traffic state correctly;
- optional mappings appear/disappear cleanly;
- switch recovery cannot be left off by a normal Stop/Restart path;
- the reference dashboard and notification package load without legacy Speedtest entities;
- immutable GHCR delivery and current-production backup/restore acceptance pass;
- runtime contract-compliance acceptance passes without changing canonical identities.

Historical Supervisor slug-migration validation is retained separately in `../docs/digitalhouses_internet_app/slug-migration.md`; it is no longer part of the current runtime test path.
