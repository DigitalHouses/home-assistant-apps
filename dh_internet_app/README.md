# DigitalHouses Internet App

Home Assistant App for Internet availability monitoring, Ookla Speedtest, current-month outage history and automatic ONT/router recovery.

This is a new product. It does not migrate or reuse the stable MQTT identities or Recorder history of `digitalhouses_speedtest`.

## Canonical identities

- repository directory: `dh_internet_app`
- HA App slug: `digitalhouses_internet`
- public product name: **DigitalHouses Internet App**
- release identifier: `digitalhouses_internet_app`
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

## Current development milestone

Version `0.1.0` establishes the new product identity and the recovery/availability foundation:

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

## Home Assistant presentation

The reusable Home Assistant layer is deliberately split by responsibility:

- `examples/packages/dh_internet_app_global_package.yaml` — Recorder whitelist only;
- `examples/packages/dh_internet_app_notification_package.yaml` — English schema-v2 Event presentation;
- `examples/packages/locales/ru/dh_internet_app_notification_package.yaml` — Russian notification presentation; install exactly one notification locale;
- `examples/lovelace/dh_internet_app_dashboard.yaml` — reference Sections dashboard.

Both locale packages validate event-specific schema-v2 machine payloads and emit the same transport-neutral Home Assistant event `dh_internet_app_notification` using DigitalHouses Notification Envelope v1 (`notification_schema_version: 1`). Missing or invalid required machine fields produce an explicit `contract_error`; raw machine payloads are not forwarded. A site-local adapter may deliver the localized event through Telegram, `mobile_app` or another transport. The reusable packages contain no customer-specific notification target, `write2log` dependency or private service.

The reference dashboard uses Mushroom, mini-graph-card and auto-entities. Optional Router and traffic entities are hidden when their mappings are not configured or their mapped source is currently unavailable.
