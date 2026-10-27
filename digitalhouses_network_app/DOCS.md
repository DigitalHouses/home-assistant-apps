# DH Network App — architecture and implementation notes

## Product identity

- Public product: DigitalHouses Network App
- Canonical ID / repository directory / Supervisor slug: `digitalhouses_network_app`
- Compact namespace: `dh_network_app`
- Web UI: Home Assistant Ingress (not a second externally exposed admin service)
- Storage: SQLite `/data/network.sqlite3`
- Current version: `0.1.5`, experimental, no GHCR artifact and no telemetry

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

## Diagnostic export and per-device source attribution in 0.1.3

- New read-only Ingress API `GET /api/diagnostics` provides `digitalhouses.network.diagnostic.v1` with UTC capture timestamp, app version/start time/intervals, counters, all devices with Note, source health, up to 200 recent events, complete `identities` history and last-positive ARP timestamps.
- SQLite tables are read under a **single read transaction** to prevent a partially updated inventory during live HA/ARP scans; reporting performs no database writes.
- New `GET /api/device-sources` provides per-device source associations, derived from `identities.kind=ha_entity` and `lan_positive`, without modifying database schema.
- The browser downloads a UTF-8 JSON file `dh-network-diagnostic-YYYYMMDD-HHMMSS.json` directly from the Ingress UI. It adds `browser_view` (active tab, exact search filter, visible device UUIDs, displayed counters, local timezone and capture time), distinguishing screen filters from the complete server inventory.
- Both diagnostic APIs inherit the strict Supervisor Ingress peer check. The App does not export Supervisor credentials, raw environment variables or secret options; it does export user Note verbatim and may expose other sensitive LAN data. Show an explicit privacy notice in UI.
- Source membership is **historical**, not active presence. The per-device sources column displays HA Router and ARP badges with last-reported evidence timestamps on hover.
- `diagnostic.v1` format is versioned for future parsing; mDNS, IPv6 NDP and SSDP remain planned sources.

## Source-aware IPv4 reconciliation (0.1.4)

- SQLite **additive schema v3**: `ipv4_evidence(device_id, source, reference, ipv4, state, first_seen, last_seen)`. Existing `devices`, `identities`, UUIDs, MACs and Notes are never migrated destructively.
- HA Router and ARP observations are separately recorded. Home Assistant `home` is a positive *router-reported* claim; `not_home` and `unavailable` are historical assertions, **not proof of current IPv4**. A subsequent claim by the same router entity marks the previous claim `previous` without deletion.
- A new ARP reply is a stronger address↔MAC binding than HA Router. For each IPv4, only the strongest fresh claim can own the current address. Tied contradictory ARP evidence is marked ambiguous and leaves the IP unassigned.
- A conflict is logged in read-only `diagnostic.v1` under `ipv4_conflicts[]`, with all surviving claims, current winner (if any), and reason. `inventory.ipv4_evidence[]` retains the source reference and timestamps. The HA Router Source is `degraded` while an active conflicting IPv4 claim exists, independently of MAC association conflicts.
- ARP freshness uses at most 2 scan windows + 30 s; HA reports use 3 polling windows, with cautious test fallbacks. Expired evidence never overrides a fresh positive claim.
- The reconciler operates **inside the source writer transaction** to avoid a half-updated current address. Only the `devices.ipv4` projection is recalculated; `identities` and user Notes are never edited or reset.
- The Ingress page separates latest ARP scan host count from the number of historical ARP identities and displays address conflicts. This is not an IP conflict alarm system yet and emits no HA events.
- Before each source has delivered at least one fresh post-upgrade observation, current IPv4 may be temporarily empty. No historical row is deleted. No need to reset or edit SQLite manually.

## Bonjour/mDNS pilot (0.1.5)

- Self-contained Go DNS-SD querying on the primary LAN using a private ephemeral UDP socket to multicast `224.0.0.251:5353`; this avoids competing for HAOS's existing 5353 listener. This is an active, legacy-unicast query strategy, not a complete passive multicast listener; some responders may not answer and source=empty must not imply zero devices.
- Discovers DNS-SD service types, browses a bounded list (including `_digitalhouses._tcp.local.`), parses PTR/SRV/A/AAAA, and resolves service targets. All DNS decoding has limits against malformed records and compression loops.
- Stores data in additive SQLite schema v4: `mdns_hosts`, `mdns_services`, and bounded `mdns_unmatched` (last 24h). TXT metadata is deliberately ignored because some services advertise pairing credentials.
- A discovered host may enrich an existing device only when its IPv4 is uniquely assigned to a MAC by **fresh positive ARP evidence**. IP or hostname by itself is never used to merge device identities. Unmatched observations are retained as non-device diagnostics.
- Existing HA Router names, user notes, UUIDs, MACs and Presence are never overwritten by Bonjour. A raw MAC label may be improved to a verified Bonjour hostname. Several services on one host remain several services, not several devices.
- mDNS reports counts of response packets, discovered hosts, linked and unmatched hosts, and services; the Web UI and exported diagnostic JSON show these details.
- No new Supervisor capabilities, no native IPv6 NDP yet, no HA Event publication.

## Release boundary

Version 0.1.0 proved HAOS install, Ingress, Web UI, data persistence, version and lifecycle. Version 0.1.2 added bounded native ARP probing; 0.1.3 added read-only diagnostics and source attribution; 0.1.4 adds independent IPv4 evidence and conflict resolution; 0.1.5 adds conservative mDNS/Bonjour metadata enrichment. These versions emit no machine events. It does not claim full IPv6 or cross-VLAN visibility. A genuine scan requires an explicit later version and tests for incomplete/invalid source data before any presence state or event is emitted.

When accepted, move from experimental Supervisor source build to the standard versioned immutable GHCR artifact. The install/update UI remains the **same Home Assistant App Store**, never a manual server-side copy.
