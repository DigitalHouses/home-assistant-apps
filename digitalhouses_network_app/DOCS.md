# DH Network App — architecture and implementation notes

## Product identity

- Public product: DigitalHouses Network App
- Canonical ID / repository directory / Supervisor slug: `digitalhouses_network_app`
- Compact namespace: `dh_network_app`
- Web UI: Home Assistant Ingress (not a second externally exposed admin service)
- Storage: SQLite `/data/network.sqlite3`
- Current version: `0.1.2`, experimental, no GHCR artifact and no telemetry

This App deliberately follows the existing product-naming and HAOS packaging standards. Its **Ingress** UI is the accepted departure from the usual MQTT-discovered Lovelace control card: UI state, notes and inventory are App-owned instead of built from MQTT entities. Any future machine events must follow DigitalHouses Events & Notifications Standard; local alert delivery belongs to HA, not the public App.

## 1.0 agreed scope

- Periodic self-contained IPv4/IPv6 LAN discovery (on-link ARP/NDP, active ICMP/TCP checks where permitted, Bonjour/DNS-SD and SSDP), no required external Nmap.
- Consume **existing router integrations exposed through HA APIs** (ASUSWRT, UniFi and similar). Do not reimplement router vendor protocols merely to duplicate existing HA integrations.
- Persistent device UUID, MAC/IPv4/IPv6 histories, name provenance, notes, sources, service records, first/last seen and reconciled presence. A host can provide many Bonjour services without becoming many fake hosts.
- Presence must distinguish positive evidence, a lack of recent observations, reliable offline evidence and scanner/source failures.
- Durable local event journal and transient machine events for future local Home Assistant notification automations.
- Web UI: Devices, device details and notes, Sources health, Events and scan configuration.

## Future service discovery conventions

Where a DigitalHouses application exposes a discoverable TCP service, publish DNS-SD instance metadata using `_digitalhouses._tcp.local.` and TXT properties for app kind, version and port/path. Multiple apps on one HAOS host remain services of one host.

## Router tracker import in 0.1.1

- Requires `homeassistant_api: true` and the Supervisor-provided token; calls `http://supervisor/core/api/states` with Bearer authentication.
- Only `device_tracker.*` entities with `attributes.source_type == router` are included. GPS/mobile sources are excluded.
- `home` -> `online` (router-reported), `not_home` -> `not_observed`; `unavailable` or `unknown` -> `unknown`. No evidence yields a confirmed `offline` status.
- IP addresses are never identity keys. Existing MAC and HA tracker identifiers are history-preserving join keys. Contradictory MAC/entity matches are skipped, with degraded source status.
- Full HA response failures leave prior device state untouched and record source error. Successful empty snapshots do not invent or delete devices.
- Ingress shows a persistent device registry, source health, and editable notes. Notifications and machine events are not emitted yet.

## On-link ARP scanning in 0.1.2

- `host_network: true` and `NET_RAW` allow the Go runtime to create scoped Linux AF_PACKET sockets for Ethernet ARP, without Nmap or a host-level dependency.
- `ingress_port: 0` asks the Supervisor to assign an internal port. With host-network mode, the HTTP server accepts requests only from the Supervisor gateway peer `172.30.32.2`; all direct LAN requests fail.
- Only the interface associated with the default IPv4 route is scanned; no docker, hassio or VPN bridge scanning by default. Its address must be private, interface must be up with six-byte Ethernet MAC, and its subnet must be /24 through /30.
- Larger subnets and unsupported interfaces are explicitly reported as Source errors, never silently truncated. Scan rate is capped at 18 probes/s, cycles default to 180s.
- Only validated replies for probed addresses in the selected subnet are considered positive. Identical MAC reporting multiple target IPs in one cycle is considered possible Proxy ARP and omitted from the registry with degraded source status.
- Positive ARP observation is attached to a device by MAC; never merge solely by current IPv4. `device_id`, prior identity history and manually entered Note are retained. New devices get independent UUIDs.
- A fresh ARP-positive observation wins over HA router `not_home` or `unavailable`; no ARP reply alone never causes confirmed Offline. LAN-only stale records may become `not_observed` after multiple missed cycles.
- Supported raw-scanner platform in this pilot is Linux on amd64/aarch64. IPv6 NDP, mDNS, SSDP and machine events remain separate future milestones.

## Release boundary

Version 0.1.0 proved HAOS install, Ingress, Web UI, data persistence, version and lifecycle. Version 0.1.2 adds bounded native ARP probing and still emits no machine events. It does not claim full IPv6 or cross-VLAN visibility. A genuine scan requires an explicit later version and tests for incomplete/invalid source data before any presence state or event is emitted.

When accepted, move from experimental Supervisor source build to the standard versioned immutable GHCR artifact. The install/update UI remains the **same Home Assistant App Store**, never a manual server-side copy.
