# DigitalHouses Internet App — first HAOS test plan

This plan is for the first real installation of the experimental `0.1.0` build from `develop/digitalhouses-internet`.

## 1. Safe first start

Before starting the App:

- set `router_ip` to the actual LAN router address;
- keep `recovery.enabled: false`;
- leave all five `traffic.*` mappings empty;
- set `speedtest.periodic_enabled: false` for the first start;
- confirm an MQTT service is installed and available to Supervisor.

Expected result after start:

- one MQTT device named **DigitalHouses Internet App**;
- all created entity IDs use the `dh_internet_app_` prefix;
- Version is `0.1.0`;
- Started at is a valid timestamp;
- Internet, Google, Cloudflare and Router connectivity update normally;
- no recovery action can execute.

## 2. Manual Speedtest

Press `button.dh_internet_app_run_speedtest`.

Verify:

- status changes to `running`, then `success`;
- Download, Upload and Ping contain numeric values;
- Jitter and Packet loss are populated when supplied by Ookla;
- provider/server/result metadata appear on Speedtest status;
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
- `connection_restored` is emitted.

## 5. Notification presentation

Install exactly one notification locale package.

Verify that `event.dh_internet_app_event` triggers the neutral HA event:

`dh_internet_app_notification`

The reusable package must not call Telegram, `mobile_app`, `write2log` or another site-local delivery mechanism.

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

## 7. Recovery — only after read-only tests pass

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

## 8. Pass criteria

The first HAOS test passes when:

- App installation/start is clean;
- MQTT Discovery creates only canonical entities;
- connectivity, Speedtest, thresholds, Events and current-month outage state work;
- App restart preserves outage/recovery/traffic state correctly;
- optional mappings appear/disappear cleanly;
- switch recovery cannot be left off by a normal Stop/Restart path;
- the reference dashboard and notification package load without legacy Speedtest entities.

Production release remains a separate milestone: immutable GHCR delivery, telemetry integration and release hardening are not required to begin this HAOS functional test.
