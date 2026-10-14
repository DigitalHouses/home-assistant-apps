# Presence App — proposed architecture

## Boundaries

```text
Home Assistant Mobile Companion GPS ──┐
                                      ├── Presence App state engine
HA Core WebSocket registration adapter ┤       ├── durable confirmed state (/data)
(connection.user + actual peer)        │       ├── retained MQTT state / Discovery
              │                       │       └── non-retained MQTT machine Events
              └── local IP → active ARP┘                 │
                            ▲                            └── HA packages → notifications
                       single Wi-Fi Engine
```

Preferred: one HA App owns network monitoring, GPS decisions, state and MQTT. A minimal supported HA Core adapter owns authenticated WebSocket registration only if required. A regular App cannot read HA Core's `ActiveConnection`. No monkey-patching of Mobile Companion / Home Assistant WebSocket internals. The ARP engine needs L2 reachability and minimal raw-socket privileges: its container feasibility has **not** been proven.

If HA App cannot perform safe ARP probing, compare an all-in-one HA custom integration versus App + adapter **before** implementation; avoid two parallel Wi-Fi engines.

## Confirmed prototype evidence (14 October 2026)

- Authenticated iPhone WebSocket → HA user → `192.168.11.54` → `88:b9:45:80:a7:55` through interface `enp6s18`.
- Active ARP with Wi-Fi enabled: 28 responses / 33 probes; isolated misses.
- Wi-Fi manually off: 28 consecutive misses, with responses after reconnection.
- Neighbour table showed REACHABLE after active ARP replies stopped, so the cache cannot prove online presence.
- iOS automatically changed Companion access to Cloudflare when local Wi-Fi was turned off. The externally routed WebSocket client is **not** eligible for local registration.

IP, MAC, interface and SSID observed in the test are **not** configuration constants. Deep-sleep iOS proof and trustworthy negative absence remain open.

## Registration security

1. Verify authorized HA session and registered user selection server-side.
2. Prove direct local connection, not just a private-looking remote IP. Reject proxy/Tailscale/Cloudflare registration unless separately attested.
3. Fetch and validate available Companion device and GPS tracker association. Multiple devices per HA user need additional binding validation.
4. Perform fresh IP→MAC verification without a network-wide scan; persist successful binding only after all checks.
5. Enforce server-side admin policy for delete and configuration operations.
6. Use an expiring one-time registration challenge where cross-process handoff is needed; do not expose bearer credentials.

## Source evidence and decision engine

Separate:
- GPS: `home | not_home | unavailable`, observation/freshness metadata;
- Wi-Fi: `home | not_home | unavailable`, source-provenance and verified-negative evidence gate;
- Confirmed logical presence: `home | not_home | unknown`, durable across outages.

Hybrid GPS HOME + verified Wi-Fi absent has a configurable 15-minute continuous qualification period before NOT_HOME. Mere ARP misses and neighbour cache snapshots can only support uncertainty, not verified absence. Breaks in verification reset negative qualification. On source loss/restart keep durable status and diagnostics of stale inputs; do not emit transitions.

Order for a legitimate state transition:
```text
Validate new evidence → persist confirmed state → publish retained current state
→ publish QoS1 non-retained machine event
```
Reconnect must not replay events from an old state snapshot. Event duplication/loss rules require explicit transport tests.

## Product lifecycle

**Pilot status 0.1.1:** A runnable, GPS-only experimental Home Assistant App now exists with a `digitalhouses.app` marker, Supervisor configuration, Dockerfile, MQTT publisher, registry entry, compatibility validator, unit tests and CI. It is installed by Home Assistant Supervisor from repository sources (no GHCR `image:`). A single selected `device_tracker` identifies each resident. Native MQTT Select changes the live decision mode, with config-change precedence and persistent UI choice. The Core WebSocket adapter and trusted Wi-Fi engine remain future work; the pilot does not contain those mechanisms and cannot use Wi-Fi absence as evidence. Production-grade GHCR/telemetry and operational acceptance remain separate gates.
