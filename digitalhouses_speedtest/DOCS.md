# DigitalHouses Speedtest — Technical documentation

## Architecture

The App is one long-running Python process based on the Home Assistant Alpine
base image. It uses:

- Home Assistant Supervisor MQTT service;
- Home Assistant MQTT Device Discovery;
- official Ookla Speedtest CLI 1.2.0;
- retained MQTT state;
- atomic JSON persistence under `/data`;
- no systemd and no external host or LXC.

Environment:

```text
HOME=/data
XDG_CONFIG_HOME=/data/.config
```

Stable compatibility contract:

```text
MQTT base topic: DigitalHouses/Global/speedtest
Device ID:       digitalhouses_global_speedtest
Device name:     Internet Speedtest
```

All 1.0.0 entity unique IDs and default entity IDs remain unchanged.

## Data files

```text
/data/state.json
/data/servers.json
/data/thresholds.json
/data/recent_results.json
/data/schedule.json
```

`thresholds.json` defaults to:

```json
{
  "minimum_download_mbps": 10,
  "minimum_upload_mbps": 10,
  "maximum_ping_ms": 200
}
```

`recent_results.json` schema:

```json
{
  "schema_version": 1,
  "updated_at": "2026-07-24T09:18:00Z",
  "results": []
}
```

There is deliberately no backfill from the 1.0.0 retained state.

`schedule.json` stores the live periodic interval and the last App-option
interval observed at startup:

```json
{
  "periodic_test_interval_minutes": 30,
  "app_option_interval_minutes": 30
}
```

The second field is internal migration metadata. It lets the MQTT Number
persist across restarts while still allowing an explicit App-option change to
take effect on the next restart.

## MQTT topics

Existing topics remain unchanged:

```text
DigitalHouses/Global/speedtest/state
DigitalHouses/Global/speedtest/command
DigitalHouses/Global/speedtest/availability
DigitalHouses/Global/speedtest/connectivity
DigitalHouses/Global/speedtest/servers
```

New 1.1.0 topics:

```text
DigitalHouses/Global/speedtest/result_availability
DigitalHouses/Global/speedtest/thresholds
DigitalHouses/Global/speedtest/problems
DigitalHouses/Global/speedtest/recent_results

DigitalHouses/Global/speedtest/thresholds/minimum_download/set
DigitalHouses/Global/speedtest/thresholds/minimum_upload/set
DigitalHouses/Global/speedtest/thresholds/maximum_ping/set
```

New 1.1.1 schedule topics:

```text
DigitalHouses/Global/speedtest/schedule
DigitalHouses/Global/speedtest/schedule/periodic_interval/set
```

## Periodic interval control

`number.internet_speed_periodic_interval` is the live scheduler control.

```text
Range: 5–720 minutes
UI step: 5 minutes
MQTT payload: whole integer minutes
```

When the Number changes:

1. validate and persist the new interval;
2. publish the retained Number state;
3. wake the scheduler thread;
4. restart the countdown from the time of the change.

The change is processed directly in the MQTT callback and is not queued behind
an Ookla run. A currently running test is not interrupted.

The legacy `periodic_test_interval_minutes` App option remains supported:

- if `/data/schedule.json` does not exist, the App option initializes it;
- Number changes then persist across restarts;
- if the App option is later changed, the new App-option value overrides the
  persisted Number value on the next App restart.

`periodic_test_enabled` remains the master switch. When disabled, the interval
can still be changed and stored, but the scheduler does not enqueue tests.

## Threshold semantics

The threshold is the boundary where a problem begins.

```text
low_download = download_mbps < minimum_download_mbps
low_upload   = upload_mbps < minimum_upload_mbps
high_ping    = ping_ms > maximum_ping_ms
low_speed    = low_download OR low_upload
problem      = low_download OR low_upload OR high_ping
```

Equality is normal.

Threshold command processing is not queued behind Ookla execution. The MQTT
callback validates and persists the number, republishes the Number state and
immediately recalculates current problem sensors from the latest successful
result.

Old Recent results are immutable and never recalculated.

## Problem attributes

Metric problem sensors publish:

```yaml
current_value: 34.0
threshold: 50
unit: Mbit/s
comparison: less_than
difference: -16.0
evaluated_at: "..."
result_timestamp: "..."
server: "OBIT — Almaty, Kazakhstan"
server_id: 56519
```

The aggregate sensor publishes:

```yaml
low_download: true
low_upload: false
high_ping: false
low_speed: true
problem_reasons:
  - low_download
evaluated_at: "..."
result_timestamp: "..."
server: "..."
server_id: 56519
```

## Availability model

Two retained availability topics are used:

- App availability: process/MQTT health;
- Result availability: freshness of the last successful test.

Measurement and performance problem entities require both to be `online`.
Other controls and diagnostics require only App availability.

This avoids the old failure mode where publishing a status update on the shared
state topic restarted Home Assistant's `expire_after` timer for old
measurements.

Processing order after MQTT reconnect:

1. publish discovery;
2. publish retained state, thresholds, schedule, Recent results and evaluation;
3. publish result freshness;
4. publish App availability `online`.

This prevents stale values appearing briefly as valid after restart.

## Runtime transitions

### Successful test

1. Parse and validate Ookla JSON.
2. Atomically save current state.
3. Snapshot current thresholds.
4. Build and persist one Recent result.
5. Publish Recent results.
6. Recalculate and publish problem sensors.
7. Mark result availability online.

### Failed test

- Keep the previous successful measurements.
- Set status to `Error`.
- Do not append Recent results.
- Do not interpret the failure as low speed.
- Keep previous evaluation until it expires.

### No connectivity

- Skip Ookla execution.
- Set status to `No connectivity`.
- Keep previous successful measurements and evaluation.
- Connectivity binary sensors report the outage.
- Do not append Recent results.

### Expiration

When the age of `last_success` exceeds `expire_after_seconds`,
result availability becomes `offline`. Measurement and performance problem
entities become `unavailable`.

A new successful test restores them.

## Recent result record

```json
{
  "timestamp": "2026-07-24T09:18:00Z",
  "server": "OBIT — Almaty, Kazakhstan",
  "server_id": 56519,
  "download_mbps": 197.8,
  "upload_mbps": 198.0,
  "ping_ms": 2.1,
  "jitter_ms": 0.5,
  "packet_loss": null,
  "result_url": "https://www.speedtest.net/result/c/...",
  "minimum_download_mbps": 10,
  "minimum_upload_mbps": 10,
  "maximum_ping_ms": 200,
  "low_download": false,
  "low_upload": false,
  "high_ping": false,
  "low_speed": false,
  "performance_problem": false,
  "problem_reasons": []
}
```

External IP is excluded. Results are stored newest-first and deduplicated by
result URL, with timestamp plus server ID as fallback.

## Tests

Run locally:

```bash
python3 -m py_compile \
  digitalhouses_speedtest/rootfs/app/core.py \
  digitalhouses_speedtest/rootfs/app/discovery.py \
  digitalhouses_speedtest/rootfs/app/app.py

python3 -m unittest discover -s digitalhouses_speedtest/tests -v
python3 scripts/validate_repository.py
bash -n digitalhouses_speedtest/rootfs/run.sh
```

The test suite covers strict threshold boundaries, aggregate logic, immediate
recalculation, immutable historical thresholds, failed/no-connectivity
semantics, expiration, packet-loss null handling, limits, threshold and
schedule persistence, App-option migration, discovery payload and preservation
of every 1.0.0 identity.

## Field verification checklist

Before updating screenshots:

1. Install 1.1.1 from GitHub over 1.1.0.
2. Confirm all old entity IDs and Recorder history remain.
3. Run a manual test.
4. Change Periodic test interval and confirm the log reports immediate
   rescheduling without an App restart.
5. Restart the App and confirm the interval persists.
6. Change the legacy App option, restart and confirm the Number follows it.
7. Change all three threshold Numbers and confirm immediate recalculation.
8. Force low/high thresholds and verify strict equality.
9. Restart the App and confirm thresholds and Recent results persist.
10. Test no-connectivity and failed Ookla execution.
11. Test expiration with a temporarily short `expire_after_seconds`.
12. Inspect MQTT discovery and App logs.
