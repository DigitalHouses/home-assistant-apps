# DigitalHouses Internet App

Home Assistant App for Internet availability monitoring, Ookla Speedtest, current-month outage history and automatic ONT/router recovery.

This is a new product. It does not migrate or reuse the stable MQTT identities or Recorder history of `digitalhouses_speedtest`.

## Canonical identities

- repository directory / HA App slug: `digitalhouses_internet`
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

`Stop recovery` stops further attempts for the current outage. If a switch has already been turned off, the App always attempts to turn it back on before the stop propagates.

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
- manual and periodic Speedtest with compact status metadata;
- Recent Results as one diagnostic entity with the last 20 successful tests and the thresholds that were active for each test.

Quality thresholds and App-owned performance problem evaluation are implemented. Monthly traffic statistics and final dashboard/package presentation remain subsequent milestones before a production release.

See [DOCS.md](DOCS.md) for configuration semantics.
