# DigitalHouses Network App

A local network inventory and device presence monitor for Home Assistant OS.

## Why this app exists

A smart home may contain dozens of network devices. Router trackers, ARP observations and advertised service names do not always agree: DHCP addresses change, old router entries remain, and some devices never answer ICMP ping.

Network App combines these independent sources without treating every report as equally reliable. It retains a persistent inventory and helps you understand what was discovered, why it was associated with a device, and when the device was last positively observed.

## Features

- Bounded ARP discovery on the primary local Ethernet interface, independently of HA router integrations.
- Read-only import of existing Home Assistant router device trackers.
- Bonjour/mDNS, SSDP and WS-Discovery enrichment with source attribution and conservative identity matching.
- Persistent SQLite inventory: stable device IDs, MAC/IP history, notes and positive observations.
- Sortable, searchable device table, NEW badges, event journal and JSON diagnostics.
- Optional IP/MAC Presence watches using confirmed global ARP scans, with configurable confirmation thresholds.
- Optional MQTT machine events and DH Sync announcement. MQTT is not required for local discovery.
- Russian and English Ingress UI in the internationalization candidate; change the language in the header. The browser remembers the choice. Device names, notes and machine identifiers are not translated.

**Online is not ping.** It means a positive observation from ARP, the local interface or a Home Assistant router tracker. Presence watches use fresh successful ARP scans; failed or ambiguous scans do not establish absence.

## Screenshots

English screenshots from a real HAOS installation will be added after candidate acceptance. No simulated device inventory is presented as a live installation.

## Installation

Requires Home Assistant OS. The app supports amd64 and aarch64.

1. Open **Settings → Apps → App store → Repositories** in Home Assistant.
2. Add [DigitalHouses Home Assistant Apps](https://github.com/DigitalHouses/home-assistant-apps).
3. Install **DigitalHouses Network App** and start it.
4. Select **Open Web UI**; optionally enable **Show in sidebar**.

Version 0.1.33 is the internationalization release using immutable GHCR delivery. The maintainer approved a direct stable release; final live HAOS acceptance and reviewed English screenshots remain pending. Do not replace an existing installation by deleting or recreating it.

## How to use

- **Devices:** search and sort the inventory, add notes, inspect discovery sources and enable a Presence watch from an IP/MAC cell.
- **Sources:** check scan health and distinguish empty results from errors.
- **Event log:** inspect new-device and monitored-availability events and copy HA automation trigger templates.
- **Settings:** configure shared scan intervals, confirmation thresholds and retention; export JSON diagnostics.
- **Help:** read explanations of positive evidence, Presence and MQTT event delivery.

The first discovery census is quiet for 120 seconds. After that, first positive discovery of a new device can generate a non-retained MQTT event. MQTT delivery acknowledgement means the broker accepted the event, not that a notification was delivered.

## Data, security and privacy

The inventory lives in `/data/network.sqlite3`. In-place updates must retain the App data directory. The app has a cold-backup policy; take a Home Assistant App backup before updates and never use Reset to perform an upgrade. Reset is destructive and requires explicit typed confirmation.

The management interface is administrator-only Supervisor Ingress. Host networking and NET_RAW are needed for on-link ARP discovery; no standalone management port is exposed. The app reads HA device trackers through the Supervisor API, does not require router credentials, and does not configure routers or other devices.

Diagnostics contain local device identifiers, addresses, notes, source details and event history. Review and redact them before sharing.

Optional DH Stats telemetry is disabled by default (`telemetry_enabled: false`). If explicitly enabled, the policy-v1 HTTPS heartbeat contains only schema, telemetry policy version, a random installation UUID, product ID and version. The inventory, IP/MAC addresses, device names, notes and credentials are not included. The server can observe the public connection IP as with any HTTPS service. Telemetry failures do not interrupt discovery. See [telemetry policy](../docs/standards/PRODUCT_TELEMETRY_POLICY.md) and [technical documentation](DOCS.md) for identity retention and deletion.

## Limitations

- Primary private IPv4 subnet only, /24 through /30; no VLAN discovery, IPv6 or networks larger than /24.
- No universal availability guarantee: sleeping devices, isolated Wi-Fi clients, proxy ARP and router tracker errors can limit accuracy.
- Service discovery enriches positively identified devices and does not establish presence by itself.
- Not a port scanner, traffic analysis tool, replacement for a network management system or a security vulnerability scanner.

## Documentation and feedback

- [Technical documentation](DOCS.md)
- [Changelog](CHANGELOG.md)
- [International release acceptance checklist](INTERNATIONAL_ACCEPTANCE.md)
- [Report an issue](https://github.com/DigitalHouses/home-assistant-apps/issues)

Feedback on real-world discovery accuracy, router integrations and false positives is welcome.
