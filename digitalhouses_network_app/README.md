# DigitalHouses Network App

Experimental native **Home Assistant OS App** for a durable LAN device inventory, presence history, and future device events. Internal/entity prefix: `dh_network_app`. Canonical product ID, App Store slug, and repository directory: `digitalhouses_network_app`.

## Staged telemetry policy-v2 implementation (0.1.32 draft)

This is **not yet a published/installed upgrade**. The staged implementation uses
a dedicated HTTPS worker for `https://telemetry.digitalhouses.vip/v1/heartbeat`,
independent of MQTT or the network scanner. The only transmitted fields are
`schema`, `telemetry_policy_version`, `installation_id`, `product` and
`version`; the per-installation bearer token authenticates each request.
No devices, IPs, hostnames, local inventory or other LAN measurements are
included. Country is derived on the server, not transmitted by the App.

The existing HAOS configuration provides one explicit `telemetry_enabled`
switch (default `false`), with a policy link in the user-facing translation.
The policy-v2 design stops normal application startup if consent has not been
given; hence installing it over an existing Network App without advance operator
migration would interrupt core LAN monitoring. The rollout is blocked until
the shared privacy/legal gate, consent/rights handling and safe upgrade plan
are approved. In particular, this experimental source-built App has not yet
adopted the production immutable-image release provenance requirement.

Telemetry is **not** the retained MQTT `/sync` announcement used by DH Sync.
The common DH Stats product registry is prepared in this draft for server
admission, but server deployment and live heartbeat verification are separate
required release-acceptance steps.

## DH Sync 0.6.0 discovery (0.1.31)

When the existing optional MQTT worker connects or reconnects, the App publishes
`DigitalHouses/Global/digitalhouses_network_app/sync` with QoS 1 and retain.
The message identifies the running App and points DH Sync at its canonical
`digitalhouses_network_app` directory in
`https://github.com/DigitalHouses/home-assistant-apps`.
The announcement does not contain Dashboard/View placement, credentials,
site addresses or network inventory. MQTT Event and Home Assistant Discovery
topics are unchanged.

The App's full management interface remains in Home Assistant Ingress. No
canonical Lovelace Views or automatically installed HA Packages are currently
published for DH Sync. The optional local notification package remains under
`examples/` and is not part of DH Sync's automatic installation.

## Current state (0.1.16 NEW badges and machine events)

Available now:
- `NEW` badge appears beside a device name for 24 hours after the first positive ARP/HA/local-interface evidence (not merely a router's `not_home` entry). Repeat observations, IP changes and name enrichments do not renew the badge.
- After the quiet first-census window (120 seconds on initial database initialization and after confirmed Reset), each newly positively discovered UUID produces **one** `device_discovered` MQTT Event (QoS 1, non-retained), with `device_id`, `observed_at`, `detection_source` and any known MAC/IP/name. Discovery config is retained for HA startup; event delivery retries from a SQLite outbox after MQTT failure.
- Machine event entity `event.dh_network_app_network`, diagnostic `sensor.dh_network_app_version` and `sensor.dh_network_app_started_at`. MQTT broker service is optional; network discovery works without MQTT and pending events are not falsely marked delivered.
- Custom method-grouped `monitored_devices` with multilingual optional `label` is the **approved next phase**, not yet active in version 0.1.16; arbitrary nested keys require Supervisor config UI compatibility verification.
- The Reset confirmation dialog uses a real line break between the irreversible-data-loss warning and the `RESET` instruction, not a literal `\n`.
- In the expandable `Показатели` panel, a destructive **Reset — очистить инвентарь…** button. A typed `RESET` challenge **and** final confirmation are required. Only the authenticated Home Assistant Ingress (admin-only panel) can use the JSON API endpoint `POST /api/inventory/reset`. It deletes all 16 discovery and inventory table contents in a single SQLite transaction, including device identities/UUIDs, Notes, events and protocol records. The SQLite schema, `schema_version`, Supervisor options, and host settings stay intact. There is no data backup or undo inside the App; download the diagnostic JSON before Reset if history is needed.
- Reset invalidates responses from scans started earlier (generation gate), then starts a new ordered discovery pass (HA Router, primary LAN interface/ARP, then mDNS/SSDP/WSD). Ordinary poll cycles continue. The App never edits router, HA or other devices as part of Reset.
- standard installation from the **DigitalHouses Home Assistant Apps repository** (no copying files into HAOS);
- authenticated Home Assistant Ingress Web UI, optionally shown on the HA sidebar;
- Go process, persistent SQLite at `/data/network.sqlite3`;
- Device list heading `Устройства (N)` and search field share one horizontal row (search immediately to the right of the count; wraps on narrow screens). Export confirmation no longer requests sharing the file in a chat. The metrics dropdown no longer contains the orange explanatory notice.
- UI sections for Devices, Sources and Events in a single persistent Ingress header. A native keyboard-accessible `Показатели` disclosure keeps the 11 metric cards, source explanation and diagnostic JSON export hidden by default, but accessible in the top bar on demand; the device table and search are visible immediately. REST status/devices/sources/events endpoints and note updates for records that exist;
- periodic read-only import of Home Assistant `device_tracker` entities with `source_type: router` using the official Supervisor Core API proxy;
- persistent MAC/HA tracker identities, IP address histories and last positive sighting; **Online represents positive ARP/HA router tracker/local interface evidence, not successful ICMP ping**. ICMP availability is not implemented and is not inferred from the current Presence field;
- source health, last successful poll and import counts. A working HA API with no router trackers is reported as `empty`, not a scan failure.
- independent bounded ARP probing of the **primary LAN Ethernet interface** at a configurable interval (default 180 s), without Nmap or installing tools into HAOS;
- reconciliation of ARP-positive MACs with router-discovered MACs; stable UUIDs, notes and IP address histories are preserved;
- source diagnostics distinguish errors, no responses and Proxy ARP ambiguities; no automatic Offline inference;
- an empty inventory until real router trackers or ARP replies are observed; no fabricated devices or presence data;
- **Download diagnostics (.json)** on every Ingress tab: version, time, all devices and notes, source status/counts, events (up to 200), MAC/IP identity history, latest ARP-positive timestamps, and the browser's active tab/search/visible row IDs.
- **Обнаружен через / Discovered via** column: per-device HA Router and ARP associations, with hoverable last-reported timestamps. A source badge means historical association, not guaranteed current presence;
- additive source-scoped IPv4 evidence database: live ARP mapping outranks a conflicting HA router-reported IP, while historical DHCP/HA claims and notes remain intact;
- current IPv4 is blank when neither source has fresh positive evidence. The diagnostic JSON exposes all IPv4 evidence and conflicts with timestamps/MACs; the Web UI shows conflict counts and separate last-ARP-scan versus historically seen ARP hosts.

- Bonjour/mDNS discovery from the App itself: published hostnames and DNS-SD service types/ports are stored only for devices with a fresh, unique ARP-verified address/MAC association. A verified change to a Bonjour-sourced hostname automatically refreshes that device's displayed name without replacing UUID, MAC, Notes or Presence. Meaningful router and verified WSD labels take priority.
- Ingress displays detected service types, source attribution and counts. Exported JSON contains linked records plus unlinked announcements without inventing device identities.

- Compact **IP-first device table** with sortable column headers; numeric IPv4 ordering and unknown addresses always last. Bonjour services appear on hovering/focusing a compact `mDNS · N` discovery badge rather than in a wide column.
- JSON diagnostics record the selected sort and exact displayed order of devices alongside the existing complete inventory.

- Local source discrepancies (including Media Bridge router tracker vs direct ARP) are recorded **once per change** in the Events tab, not emitted as HA alerts. The current IPv4 continues to prefer fresh direct ARP evidence.
- Experimental SSDP/M-SEARCH discovery on the primary LAN enriches only uniquely fresh ARP-confirmed devices, without fetching remote XML documents, creating fake hosts or altering Notes and Presence. SSDP service badges have details on hover and diagnostics export includes all matched/unmatched metadata.

- A numbered, single-line device table (№, Name, IP, MAC, Presence, sources, last Online, Note) removes fallback MACs from the Name column. A missing discovered name is displayed as a dash without changing the stored identity.
- Notes use a clickable inline label when present and a small `Добавить` action when absent. The complete text is retained in SQLite, shown on hover and editable with one click.

- The primary Linux default-route LAN interface is **positive direct OS evidence** (MAC and IPv4, no invented name). Own HAOS address is registered even though an ARP scanner cannot query itself. Local-interface claims outrank router claims and are journaled on conflict.
- WS-Discovery sends a bounded local UDP 3702 multicast Probe for DPWS devices and records ProbeMatches only when the reply references the unique sent MessageID. Response IPs are joined to existing devices **only** with fresh unique ARP or local interface identity; unmatched identifiers remain metadata. This pilot does **not** issue HTTP metadata Get or infer a device name from WSD UUID/Types/Scopes.

- Verified Windows / Linux wsdd2 computer names are obtained only from bounded HTTP SOAP GetResponse `pub:Computer` records, bound to the exact WSD endpoint and a fresh direct ARP/MAC identity. Supported explicit WSD computer-name forms include `name/NotJoined`, `name/Workgroup:...` and `name/Domain:...`. The system does not infer names from service categories or generic WSD FriendlyName. Existing meaningful labels and user Notes are preserved. A strict same-IPv4, WSD-advertised local HTTP port 5357 or 3702 policy blocks SSRF, proxies and redirects. The verified name and source are retained in SQLite schema v7.

**Not yet implemented:** IPv6 NDP, SSDP, full device registry enrichment, HA Event publication or verified Offline. `online` means either a router reports `home` or a device answers ARP. The Web UI identifies these as planned.

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
