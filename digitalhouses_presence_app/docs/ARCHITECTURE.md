# Presence App — proposed architecture

## Boundaries

```text
Home Assistant Mobile Companion GPS ──┐
                                      ├── Presence App state engine
Supervisor native Ingress registration ┤       ├── durable confirmed state (/data)
(connection.user + actual peer)        │       ├── retained MQTT state / Discovery
              │                       │       └── non-retained MQTT machine Events
              └── local IP → active ARP┘                 │
                            ▲                            └── HA packages → notifications
                       single Wi-Fi Engine
```

Preferred: one HA App owns GPS decisions, state, MQTT and the authenticated registration UI. Supervisor Ingress supplies HA user identity; access to HA Core `ActiveConnection` is unnecessary. No monkey-patching of Companion or HA WebSocket internals. The ARP engine needs L2 reachability and minimal raw-socket privileges: its container feasibility has **not** been proven.

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

## Native Ingress single-App registration pilot (0.1.11; acceptance pending)

The earlier architectural sketch used a separate HA Core adapter. This has
been **superseded** by documented Supervisor Ingress authentication headers:

```text
HA Companion / HA user (local Wi-Fi)
      → authenticated HA Core ingress transport
      → Supervisor Ingress (user id, display name, proxy chain)
      → DH Presence App native HTTPS/HTTP web UI
      → direct LAN on-link ARP
      → private /data/registration registry
      → existing one-engine GPS/MQTT discovery and events
```

- `ingress: true`, port 8099, `panel_admin: false` expose a native HA
  App panel with no custom integration or JS module. Supervisor only
  authenticates incoming requests and injects user identity on its
  documented ingress proxy hop `172.30.32.2`.
- The App derives the directly connected Core client IP from the
  second-to-last hop of X-Forwarded-For, **never the untrusted first
  header value**, with a validated last internal Core hop. Registration
  is allowed only for a local IP/.local HA URL and on-link IPv4 peer.
- `arping` performs a fresh one-time IPv4 LAN broadcast with `NET_RAW`;
  the App refuses off-link paths, proxy/virtual interfaces, failed probes
  and inconsistent MAC observations.
- A selected GPS tracker and the authenticated HA user are stored locally.
  Device ownership proof is an explicit **pilot limitation**: HA Ingress
  identifies the user, but the App cannot prove that the selected tracker
  is the physical Companion app hosting the web session.
- `host_network` + `NET_RAW` were **explicitly approved for this
  experimental 0.1.11 home pilot** only. Repository validator enforces
  exactly this capability and Ingress, with no extra ports, mounts, role or
  disabled AppArmor. Live field verification of source IP, Ingress isolation
  and ARP remains pending; deny higher privileges or production claims.
- Wi-Fi presence/absence and alarm integration are out of scope.
