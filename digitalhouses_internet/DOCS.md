# DigitalHouses Internet App — configuration

## Network

`router_ip` is the LAN address of the router. The App uses it to distinguish a local router failure from an upstream Internet/ONT failure.

`connectivity_check.interval_seconds` controls the normal probe interval. `attempts` is the number of consecutive failed Internet probes required before an outage incident starts. `timeout_seconds` is the timeout for an individual probe.

## Recovery

Recovery is disabled by default.

`recovery.mode` supports only:

- `smart`: Internet down + Router up -> ONT; Router down -> Router.
- `both`: ONT -> Router on every recovery attempt.

Each target supports only `button` or `switch`. A button target must reference a `button.*` entity and is executed with `button.press`. A switch target must reference a `switch.*` entity; the App turns it off for `power_off_seconds` and always attempts to restore power before the action completes or a Stop request propagates.

When recovery is enabled, both ONT and Router target entities must be configured. All recovery timing belongs to App configuration:

- `max_cycles`: recovery attempts before cooldown.
- `boot_wait_minutes`: stabilization wait after an action cycle.
- `retry_interval_minutes`: delay before the next cycle when Internet is still down.
- `cooldown_minutes`: pause after `max_cycles`; if the same outage continues, a new series may start afterwards.

The MQTT Stop button suppresses further attempts for the current incident. A new outage clears Stop state.

## Speedtest

The App runs the official Ookla CLI. Periodic execution is controlled by App configuration with a 5..720 minute interval and may be disabled. The MQTT Discovery Run speed test button uses the same backend path.

Graphable entities are Download, Upload, Ping, Jitter and Packet loss. Provider, external IP, selected server, result URL, last successful timestamp and the last error are attributes of the compact Speedtest status entity rather than separate entities.

A failed test does not overwrite the last successful measurements. The runtime status becomes `error` or `no_connectivity` while the last successful result remains persisted under `/data/runtime`.

## Quality thresholds

The three user-editable MQTT Number entities are Minimum download speed, Minimum upload speed and Maximum ping. Their values are persisted under `/data/runtime` and immediately recalculate the last successful Speedtest result.

The App owns low-download, low-upload, high-ping and aggregate performance-problem state. Home Assistant is presentation only and does not recalculate thresholds with templates. Schema-v2 Events are emitted on meaningful problem transitions.

## Recent Results

The App persists the latest 20 successful Speedtest records under `/data/runtime`. Home Assistant receives them through one diagnostic Recent results sensor whose state is the retained test count and whose `results` attribute contains the records.

Each record stores measured values plus the thresholds and problem flags active when that test completed. Later threshold changes recalculate current problem state but do not rewrite historical results.

## Monthly outages and availability

The App persists current-month outages, including an active outage. Each record contains From, To and duration; the current outage has no To value until recovery.

Current-month availability is calculated by the App from elapsed local calendar-month time minus accumulated outage time. Home Assistant exposes the result but does not own the calculation.

## Router telemetry and traffic

All Router Home Assistant bindings are optional. The public contract contains at most five:

- `traffic.traffic_download_total`
- `traffic.traffic_upload_total`
- `traffic.router_wan_status`
- `traffic.router_download_rate`
- `traffic.router_upload_rate`

Together with the two optional recovery target entities, this keeps the external Home Assistant binding surface at a maximum of seven. No Home Assistant entity binding is mandatory.

The two cumulative counters are a pair: configure both or neither. They enable App-owned monthly traffic accounting. WAN state and current Download/Upload rates are independent optional bindings and do not affect recovery decisions.

The App samples configured Router sources every 60 seconds through the Home Assistant Core API. Common decimal/binary data-size counters are normalized to bytes. Common bit/s and byte/s rate units are normalized to Mbit/s.

The first cumulative sample establishes a baseline. Normal growth adds only the delta. A source counter reset does not create negative traffic. If the cumulative source IDs change, history is retained but a fresh baseline is established. At a calendar-month boundary the first observation is also a fresh baseline because cumulative counters cannot reveal the exact cross-boundary split.

Traffic history keeps the current month plus up to 11 previous observed months under `/data/runtime`. Traffic entities are created only when the cumulative pair is configured. WAN state and current rate entities are created only when their own mapping is configured.

Temperature, connected-client count, uptime and last-boot bindings are intentionally outside the new App contract.

## Events and notifications

The App publishes machine-readable MQTT Event entities using schema version 2. Event payloads contain semantics such as event type, target, cycle, reason, values and timestamps.

Human-readable notification text belongs in the reusable Home Assistant package. Site-specific delivery such as Telegram or mobile notifications remains a local adapter and is not a dependency of the App.
