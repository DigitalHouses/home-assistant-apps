# DigitalHouses Network App

Experimental native **Home Assistant OS App** for a durable LAN device inventory, presence history, and future device events. Internal/entity prefix: `dh_network_app`. Canonical product ID, App Store slug, and repository directory: `digitalhouses_network_app`.

## Current state (0.1.3 diagnostics pilot)

Available now:
- standard installation from the **DigitalHouses Home Assistant Apps repository** (no copying files into HAOS);
- authenticated Home Assistant Ingress Web UI, optionally shown on the HA sidebar;
- Go process, persistent SQLite at `/data/network.sqlite3`;
- UI sections for Devices, Sources and Events, REST status/devices/sources/events endpoints and note updates for records that exist;
- periodic read-only import of Home Assistant `device_tracker` entities with `source_type: router` using the official Supervisor Core API proxy;
- persistent MAC/HA tracker identities, IP address histories and last positive sighting;
- source health, last successful poll and import counts. A working HA API with no router trackers is reported as `empty`, not a scan failure.
- independent bounded ARP probing of the **primary LAN Ethernet interface** at a configurable interval (default 180 s), without Nmap or installing tools into HAOS;
- reconciliation of ARP-positive MACs with router-discovered MACs; stable UUIDs, notes and IP address histories are preserved;
- source diagnostics distinguish errors, no responses and Proxy ARP ambiguities; no automatic Offline inference;
- an empty inventory until real router trackers or ARP replies are observed; no fabricated devices or presence data;
- **Download diagnostics (.json)** on every Ingress tab: version, time, all devices and notes, source status/counts, events (up to 200), MAC/IP identity history, latest ARP-positive timestamps, and the browser's active tab/search/visible row IDs.
- **Обнаружен через / Discovered via** column: per-device HA Router and ARP associations, with hoverable last-reported timestamps. A source badge means historical association, not guaranteed current presence.

**Not yet implemented:** IPv6 NDP, mDNS/Bonjour/SSDP, full device registry enrichment, HA Event publication or verified Offline. `online` means either a router reports `home` or a device answers ARP. The Web UI identifies these as planned.

## Install / update (only through standard HA App Store)

1. In Home Assistant open **Settings → Apps → App store → Repositories**.
2. Add `https://github.com/DigitalHouses/home-assistant-apps` once, if not already present.
3. Refresh the App Store and install **DigitalHouses Network App**.
4. Start it and use **Open Web UI**; optionally enable **Show in sidebar**.
5. Future updates must also be installed by the Home Assistant App Store.

Do **not** install using `/local_apps`, arbitrary `docker run`, a separate web port, or manual copying into HAOS. This experimental build has no published GHCR image, so Supervisor builds it from the repository. Production immutable images will be added before the first stable release following the common DigitalHouses release policy.

## Security and compatibility

Ingress is the only allowed Web UI entry point. For on-link ARP the App uses `host_network: true` and **only** `NET_RAW`; Supervisor assigns a dynamic Ingress port and the HTTP server rejects requests not originating from Supervisor (172.30.32.2). No mapped host port, `NET_ADMIN`, `full_access`, Docker socket or host mounts are requested. Data survives App restart/upgrade in `/data`; generated code and images do not belong there. No dependency on Nmap, an MQTT broker, remote telemetry or a database server. IPv4 auto-scan intentionally refuses non-private, larger-than-/24 or ambiguous networks instead of silently scanning only part of a subnet. `homeassistant_api: true` is necessary and carries administrator-level Core API access; the token is never exposed in the Web UI.

**Privacy:** exported files contain potentially identifying network addresses, hostnames and user notes; treat them as private. Supervisor API tokens, passwords, and runtime environment are not read by the export. However a password manually written in a note will be exported verbatim. The file is created locally by your browser; the App does not upload, email or persist a separate diagnostic copy.

No existing NetAlertX, Presence App, Internet App or HA entities are modified.

See [DOCS.md](DOCS.md) for design boundaries and [CHANGELOG.md](CHANGELOG.md) for status.
