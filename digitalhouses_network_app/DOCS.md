# DH Network App — architecture and implementation notes

## Product identity

- Public product: DigitalHouses Network App
- Canonical ID / repository directory / Supervisor slug: `digitalhouses_network_app`
- Compact namespace: `dh_network_app`
- Web UI: Home Assistant Ingress (not a second externally exposed admin service)
- Storage: SQLite `/data/network.sqlite3`
- Current version: `0.1.13`, experimental, no GHCR artifact and no telemetry

This App deliberately follows the existing product-naming and HAOS packaging standards. Its **Ingress** UI is the accepted departure from the usual MQTT-discovered Lovelace control card: UI state, notes and inventory are App-owned instead of built from MQTT entities. Any future machine events must follow DigitalHouses Events & Notifications Standard; local alert delivery belongs to HA, not the public App.

## Small Ingress layout refinements (0.1.13)

- Preserve the `Показатели` disclosure with all eleven counters and authenticated diagnostic JSON export. Remove the large orange introductory information/notice block from **inside the disclosure**. Keep the concise neutral Online vs ICMP statement and retain critical, active IPv4 conflict warnings outside the menu.
- The export completion message is now just `Файл <filename> сформирован.` without instructions to send data to a chat.
- The device count and search input share a responsive flex row: `Устройства (N)` immediately followed by a bounded-width search box. The row remains separate from the table body so 30-second refreshes and filter changes don't destroy search focus. Search and count are hidden on Sources/Events.
- No changes to scanners, APIs, SQLite, MAC/UUID identity, Notes, WSD or presence status semantics.

## Compact Ingress header and presence labeling (0.1.12)

- Preserve the DigitalHouses Network App title in the top bar. Devices / Sources / Events navigation lives beside it and remains visible on each tab.
- The `Показатели` disclosure is a native `<details>` / `<summary>` in the top bar. Closed by default, opening overlays a scrollable responsive panel containing all 11 existing metric cards, the source/accuracy notice and diagnostic JSON export. No loss of export functionality or telemetry. A real unresolved ARP-vs-ARP IPv4 conflict stays visible separately and is not hidden in the panel.
- User-facing `Online` means observed presence from positive on-link ARP, HA router tracker `home`, or Local Interface; the app **does not perform ICMP echo or test TCP port reachability**. `Not observed` does not assert true offline. No new ICMP access or privilege is introduced in this UI release.
- Keep 30-second refresh, live source health, sort/search/note edits, stable device records and diagnostic JSON export. SQLite schema stays v7.

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

## Sortable compact Ingress device table (0.1.6)

- Column order: **IP, name, MAC, Presence, sources, last Online, Note**. The former Bonjour service column is removed; service descriptions, instance names and ports remain accessible on hovering/focusing the compact `mDNS · N` tag, as well as in the full diagnostic JSON.
- Every device header is an interactive ascending/descending control with `aria-sort`; default IP sorting uses numerical IPv4 octets, and missing IPs remain last.
- Search focus and selected sort persist through the 30-second UI refresh.
- `browser_view` exports `sort_column`, `sort_direction` and visible device IDs **in the displayed order**. The complete server inventory remains available.
- `node --test digitalhouses_network_app/tests/ui_sort.test.cjs` exercises IP ordering, each column, missing values, badge details, search and export-sort metadata.
- Pure browser UI change: no SQLite schema migration or modified on-wire discovery, device UUIDs, Notes or Presence. Native HAOS App Store update only.

## Local IPv4 source-disagreement journal and SSDP pilot (0.1.7)

- Additive SQLite schema v5 adds `ipv4_disagreement_state` for deduplicating transitions, `ssdp_services` for ARP-confirmed SSDP services, and bounded `ssdp_unmatched` for source-only diagnostics. Existing UUIDs, MACs, Notes, IPv4 history and events remain intact. No manual migration.
- Conflicting **HA Router vs fresh ARP** IP assertions are recorded as **informational source disagreements** (`source_disagreement`), not confirmed duplicate-IP faults. The UI keeps a neutral count and suppresses the intrusive warning for this class. Device IP projections retain their existing ARP-over-router preference.
- The event journal stores `ipv4_disagreement_started`, `ipv4_disagreement_changed`, and `ipv4_disagreement_resolved` once per state transition, never each HA/ARP polling cycle. Each event includes IPv4, resolution, source, MAC, reference and device ID. Retention is bounded to 1000 event rows; latest 200 are exposed by Ingress API and JSON diagnostic. The App does **not** emit HA events or send notifications yet.
- SSDP sends two rate-limited M-SEARCH requests with `ST: ssdp:all` from an ephemeral UDP port bound to the primary IPv4 LAN IP, to multicast `239.255.255.250:1900` every 300 seconds. Responses must be valid `HTTP/1.x 200 OK`, originate on the primary private LAN, and include bounded USN/ST/LOCATION. No passive SSDP listener or general multicast port bind is required.
- The response URL must use an HTTP(S) IP host matching the UDP responder IP. Only the **origin**, not URL paths/queries/userinfo, is persisted; no device description XML is fetched, preventing credential leakage and SSRF.
- SSDP enriches a device **only** if an unambiguous, fresh, direct ARP claim matches its current IPv4; it does not create devices, rename hosts, alter Presence, overwrite notes, merge by IP, or trust a router-only entry. Unmatched SSDP records are kept for a maximum of 24 hours as non-device diagnostics.
- Ingress shows a compact `SSDP · N` source badge with tooltip for ST, USN and SERVER, and counters for SSDP-linked hosts and services. Full records and unmatched are included in the diagnostic JSON, with new `GET /api/ssdp-services`.
- Empty SSDP responses are acceptable (`status=empty`) and do not mean no SSDP-capable hosts exist. No new Supervisor permissions, no user-configurable extra network targets, no changes to NetAlertX.

## Compact numbered device inventory (0.1.8)

- Eight columns in the Ingress table, in this order: **№, Имя, IP, MAC, Presence, Обнаружен через, Последний Online, Note**. № is a local ordinal for the **current filtered/sorted view**, not a persistent device identifier and not a sortable database field. Seven real data columns remain clickable sort controls, with the default IP numeric ascending. Exported `browser_view.displayed_columns` includes № and the exported UUID order matches the current visual ordering.
- The Name column includes only genuine non-MAC names already supplied by Home Assistant or verified Bonjour. Suppress colon/dash MAC and 12-digit raw hexadecimal (e.g. `54ef44a716c9.local`), unknown/unavailable, raw UUID and IPv4 placeholders. Fallback to meaningful hostname only if display_name is a placeholder. Show `—` when no discovered name. No inventing device labels, no backend data mutation, no using the user's note as a discovered name.
- Notes render as **one compact clickable action** per row: `Добавить` when blank and the actual saved note text otherwise, both invoking the existing note editor. A long note is CSS-ellipsized inside a bounded cell but retains full original text on hover; saved notes and API contract remain unchanged.
- Constrain every device row to a single line and use horizontal table scrolling at narrow Ingress widths. No new field editor, schema migration, runtime permission, scanner or HA API behavior.
- Ingress JS regression suite verifies numbering, headers, MAC-only name hiding, meaningful name fallback, sort/filter, escaping and note actions.

## Local Interface + WS-Discovery metadata pilot (0.1.9)

- OS default-route LAN interface's `MAC`, `IPv4`, name and prefix are read from Linux network configuration (existing `localLANPlan`), independently of ARP replies. The app registers an exact MAC-backed device (or reuses the identical MAC) and maintains an authoritative `local_interface` IPv4 evidence claim and a separate `Local Interface` source. No IP-only identity join, no automatic hostname, no Notes modification. This correctly registers HAOS VM itself, previously omitted from the active ARP target list.
- Evidence precedence: fresh `local_interface` (rank 3) > direct ARP (rank 2) > HA Router home (rank 1). Freshness for local evidence equals LAN ARP TTL; router wins only after local evidence genuinely expires. A local-interface versus router claim is an informational `source_disagreement`; preserve actual contradictory evidence in Events.
- mDNS/SSDP matching now accepts fresh, unique `local_interface` or ARP direct evidence, but never an IP-only router assertion. The previous diagnostic rule remains in effect.
- WS-Discovery (2005/04) sends an `s:Probe` to 239.255.255.250:3702, bound to the primary LAN IPv4 address via an ephemeral UDP port, every 300 seconds. The returned `ProbeMatches` is accepted only when SOAP 1.2 Action/RelatesTo match the sent message, source is local IPv4, EndpointReference is a bounded UUID, and payload is <=16 KiB. Only HTTP(S) XAddr URL origins whose literal IP matches the responding IP are retained. It **never HTTP-fetches the metadata** in this pilot and never treats Types/UUID as a human-readable name.
- Additive SQLite schema v6 adds `wsd_endpoints` and `wsd_unmatched`; unmatched items expire after 24h; matched endpoints after 7 days. No automatic identities from Endpoint UUIDs, no Presence or Note mutation, no required Supervisor privileges, no impact on parallel NetAlertX.
- Diagnostic JSON includes the WSD source, matched/unmatched endpoints, their origin (sanitized), and local-interface evidence. Ingress includes a compact WSD badge for matched devices; `GET /api/wsd-endpoints` exposes bounded matched records. Empty discovery is an expected successful response.
- **Scope limitation:** the Windows File Explorer computer name `MEDIA-SERZHAN` may be conveyed by a separate WSD SOAP metadata Get; this version does not infer or assign the name absent that verified response. That stage requires its own URL safety review and real-world protocol capture.

## Windows `/NotJoined` WSD metadata compatibility (0.1.11)

- Actual Windows workstation `192.168.11.71` HTTP SOAP Metadata Get returned `200 OK`, correlated `GetResponse` / `RelatesTo`, WSD endpoint UUID and explicit `pub:Computer=VIEW71/NotJoined`; generic `FriendlyName=Microsoft Publication Service Device Host` must never be selected.
- Parse this exact `/NotJoined` suffix as Windows-provided computer name `VIEW71`; retain strict hostname validation and reject unknown/malformed suffixes. Keep support for `/Workgroup:` and `/Domain:`.
- No hardcoded `VIEW71` in application code. No device identity merge. The Linux media VM is undergoing Ansible reprovisioning, so previous vs present MACs must not be conflated without post-install OS inspection.

## Verified Windows WSD computer names (0.1.10)

- Extends the WS-Discovery pilot using an optional HTTP SOAP WS-Transfer `Get` against the **same IPv4 host that emitted a WSD ProbeMatches response**, restricted to `http://<source-IP>:5357/<advertised UUID>` (Windows) or `http://<source-IP>:3702/<advertised UUID>` (Linux `wsdd2`). No hostnames/DNS, arbitrary ports, URL paths or query arguments, proxies or redirects. Request sent only after fresh unique direct ARP confirms IP->MAC and a matching WSD endpoint is already in SQLite; at most 8 metadata requests per scan. Timeouts under 2 seconds, responses capped to 32KiB. No passwords, OS privileges or changes to Windows settings.
- Only SOAP GetResponse with a matching `RelatesTo` request ID, actual WSD MetadataSection Relationship/Host endpoint UUID and explicit `pub:Computer` type is accepted as a **computer name**, e.g. `VIEW71/Workgroup:WORKGROUP` -> `VIEW71`. Generic `wsdp:ThisDevice/FriendlyName` is ignored (on Windows it may simply say `Microsoft Publication Service Device Host`); no fabricated labels from UUID, Domain/Workgroup, hardware vendor or service type.
- Additive SQLite v7 `wsd_names` records verified computer names per device + endpoint and last observation. The existing `devices.display_name` is only enriched if empty or equals its own MAC; existing meaningful names, UUID, MAC, Note, IPv4 evidence and all prior source records remain unchanged. No automatic identity merge or device creation.
- Diagnostic source metadata now includes verified names and per-device provenance. The Ingress WSD badge displays confirmed computer names when available. Technical 32-character hexadecimal mDNS host IDs are hidden only in the *Name* column, retained in the source and diagnostics.
- Empty/rejected/unreachable metadata is nonfatal and creates **no name**. Actual `VIEW71` and `MEDIA-SERZHAN` must be independently observed in WSD GetResponse at runtime before displayed.

### wsdd2 interoperability correction

- On a real Linux Samba media server running `wsdd2 1.8.7`, WSD multicast and HTTP use port 3702; Windows WSDAPI metadata uses port 5357. Both are allowed **only as an XAddr-origin already reported from a correlated WSD ProbeMatches message** and only for the exact UDP responder IPv4 and UUID path.
- `wsdd2` has a non-namespace-aware string parser for SOAP headers: requests must serialize the Action and MessageID with the canonical literal `wsa:` prefix; the former `a:` alias was XML-equivalent but skipped by `wsdd2`. The WSD Probe and Metadata Get now use `wsa:`, plus `wsdp:Device` in Probe types.
- `wsdd2` also expects an exact `Content-Type: application/soap+xml` on HTTP Metadata Get (no `charset` parameter). Adapt request header without broadening accepted response types or weakening correlation checks.
- No change to Samba, `wsdd2`, privileges, Windows, or NetAlertX.

## Release boundary

Version 0.1.0 proved HAOS install, Ingress, Web UI, data persistence, version and lifecycle. Version 0.1.2 added bounded native ARP probing; 0.1.3 added read-only diagnostics and source attribution; 0.1.4 adds independent IPv4 evidence and conflict resolution; 0.1.5 adds conservative mDNS/Bonjour metadata enrichment. These versions emit no machine events. It does not claim full IPv6 or cross-VLAN visibility. A genuine scan requires an explicit later version and tests for incomplete/invalid source data before any presence state or event is emitted.

When accepted, move from experimental Supervisor source build to the standard versioned immutable GHCR artifact. The install/update UI remains the **same Home Assistant App Store**, never a manual server-side copy.
