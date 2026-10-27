# Changelog

## 0.1.7

- Persist event transitions for IPv4 source disagreements, especially HA Router Wi-Fi Media Bridge MAC/IP observations versus fresh direct ARP, without treating them as confirmed duplicate-IP faults or sending notifications.
- Suppress the attention-grabbing IPv4 warning for ARP-versus-router discrepancies while retaining a neutral count and detailed local Events history.
- Native bounded SSDP M-SEARCH discovery on the primary local IPv4 network, with conservative fresh-ARP binding, read-only service metadata and unmatched diagnostics.
- Never fetch LOCATION/XML or store sensitive URL path/query components. No SSDP-only device creation, name/presence mutation, new capabilities or changes to HAOS ingress policy.
- Additive schema v5; previous UUIDs, notes, identity history and SQLite content persist.
- UI: SSDP counters, source badges and helpful event descriptions. New regression tests for safe SSDP parsing, verified joins and deduplicated event transitions.

## 0.1.6

- IP address is now the first column in the Ingress inventory; removed the wide Bonjour services column.
- All published services, instances and ports appear on hover/focus of the compact `mDNS · N` badge.
- Added clickable ascending/descending sorting for **every device column**: IP, name, MAC, Presence, sources, last Online, Note.
- IPv4 ordering is numeric across octets; rows missing an IP remain last in either direction, default is ascending IP.
- Active search/sort survives the regular browser refresh without losing text-input focus.
- Diagnostic JSON `browser_view` includes selected sort column, direction and visible device UUIDs in the actual on-screen order.
- Added a browser JavaScript regression suite; no backend, schema, scanner, credential, permission, UUID or Note changes.

## 0.1.5

- Added native Go Bonjour/mDNS DNS-SD service discovery on the primary LAN, using legacy-unicast queries without Nmap or extra HAOS privileges.
- Hostnames and service types/ports are attached only to uniquely identified, fresh ARP-confirmed devices; no IP-only/hostname-only device merging.
- Multiple Bonjour services remain under one host; unresolved mDNS observations are retained separately in diagnostics.
- Source health and counters, device services in Ingress, and exported matched/unmatched mDNS records.
- Existing UUIDs, notes, router-provided names and Presence remain unchanged by Bonjour.
- No mDNS TXT collection; IPv6 NDP, SSDP and HA events remain future milestones.

## 0.1.4

- Introduced source-scoped positive IPv4 evidence rather than overwriting the current device IP with every router claim.
- Fresh ARP-backed MAC ↔ IPv4 observations take precedence over conflicting Home Assistant tracker IPs.
- Current IPv4 is withheld for stale or unresolved records, but UUID, MAC, Note, identity history and previous IPs remain unchanged.
- Added conflict evidence, winning-source explanations and current IP summaries to diagnostic JSON; no duplicate MAC merging.
- Display last ARP scan count separately from historically observed ARP clients, with visible IPv4 conflict count.
- New regression tests for conflicting router/ARP MACs, address changes, stale claims, duplicate ARP claims and Note preservation.
- No new privileges, raw network scan scope, mDNS/Bonjour or HA events in this release.

## 0.1.3

- Added a **Save diagnostics (.json)** button in the Ingress Web UI for sharing reproducible app observations with support.
- Included complete device inventory and notes, MAC/IP identity histories, source health, current/previous observations and latest 200 events.
- Added active UI tab, selected search filter, visible UUIDs and displayed counters to browser-downloaded snapshots; files are local and are not uploaded.
- Added **Discovered via** badges for each device, showing historical HA Router and ARP source associations.
- Added diagnostic schema v1, read-only API endpoints, privacy notice and automated export tests.
- No new network privileges, changes to scanning or changes to device identity matching.

## 0.1.2

- Added bounded native Go ARP discovery of the primary on-link LAN (no Nmap, no external ARP command).
- Enabled `host_network` and the minimal `NET_RAW` capability only; Ingress uses Supervisor-assigned dynamic port.
- Restricted HTTP access to the authenticated Supervisor Ingress peer; direct LAN connections to the host-network port are rejected.
- ARP observations merge into the persistent SQLite device registry by MAC; UUID, notes and IP history remain intact.
- Ambiguous Proxy ARP MACs are reported as degraded and skipped; source failures never mark devices Offline.
- New scan interval setting (180 seconds by default) and LAN ARP Source diagnostics. IPv6 NDP, mDNS/Bonjour and SSDP remain future stages.

## 0.1.1

- Added read-only import of router-backed Home Assistant `device_tracker` entities through the Supervisor Core REST API.
- Devices persist in SQLite with MAC/HA entity identity and IPv4/IPv6 history; existing notes survive restart/update.
- Added configurable poll interval (default 60 seconds), per-source health and real device/source views.
- Unknown/unavailable tracker states no longer imply offline. Missing/failed HA API never triggers a mass-offline transition.
- No independent LAN scanner or HA event publication yet.

## 0.1.0

- Created DigitalHouses Network App as a standards-compliant experimental HAOS App.
- Added Ingress Web UI, Go/SQLite foundation, persistent device/event schema and read-only inventory API with note editing for existing device records.
- Added repository registration, documentation, product-specific validation and tests.
- No scanning, HA router integration, presence inference or event transmission in this preview.
