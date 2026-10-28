# DH Network App — architecture and implementation notes

## Product identity

- Public product: DigitalHouses Network App
- Canonical ID / repository directory / Supervisor slug: `digitalhouses_network_app`
- Compact namespace: `dh_network_app`
- Web UI: Home Assistant Ingress (not a second externally exposed admin service)
- Storage: SQLite `/data/network.sqlite3`
- Current version: `0.1.16`, experimental, no GHCR artifact and no telemetry

This App deliberately follows the existing product-naming and HAOS packaging standards. Its **Ingress** UI is the accepted departure from the usual MQTT-discovered Lovelace control card: UI state, notes and inventory are App-owned instead of built from MQTT entities. Any future machine events must follow DigitalHouses Events & Notifications Standard; local alert delivery belongs to HA, not the public App.

## New device first-positive evidence and MQTT machine events (0.1.16)

- Add schema v8 `device_births` table (one row per UUID) with `first_positive_at` and `publish_state`. SQLite triggers capture the initial confirmed positive (`online` with nonempty `last_seen`), not a router's `not_home` or `unknown` entry. Existing installed devices are seeded as `suppressed`, retaining UUID/Notes; no legacy notification flood.
- Devices display a `NEW` badge during the first 24h following `first_positive_at`; no periodic database mutation or time-based watcher is needed, with a 30-second UI refresh. Restart/renaming/IP rotation does not renew NEW.
- On a brand-new database and after explicit Reset, first census is quiet for 120s: initial observations are shown as NEW but not published as notifications. Normal first-positive inserts after this period have `pending` event state.
- Separate Python MQTT worker uses Supervisor `mqtt:want` service, Paho MQTT and SQLite WAL; the Go collector stays independent. HA MQTT Event Discovery is retained, `device_discovered` payloads are QoS 1 / `retain:false`, and the outbox marks `published` only after PUBACK. A reconnect may resend an event if interrupted after broker ACK but before commit: consumers should deduplicate using `device_id` if exactly-once notification is required.
- Event contract: required `schema_version:2`, `event_type:device_discovered`, `observed_at`, `device_id`, `detection_source`; optional verified `mac`, `ipv4`, `name`. No localized message/title or delivery settings. The local HAOS notification package consumes `event.received` and owns language and delivery.
- `event.dh_network_app_network`, `sensor.dh_network_app_version`, `sensor.dh_network_app_started_at` have stable discovery IDs and runtime MQTT availability. Initial events are not replayed after Reset. Reset clears `device_births` and sets a fresh quiet-census threshold.
- The method-grouped `monitored_devices` YAML with optional UTF-8 `label` is separately approved but **not configured or enabled** here. HAOS Supervisor's nested YAML editor/schema limits require live compatibility verification; inventing a different configuration format is intentionally avoided.

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

## Reset confirmation display fix (0.1.15)

- Replace double-escaped `\\n` with the JavaScript newline escape `\n` in the destructive Reset prompt. User sees a genuine two-line confirmation, not literal backslash and `n` characters.
- Browser regression test executes the Reset handler, intercepts the prompt, and verifies the rendered string contains the newline and that cancelling the dialog makes no API call.
- No change to SQLite tables, reset permissions, scan-generation logic, notes, or existing network observations.

## Confirmed inventory reset (0.1.14)

- Admin-only Supervisor Ingress exposes `POST /api/inventory/reset` with `Content-Type: application/json`, custom `X-DH-UI: 1` header, and exact JSON `{"confirmation":"RESET"}`. The Ingress peer is independently restricted to the Supervisor proxy address. Cross-origin HTML forms cannot invoke this JSON-only action.
- The destructive button is visible only in the expanded `Показатели` panel. The user must first type `RESET`, then approve a final dialog explaining the irreversible loss of devices/UUIDs, Notes, source history, WSD/mDNS/SSDP evidence, conflicts and events. UI sends nothing when either confirmation fails.
- Reset takes a generation-write lock and deletes all 16 persisted inventory/source/history tables inside **one SQLite transaction**. Failure rolls back without partial deletion. `schema_version`, existing schema/migrations, Supervisor options and network/HA settings remain unchanged. The App does not create an automatic backup; users can export diagnostic JSON beforehand. This is logical SQLite row deletion, not a promise of forensic secure erase.
- Each scanner captures an epoch before network IO and rechecks it under a read-lock before persisting: any result begun before Reset is discarded. A fresh cycle starts router import, then ARP/local interface, then mDNS/SSDP/WSD enrichment; regular intervals continue independently. No manual service restart required.
- Reset may intentionally change all generated device UUIDs, and previous Notes are **not recovered**. No IP-based merging, direct hardware reconfiguration, or old-media-server reconciliation is attempted.

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


## Immediate Presence baseline and Online hover (0.1.22)

Enabling an IP or MAC Presence subscription via the three-dot address menu
automatically schedules an out-of-cycle **shared LAN ARP scan**. The request
does not launch a per-device ping or block the Ingress HTTP request. A single
global scanner serializes periodic and on-demand scans, and coalesces
simultaneous enable actions. Editing notifications alone does not scan.

The newly enabled subscription immediately shows **Working**. Until a
successful scan that **started after activation** completes, the UI does not
reuse stale earlier results. ARP source failure yields an explicit unknown
state, not a false absence. After the first successful scan, progress is
shown as **confirming** with the number of positive/negative observations
out of the global thresholds (default 2 positives, 3 negatives).
The accepted state becomes "Обнаружен" or "Не обнаружен" only after enough
independent global scans; the first confirmation is an event-free baseline.

The green eye hover shows human-readable status, last scan time, last
positive observation and last state transition. While confirmation is
in progress, the UI refreshes it every four seconds.

The Online tag hover and keyboard focus show the **exact date and time with
seconds** of the last accepted positive observation, as recorded by the
inventory. Its evidence comes from ARP and/or the Home Assistant router
integration, NOT from an ICMP ping. A router-reported "home" may reflect
the router integration's state rather than an independent fresh response.

## Ingress Presence, settings, event journal and Help (0.1.21)

**Top navigation:** Устройства, Источники, Журнал событий, Параметры, Помощь.
The old YAML Monitoring tab is hidden; existing monitored_devices.yaml and its
watch engine are preserved for compatibility, without automatic migration.

**IP/MAC Presence:** Open the three-dot menu beside the exact IP or MAC in
the Devices table. Copy the address, subscribe to Presence, or opt into local
DigitalHouses notifications. A green eye means the subscription is active,
NOT that the endpoint is online. The tooltip includes last check, last
positive observation, last confirmed change, current state, and reason.
IP watches a literal IPv4 address; MAC follows the physical address across
DHCP changes. No per-target scan intervals exist.

**Shared discovery:** New Presence subscriptions use completed global ARP
discovery snapshots, never a new independent per-device ICMP or ARP scanner.
Every successful scan contributes one sample. Defaults: two positives to
confirm presence, three successful misses to confirm absence. Stale,
unavailable or ambiguous sources cannot confirm disappearance. Initial
subscription baselines are quiet, and events are generated only on later
confirmed changes. Only on-link IPv4 addresses and locally observable MACs
are supported by this engine; remote targets need another observation source.

**Global settings:** Параметры persists the five discovery intervals and
Presence confirmation thresholds in the app SQLite database. Existing HAOS
App options are used as initial values on first startup; later changes take
effect at the next scan cycle. Settings survive app restarts.

**Event journal:** Dedicated SQLite event_delivery_log contains outbound
machine event_type, event_id, target, original JSON, observed timestamp,
delivery attempts, broker ACK timestamp and status. A broker_acked entry
means MQTT QoS 1 PUBACK, NOT confirmed Home Assistant automation execution.
The journal excludes internal IPv4 disagreement diagnostics. Copy exact
event_type, JSON, and a valid Home Assistant event.received YAML trigger
targeting event.dh_network_app_network from the event details.

**Optional HA package:** examples/ha_packages/dh_network_notifications.yaml
can be installed on the owner's Home Assistant. It turns opt-in Presence
events into persistent notifications and includes a global NEW DEVICE
notification toggle. This separate package is NOT installed by the app:
selecting the UI preference records intent, but does not itself deliver
notifications until HA installs the package. The local owner may implement
other delivery channels independently.

Reset clears pending runtime Presence events and the delivery journal
alongside the inventory; it retains global settings and subscription
configuration, restarting a quiet observation baseline. Existing device
UUIDs, Notes and LAN evidence are preserved by normal upgrades.

## Inventory table usability (0.1.20)

The **Устройства** table includes a drag handle at the right edge of each
of its seven data column headers. Drag to adjust the width; use keyboard
Left/Right arrows on a focused handle for 16px increments, Home or double
click to reset that column to its default width. The table scrolls
horizontally if needed. Width preferences are stored only in the local
browser and are not synchronized between users. Reloads and periodic
30-second refreshes preserve the selected widths.

Hover over a populated cell or focus it via keyboard to reveal the small
copy icon. This copies the **complete** value, even when the cell is
visually truncated, for name, IP (both addresses if present), MAC,
observation, source names, last Online and saved Note. Notes retain their
separate edit action. Clipboard failures show an explicit message; the UI
attempts the legacy browser copy method for restricted Ingress contexts.
A compact status message confirms success. Names that contain an exact
duplicate phrase from an HA router are collapsed for UI display only;
stored inventory names are not modified.

Selected-device monitoring (since 0.1.18)

The **Мониторинг** Ingress tab lets an HA administrator edit the explicit
`monitored_devices` YAML configuration. It is stored as UTF-8 in the App
persistent volume at `/data/monitored_devices.yaml`. The editor validates the
file before replacing it atomically. The previous valid file is retained when
validation fails. The monitoring worker picks up changes automatically.

**No watches are configured by default.** The addresses below illustrate
the format only; they are not automatically added or enabled:

```yaml
monitored_devices:
  icmp:
    media_server:
      ip: 192.168.11.238
      label: "Медиасервер"
    web_server: 192.168.11.240
  arp:
    workstation:
      mac: "18:31:BF:2F:ED:37"
      label: "Рабочий компьютер"
  ha_device_tracker:
    phone:
      entity_id: device_tracker.phone
      label: "Телефон"
  tcp:
    plex:
      ip: 192.168.11.238
      port: 32400
      label: "Plex"
```

Grouping is by check method. The stable technical `watch_id` belongs to
the YAML key, not to a discovered inventory UUID. Scalar form is supported
for ICMP IP, ARP MAC and HA tracker entity_id; TCP requires both IP and port.
Optional `label` is user-owned and is not overwritten by HA/Bonjour/WSD.
The same watch_id may be used in different methods; states remain independent.

- **icmp** checks IPv4 Echo Replies using a raw socket (NET_RAW); filtered
  ICMP is only ICMP-unreachable, not proof the machine is powered off.
- **tcp** tests the configured IP:port; failure indicates that service is
  unreachable, not necessarily that the host is off.
- **arp** uses fresh direct ARP evidence for the configured MAC, never
  the wider `lan_positive` registry (which also includes local interface
  observations). An absent MAC means only "not observed in that ARP scan".
  Each completed ARP scan counts once; default scan interval is 180 seconds.
- **ha_device_tracker** uses the explicitly configured HA entity, with
  `home` and `not_home` as positive/negative. Debounce counts advance
  only on distinct, fresh `last_reported` revisions supplied by the Home
  Assistant REST state object. Repeated reads of the same cached report do
  not count as new observations. When there is no timestamp or the last
  report is older than 180 seconds, the result is unknown, not absent.
  An integration that does not periodically report unchanged state will
  therefore remain unknown until enough independent reports arrive.

Default ICMP/TCP cadence is 30 seconds and HA tracker cadence is 60 seconds.
A transition is confirmed by 2 consecutive positive or 3 consecutive
negative **independent** observations. On initial startup a baseline state is
learned without emitting a transition; source errors result in unknown and
must not manufacture a negative transition. State survives worker restart.
Inventory Online/Not observed is **unaffected by this separate monitoring**.

Each watch has retained Home Assistant MQTT sensor Discovery/state under
`DigitalHouses/Global/dh_network_app/monitor/<method>/<watch_id>/`.
Confirmed transitions publish machine events with `schema_version: 2`,
`event_id`, `event_type` (tracked_device_reachable/unreachable/present/
absent), `observed_at`, `check_method`, `watch_id`, previous/current state,
source-specific target, and optional `label`. QoS 1, no retain for events;
outbox uses stable event IDs for downstream deduplication on retries.
The App owns no language-specific notification delivery; consumers configure
their own Home Assistant event automations. MQTT is optional: the local
monitor state still updates when the broker is disconnected, and events are
queued for later delivery. Retained Discovery and state are republished
after every broker reconnect, including a short disconnect between worker
poll cycles.

Validation errors identify bad paths; malformed YAML is not silently accepted.
The editor is an administrator-only Ingress operation and does not change
HAOS, router, Proxmox, endpoint network configuration or inventory records.
