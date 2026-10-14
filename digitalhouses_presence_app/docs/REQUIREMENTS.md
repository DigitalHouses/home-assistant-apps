# DigitalHouses Presence App — requirements

Status: product scope recorded from the 14 October 2026 Home Assistant prototype discussion. Implementation and field acceptance pending.

## Users and registration

- Register each resident by one explicit Mobile Companion phone GPS `device_tracker` entity ID. Do not automatically include an iPad or second phone logged in under the same HA account.
- Registration UI performs a user-initiated WebSocket request on the mobile device. The Home Assistant Core adapter obtains the authenticated `connection.user` and actual peer address server-side; the browser must not provide trusted user identity.
- Allow registration only with independently confirmed direct local-LAN access. Cloudflare / Tailscale / reverse-proxy addresses are not proof of the phone's LAN IP.
- Resolve local IP to the device MAC using a **fresh** active ARP observation. Do not treat a stale neighbour-table record as fresh presence.
- A single HA user can own more than one Companion device; user equality alone does not authenticate a particular selected device. Binding integrity requires an additional proof or an explicit UX limitation.
- Ordinary residents may register their own devices where permitted. Only administrators can delete registrations or change app-wide settings. Authorize these actions server-side.
- Exclude HA administrators by not enrolling their trackers. Legacy `exclude_users` (HA User IDs) remains available only for explicitly linked legacy records. For tracker-only records, a nonempty User-ID exclusion list is a configuration error until the WebSocket identity binding can prove ownership; do not silently ignore it.

## Modes

| Mode | Authoritative decision | Secondary data |
| --- | --- | --- |
| GPS | Fresh GPS home/not_home observation | Wi-Fi source events; GPS distance |
| Wi-Fi | Trustworthy local network presence/absence | GPS distance |
| Hybrid | GPS, corrected by independently trustworthy Wi-Fi evidence | Source-specific events and diagnostics |

Hybrid policy: fresh confirmed Wi-Fi HOME can assert presence when GPS says NOT_HOME; a *verified continuously observed* Wi-Fi NOT_HOME for 15 minutes (configurable) can override GPS HOME. Individual `no_reply` ARP probes never qualify as verified absence. Scanner failure or stale evidence is UNAVAILABLE, not NOT_HOME.

## Safety and persistence

- Logical confirmed state (`home/not_home/unknown`) is independent from the availability/freshness of sources.
- Preserve the last confirmed logical state when source measurements become unavailable; never infer NOT_HOME from missing phone updates, dead battery, socket error or MQTT outage.
- Never publish OFF for an entirely unknown initial state.
- A first observation establishes an initial state without fabricating an arrival/departure event. Transitions should emit exactly once, after persisted and retained state is synchronized.
- Persist registration, stable resident keys, last confirmed state, and evidence timestamps under `/data`. A malformed existing persisted state file is an explicit error, not a silent reset.
- Stale GPS coordinates must not appear as current distance. Recorder tracks distance history; do not append measurement history as MQTT attributes.

## MQTT and UI

- One MQTT Device; one aggregate residents-home binary sensor with resident statuses in attributes.
- Individual GPS binary sensor and straight-line distance sensor per included resident.
- One MQTT Event entity with `arrival, departure, gps_in, gps_out, wifi_in, wifi_out`.
- Human-facing notifications are rendered only by HA packages: `event.received → trigger.id → choose → local action`.
- User-editable mode is configured in the App and exposed as `select.dh_presence_app_mode`. HA selection persists in `/data`; changing App Configuration's default wins on next startup.
- UI includes resident status and source freshness, mobile registration, admin configuration, MQTT/engine diagnostics, and DigitalHouses unified App operation card.
- Standard telemetry consent flag defaults to false; never include user IDs, IP/MAC, GPS positions, distances, or movement history in telemetry.

## Required proof before alarm integration

The iPhone tests do not establish 15+ minute continuously locked iOS reliability, DHCP/private-MAC recovery, multi-phone identity binding, or a trustworthy network-absence detector. Do not enable automatic alarm arming based on Presence App until these are tested and separately accepted.
