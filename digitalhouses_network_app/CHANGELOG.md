# Changelog

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
