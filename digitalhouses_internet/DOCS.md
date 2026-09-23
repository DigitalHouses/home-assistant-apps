# DigitalHouses Internet App — configuration

## Network

`router_ip` is the LAN address of the router. The App uses it to distinguish a local router failure from an upstream Internet/ONT failure.

`connectivity_check.interval_seconds` controls the normal probe interval. `attempts` is the number of consecutive failed Internet probes required before an outage incident starts. `timeout_seconds` is the timeout for an individual probe.

## Recovery

Recovery is disabled by default.

`recovery.mode` supports only:

- `smart`: Internet down + Router up -> ONT; Router down -> Router.
- `both`: ONT -> Router on every recovery attempt.

Each target has only two supported actions:

- `button`: `entity_id` must be a `button.*` entity and the App calls `button.press`.
- `switch`: `entity_id` must be a `switch.*` entity. The App turns it off, waits `power_off_seconds`, then always attempts to turn it back on.

When recovery is enabled, both ONT and Router target entities must be configured. This keeps the two modes predictable and prevents a partially configured recovery path from silently doing the wrong thing.

Timing:

- `max_cycles`: recovery attempts before cooldown.
- `boot_wait_minutes`: wait after an action cycle before checking the connection again.
- `retry_interval_minutes`: additional wait before the next cycle if the connection is still down.
- `cooldown_minutes`: pause after `max_cycles` are exhausted; if the same outage continues, a new series may start after cooldown.

The MQTT Stop button suppresses further attempts for the current incident. A new Internet outage after recovery starts with Stop cleared.

## Events

The App publishes machine-readable MQTT Events only. Initial event types are:

- `connection_lost`
- `connection_restored`
- `recovery_started`
- `recovery_action`
- `recovery_stopped`
- `recovery_exhausted`
- `recovery_error`

Human-readable notification text belongs in the reusable Home Assistant notification package, with site-specific delivery kept in a local adapter.


## Speedtest

The App runs the official Ookla CLI. Periodic execution is controlled by App configuration with a 5..720 minute interval and may be disabled. A manual MQTT Discovery button runs the same backend path.

The main graphable entities are Download, Upload, Ping, Jitter and Packet loss. Provider, external IP, selected server, result URL, last successful test timestamp and the last error are attributes of the compact Speedtest status entity rather than separate entities.

A failed test does not overwrite the last successful measurement values. Runtime status becomes error or no_connectivity and the last successful result remains persisted under /data/runtime.


## Quality thresholds

The three user-editable MQTT Number entities are Minimum download speed, Minimum upload speed and Maximum ping. Their values are persisted under /data/runtime and immediately recalculate the last successful Speedtest result.

The App owns low-download, low-upload, high-ping and aggregate performance-problem state. Home Assistant does not recalculate these thresholds with templates. Structured schema-v2 Events are emitted only on meaningful performance-problem transitions.
