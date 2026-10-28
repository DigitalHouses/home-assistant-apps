# Changelog

## 0.1.24

- Fix missing green **Presence eyes** after reopening Devices or a periodic refresh: the UI now reloads persisted IP/MAC subscriptions from the Ingress Presence API before rendering device rows. Existing SQLite subscriptions and event history remain untouched.
- The IP/MAC three-dot menu now closes on clicking outside or pressing Escape; clicking inside or using another address trigger retains correct interaction.
- Remove the top-header **Показатели** dropdown completely. Move every item of its content to the **Параметры** tab: device/source/scan counters, health status, IP disagreement count, the native diagnostic JSON download and fallback preview/copy, plus destructive inventory Reset.
- Keep all five navigation tabs in the header, and globally configurable scan intervals in the same Settings tab.
- Include regression tests for repeated Devices reloads restoring stored subscriptions, outside-click/Escape semantics, and complete relocation of metrics, diagnostics and Reset.
- User-supplied diagnostic JSON (0.1.23) verified 5 active confirmed subscriptions (3 IP + 2 MAC), 4 broker-acknowledged outbound events, and no queued/retrying events: eye disappearance was a UI state-loading regression, not lost monitoring data.


## 0.1.23

- Fix event journal **Copy HA trigger**, **Copy JSON** and event_type buttons. An absent HTML title no longer throws before calling the clipboard; buttons have explicit accessible copy labels. Add DOM click tests with multiline JSON and YAML.
- Replace Ingress sandbox-sensitive JavaScript Blob download with a **native, user-clicked server attachment** (GET /api/diagnostics/download). No file is written to disk; attachment has a timestamped JSON filename, no-cache headers, and remains restricted to the authenticated Ingress path.
- Add **Показать JSON** fallback preview and **Скопировать весь JSON**; the read-only JSON is selectable even when the browser disallows downloads or clipboard access. Do not claim a download succeeded when the app cannot confirm it.
- Expand the diagnostic report with temporary bounded debug data: global scan and Presence settings, all opted-in watches and states, legacy monitoring states, recent 150 MQTT delivery entries, outgoing queue counts, event status counts, and scan/source evidence. No credentials or passwords.
- Keep device UUID, Notes and prior monitoring config intact; no live HAOS deployment.


## 0.1.22

- Enabling a new IP/MAC Presence subscription immediately schedules one out-of-cycle **global LAN ARP scan**. Concurrent activations coalesce, and periodic/on-demand scans serialize to avoid overlapping scanners. Changing notification settings alone never forces a scan.
- New subscriptions enter visible **Working** state before the UI action is acknowledged. After the first completed qualifying scan, the interface shows the observation and confirmation progress (e.g. 1 of 2 positive observations) instead of misleading blank/unknown readings. The initial baseline remains quiet and does not emit a false transition event.
- A scan that began before subscription activation is excluded even if it completed afterwards; true scan-start timestamps preserve sub-second ordering. Source failures become unknown rather than offline.
- An active Presence eye exposes understandable status, scan time, last positive and last change; the interface refreshes active progress without waiting for the normal 30-second inventory refresh.
- Hovering or focusing the Online state now shows an explicit date and time (with seconds) of the latest accepted positive ARP/HA router observation. The icon does not pretend that ICMP Ping was performed.
- Regression tests for scan coalescing, working/confirming state, stale scan rejection, source failures and Online timestamps.


## 0.1.21

- Ingress top navigation: Devices, Sources, Event Journal, Global Settings, and plain-language Help; the legacy YAML Monitor editor is removed from navigation while its files remain compatible.
- IP/MAC three-dot menu: copy address, subscribe to IP Presence or MAC Presence, and record an opt-in for an external DigitalHouses HA notification package. Active subscriptions show a green eye with status/last-check/last-seen/transition hover details.
- Global scan intervals and presence confirmation thresholds persist in SQLite; the shared scanner schedules re-read intervals without restarting the App.
- New Presence engine reads completed global LAN ARP scans, counts each successful scan once, distinguishes unknown on source failures, and publishes presence transitions with stable machine event IDs and durable QoS 1 outbox. No new per-device scanner.
- New MQTT delivery journal includes exact event_type, event_id, JSON, broker acknowledgements, copyable Home Assistant trigger snippets, and search/filter controls. Internal IPv4 disagreement diagnostics are excluded.
- Retains existing device UUIDs, Notes, IPv4 evidence and old YAML monitoring configuration; does not modify the client's running instance.
- The HA notification delivery package remains an external opt-in; enabling that preference only sets metadata until installed.


## 0.1.20

- **Ingress inventory table:** resize any of the seven data columns by dragging its header edge; keyboard arrows resize, Home or double click resets individual column widths. Widths are bounded, stored only in browser localStorage, survive refresh and stay independent for different browsers.
- **Copy full cell value:** a small copy icon appears on hover or keyboard focus for name, IP, MAC, observation, source list, last Online, and nonempty Note; copies full original text rather than truncated display, with clipboard API and legacy fallback, plus accessible success/failure feedback.
- UI-only deduplication of accidentally repeated whole-name labels from some router trackers (e.g. `Express 7 Express 7`), preserving actual names, UUIDs and SQLite history.
- New Node regression tests for width controls, persistence, safe escaping, copy feedback and clipboard fallback. No server state, HAOS or scan behavior changed.


## 0.1.19

- Count independent HA device_tracker observations only when the REST state carries a fresh, new `last_reported` revision; repeated REST reads of the same cached snapshot do not advance 2/3 debounce, and missing/aged reports become unknown, not a false absence.
- ARP monitoring now accepts only explicit per-MAC `ipv4_evidence` from the ARP scanner. A local-interface / `lan_positive` row is not an ARP reply.
- Track MQTT broker connection generations and republish retained watch Discovery/state even when disconnect and reconnect occur between monitor worker cycles.
- Add regression coverage for duplicate/stale tracker snapshots, genuine ARP evidence and short MQTT reconnects. No monitoring targets are enabled by default; inventory UUIDs, Notes and Online rules remain unchanged.


## 0.1.18

- Add separate monitored_devices YAML configuration editor under Ingress, preserving nested method-grouped scalar/mapping syntax and optional UTF-8 Russian labels; strict validation precedes atomic update of /data/monitored_devices.yaml. No monitored devices enabled by default.
- Add independent ICMPv4, ARP, HA device_tracker and TCP monitoring, persistent per-method state and 2-success/3-failure transition debounce, unknown handling for source failures, and no changes to inventory Online/Not observed semantics.
- Publish per-watch retained MQTT state/discovery and QoS 1 non-retained tracked-device machine transition events with event_id deduplication and local SQLite journal; optional MQTT failures do not stop monitoring.
- Add monitoring-state Ingress table, regression tests and a backward-compatible SQLite schema v10; existing UUIDs and Notes are preserved.


## 0.1.17

- End the first-install and post-Reset notification baseline only after successful HA router tracker AND LAN ARP source snapshots, not after an arbitrary two-minute timer. Pending initial-census births remain silent throughout delayed scans or MQTT reconnects.
- Persist the detection source at the first positive observation (ARP, HA router tracker or local interface); later source enrichment cannot rewrite the original event provenance.
- Add deterministic `event_id` to transient `device_discovered` events so MQTT QoS 1 retries can be deduplicated after a crash between PUBACK and SQLite outbox acknowledgement.
- Add backward-compatible SQLite schema v9 migration without touching established device IDs, Notes, first-positive times or prior outbox state; explicit Reset restarts the census gate.
- Add regression coverage for baseline completion, restart, first evidence, MQTT event idempotency and active-census event suppression.


## 0.1.16

- Add a 24-hour NEW badge driven by persistent first-positive evidence; not-home/unknown sources do not count as newly online.
- Add MQTT Event Discovery and durable QoS1 `device_discovered` publisher (non-retained event, retained discovery, optional MQTT service); existing inventory and initial/reset census are suppressed from event notifications.
- Persist event outbox in SQLite schema v8 and expose first-positive timestamps for Ingress.
- Retain previous UUIDs/Notes, all scanners and current Online/Not observed semantics.
- Grouped monitored_devices configuration is deliberately not enabled until native HAOS configuration schema compatibility is verified.

## 0.1.15

- Fix Reset confirmation prompt displaying literal `\n` instead of an actual line break.
- Add a browser test for the rendered prompt and cancellation without an API call.
- No changes to Reset semantics or database schema.

## 0.1.14

- Add guarded Reset button to the Ingress `Показатели` panel; requires typing `RESET` and final explicit confirmation.
- Atomic SQLite reset of all 16 inventory, Notes, identity, discovery, source and event tables. Preserve schema version, addon config and hardware settings; errors roll back.
- Reject in-flight scan results begun before reset using an epoch gate, then immediately restart discovery (router, ARP, mDNS/SSDP/WSD). Maintain normal background pollers.
- Ingress-only JSON API with exact request challenge, custom header and bounded body. Unit tests cover permission/confirmation, fresh UUID/Notes after reset, rollback, and stale results; Ingress JS tests cover UX.

## 0.1.13

- Remove the large orange explanatory notice from the collapsed-by-default `Показатели` menu, while retaining the concise neutral Online-vs-ping statement and independent real-conflict warning in the main view.
- Simplify JSON diagnostic export confirmation: remove `Пришли его в чат для анализа.`.
- Put `Устройства (N)` and the search field in one flexible row, with search immediately to the right of the device count; keep input focus across periodic refresh and filtering, and hide this row on other tabs.
- Keep all eleven counters, export, existing source data and persistence unchanged.

## 0.1.12

- Refactor Ingress to a persistent compact header with product name, always-visible Devices / Sources / Events navigation, and a keyboard-accessible `Показатели` disclosure. All 11 existing metric cards, explanatory source notice and JSON diagnostic export are collapsed in the header by default and shown when opened. A serious active conflict warning remains outside the collapsed panel.
- Clarify `Online` as presence observed via ARP, HA router tracker or Local Interface, **not** successful ICMP ping. Retain backend status values and history semantics without inventing ICMP results.
- Preserve notes, JSON export, table sorting/filtering, API, polling cadence, source/UUID/identity models and database schema.
- Add Ingress markup regression tests for visible navigation, closed-by-default metrics, accessible disclosure and absence of invented ping claims.

## 0.1.11

- Accept the explicitly observed Windows WSD `pub:Computer` suffix `/NotJoined` (example `VIEW71/NotJoined`), in addition to `/Workgroup:` and `/Domain:`; the result is a verified computer name, **never** the generic WSD `FriendlyName`.
- Regression tests cover real `VIEW71/NotJoined` metadata, malformed suffixes, unrelated SOAP replies, endpoint mismatch, and the existing Workgroup/Domain forms.
- No changes to WSD network access policy, IP/MAC matching, Notes, UUIDs, SQLite schema, or existing Samba settings. The media server is being reinstalled independently via Ansible: its changing MAC/device identity is **not** reconciled or merged automatically.

## 0.1.10

- Extend WSD pilot with tightly scoped, read-only Windows WS-Transfer Metadata Get. Accept verified `pub:Computer` hostnames only; never use generic `FriendlyName` (often the Windows publication service title).
- Correlate SOAP request/response IDs and endpoint UUID; allow only IP-literal advertised WSD ports 5357 (Windows) or 3702 (wsdd2), bound timeouts/payloads, disable proxy and HTTP redirects.
- Preserve UUID/Notes/history and existing meaningful names, only upgrade an empty/MAC-placeholder display name; store verified provenance in additive SQLite v7 `wsd_names`.
- Fix Linux wsdd2 interoperability: canonical literal `wsa:` SOAP request headers and `wsdp:Device` Probe type, bare `application/soap+xml` HTTP content type, metadata port 3702 in addition to 5357.
- WSD badge and diagnostic export include the observed computer name. Hide 32-char opaque mDNS IDs from Name without losing source records.

## 0.1.9

- Register the host OS default-route LAN IPv4/MAC as direct positive `Local Interface` evidence; fixes HAOS own .33 being omitted from active ARP and wrongly assigned an ASUS Media Bridge Wi-Fi MAC via imported router trackers.
- Protect names, UUIDs, IP histories, Notes, and existing devices; local source takes precedence over router IP assertions and records any discrepancy as a non-alarming local event.
- Add active multicast **WS-Discovery** SOAP ProbeMatches collection, strict source/correlation/response bounds, no remote metadata GET, no fabricated computer name. Match device only through fresh unique ARP or Local Interface.
- New source badge, diagnostics endpoint, and additive SQLite schema v6 for retained WS-Discovery metadata; no new device creation from WSD, no secrets read from arbitrary URLs, no new privileges.
- Automated tests for local source identity, IPV4 precedence, preserved Notes and truthful WSD SOAP records.

## 0.1.8

- First column is dynamic sequential row number (recomputed after active filtering and sorting); the second is the discovered device name, followed by IP, MAC, Presence, sources, last Online and Note.
- The Name column shows **only a verified human-readable name from the existing inventory**: MAC-formatted names (colon-, dash-separated, or 12-hex without separators), UUID and IPv4 placeholders are represented as an em dash. The underlying MAC, hostname and identity values remain available in their own columns and diagnostic JSON.
- Note cell is a compact, single-line action: `Добавить` for empty notes, or the actual note text (click to edit) for existing notes. Long notes are visually truncated with full text available in hover tooltip; the editable underlying note is never truncated.
- Every row is visually constrained to one line, using tooltips/ellipsis and horizontal scroll if needed, to keep 30+ devices readable.
- Preserve sorting of all seven data columns, search by MAC/notes, stable device UUIDs, Note editing and diagnostic export with display columns matching the new layout.
- Browser JavaScript tests cover name placeholders, actual discovered names, sort/filter row indexes, compact Notes, and HTML injection escaping. No DB schema/permissions/scanner changes.

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
