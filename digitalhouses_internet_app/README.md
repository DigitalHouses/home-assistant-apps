# DigitalHouses Internet App

Home Assistant App for Internet availability monitoring, Ookla Speedtest, current-month outage history and automatic ONT/router recovery.

This is a new product. It does not migrate or reuse the stable MQTT identities or Recorder history of `digitalhouses_speedtest`.

## Canonical identities

- repository directory: `digitalhouses_internet_app`
- HA App slug: `digitalhouses_internet_app`
- public product name: **DigitalHouses Internet App**
- release identifier: `digitalhouses_internet_app`
- production image: `ghcr.io/digitalhouses/digitalhouses_internet_app:<version>`
- MQTT base: `DigitalHouses/Global/dh_internet_app`
- Home Assistant entity / unique-id prefix: `dh_internet_app_`

## Recovery

Recovery is intentionally limited to two user-facing modes:

- `smart` — if the router answers locally but Internet is unavailable, reboot the ONT; if the router itself does not answer, reboot the router.
- `both` — reboot ONT and then router on every recovery cycle.

Recovery actions are intentionally limited to:

- `button` — press an existing Home Assistant reboot button;
- `switch` — power-cycle a Home Assistant switch/relay.

Arbitrary scripts and shell commands are not part of the recovery contract.

All recovery timing belongs to App configuration: maximum cycles, retry interval, boot wait, cooldown and switch power-off duration. `router_ip` is a top-level network fact used by both monitoring and smart recovery.

`Stop recovery` stops further attempts for the current outage. Stop state, completed recovery cycles and an active cooldown survive an App restart, so restarting the App does not bypass recovery limits. If a switch has already been turned off, the App always attempts to turn it back on before the stop propagates. The HAOS App shutdown timeout is extended to 45 seconds so normal Stop/Restart operations can complete that restore path.

## Current product state

Version `0.1.20` keeps immutable GHCR delivery and adds persistent suppression of transient automatic Speedtest failures. The canonical Supervisor identity is permanent, the temporary migration runtime has been removed, and the App remains stable in Home Assistant. The product provides:

- Internet and router reachability;
- current-month outage state persisted under `/data`;
- `smart | both` recovery state machine;
- `button | switch` recovery actions via the Home Assistant Core API;
- recovery countdown and Stop button;
- structured MQTT Event entity;
- Version and Started-at diagnostics;
- Ookla Download, Upload, Ping, Jitter and Packet loss measurements;
- manual and periodic Speedtest with `idle | running` execution status and last-result metadata;
- preferred Ookla server IDs with optional automatic fallback and on-demand server catalog;
- Recent Results as one diagnostic entity with the last 20 successful tests and the thresholds that were active for each test.

Quality thresholds and App-owned performance problem evaluation are implemented. Router integration uses at most five optional HA bindings: cumulative Download/Upload totals, WAN state and current Download/Upload rates. Together with two recovery entities the App stays within seven external HA bindings. Monthly traffic retains the current month plus 11 previous months. The reusable package, notification presentation and reference dashboard are included in this development milestone.

See [DOCS.md](DOCS.md) for configuration semantics and [HAOS_TEST_PLAN.md](HAOS_TEST_PLAN.md) for the first real installation test sequence.

## Immutable production delivery

Production releases are delivered through the DigitalHouses App repository using the canonical image repository `ghcr.io/digitalhouses/digitalhouses_internet_app`. The App package version, canonical release tag, exact release commit, GHCR version tag and recorded image digest must all describe the same release. Floating tags such as `latest` are not part of the production contract.

Home Assistant backups are expected to contain installation-specific configuration and persistent `/data` state, including telemetry identity and App-owned runtime state, without duplicating a locally built application image. Restore acceptance targets the current supported production release; restoring an older release over a newer one is not a general immutable-delivery requirement.

## Completed App slug migration

The Home Assistant App slug migration from legacy `digitalhouses_internet` to canonical `digitalhouses_internet_app` is complete.

Releases `0.1.12` through `0.1.15` contained the temporary bridge/import machinery used for the controlled reinstall. Version `0.1.16` removes that machinery from the normal runtime: there is no writable `/share` migration mapping, no migration environment mode, and no migration module in the image.

MQTT/device/entity identities remain unchanged under `dh_internet_app`.

The completed procedure and release history are retained in [the slug migration record](../docs/digitalhouses_internet_app/slug-migration.md).

## Runtime contract behavior

Connectivity is considered **unknown** until a real ICMP probe completes. During startup, or when the probe mechanism itself cannot execute, the four connectivity entities are unavailable rather than being reported as down. Probe execution failures do not advance outage confirmation and cannot start automatic recovery.

Persisted App-owned state under `/data` is contract data. A genuinely missing state file is treated as first-run state and receives documented defaults where applicable. An existing malformed state file is not silently replaced: startup fails with an explicit contract-data error so recovery limits, outage history, traffic totals or telemetry installation identity cannot be reset unnoticed.

Machine events are producer-validated against their schema-v2 event-specific contract before transport. For connection loss/restoration, retained authoritative state is synchronized before the transient event is emitted. Existing MQTT/device/entity identities remain unchanged.

## Product telemetry

Usage telemetry is explicit opt-in and disabled by default:

```yaml
telemetry_enabled: false
```

When telemetry changes from disabled to enabled, the App sends one best-effort heartbeat immediately on the next App start. A fresh installation and a released App version change are also eligible for an immediate heartbeat. After a successful heartbeat, normal reporting is approximately every 24 hours with deterministic ±30 minute jitter. Ordinary restarts do not bypass the saved schedule, and a failed attempt keeps the one-hour retry backoff across restarts. The endpoint is `https://telemetry.digitalhouses.vip`. The payload contains only protocol version, telemetry policy version, random installation UUID, canonical product identifier `digitalhouses_internet_app`, and App version. Country is derived server-side. Hostname, Home Assistant UUID, LAN/WAN addresses, router data, Speedtest results, outages, entity IDs and configuration are not sent.

Telemetry identity and scheduling state are stored in `/data/telemetry.json`, so they survive App restart/update and normal HA backup/restore. Telemetry failures never affect Internet monitoring or recovery. `button.dh_internet_app_delete_telemetry` requests authenticated deletion of this installation's retained server-side telemetry data.

See [DigitalHouses Product Telemetry Policy](../docs/standards/PRODUCT_TELEMETRY_POLICY.md).

## Home Assistant presentation

The Home Assistant layer is deliberately split by responsibility:

- `examples/packages/dh_internet_app_global_package.yaml` — Recorder whitelist only;
- `examples/packages/dh_internet_app_notification_local_package.yaml` — English direct-delivery example;
- `examples/packages/locales/ru/dh_internet_app_notification_local_package.yaml` — Russian public direct-delivery example;
- `examples/lovelace/dh_internet_app_dashboard.yaml` — reference Sections dashboard.

Install one local notification package. It consumes `event.dh_internet_app_event` directly, gives every user-visible machine event its own `trigger.id`, routes through `choose`, and calls the final delivery action directly. There is no Notification Envelope, secondary `dh_internet_app_notification` event, adapter layer or repeated machine-schema validation in Home Assistant. The producer owns the machine-event contract.

The reference dashboard uses Mushroom, mini-graph-card and auto-entities. Optional Router and traffic entities are hidden when their mappings are not configured or their mapped source is currently unavailable.

Recorder-facing diagnostics are intentionally low-noise: `sensor.dh_internet_app_problems` changes only when the actual problem list changes, and `sensor.dh_internet_app_availability_month` exposes a two-decimal state plus the stable calendar month while exact outage timing remains App-owned.
