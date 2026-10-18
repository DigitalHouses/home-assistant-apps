# DigitalHouses Presence App — current requirements (0.1.27)

Status: experimental HAOS App. This document describes the currently implemented contract; deployment reliability and security-sensitive integrations require separate acceptance.

## Registration and exclusions

- Enrol residents using an explicitly selected phone GPS `device_tracker`; never automatically enrol every Companion device under the same HA user.
- Supervisor Ingress authenticates the HA user. Registration must prove a direct local LAN phone connection and freshly verify the phone's IP/MAC using one-time ARP. Cloudflare/VPN/reverse-proxy access cannot establish LAN presence.
- A matching Home Assistant router `device_tracker`, bound by verified MAC and stored with the resident registration, provides optional ongoing Wi-Fi presence evidence. Registration ARP must not become periodic presence polling.
- Only permitted authenticated operators can manage registration and configuration; administrators may inspect the private enrollment diagnostics, including IP/MAC, in the App's HA Ingress UI. No IP/MAC is transmitted in MQTT events, standard presence sensors or telemetry.
- `exclude_users` excludes verified HA User IDs from the resident roster and from **all** GPS, Wi-Fi, zone transition, distance, aggregate and notification activity. Admins who are excluded must not be tracked via the App's zone processor. Tracker-only legacy records without verified user ownership must fail closed when user-ID exclusions need to be enforced; do not assume a tracker belongs to a specific HA user.

## Sources and mode decisions

| Mode | Authoritative decision | Secondary source |
| --- | --- | --- |
| GPS | HA Mobile Companion GPS tracker home/away | Wi-Fi source events and distance |
| Wi-Fi | HA router tracker home/not_home (verified linked MAC) | GPS diagnostics |
| Hybrid | GPS with trustworthy router Wi-Fi correction | Independent source events |

- Wi-Fi observation belongs only to the HA installation's **local home** (`zone.home`). An office Wi-Fi connection to HA via Cloudflare does not qualify as local Wi-Fi evidence. Other HA zones are GPS-only.
- A missing, ambiguous, mismatched or unavailable router tracker gives Wi-Fi UNAVAILABLE, never a fabricated NOT_HOME.
- `wifi_absence_minutes` is a retained configuration compatibility field and is **ignored** since 0.1.25. Do not document legacy timed ARP absence as current behavior.
- Persist confirmed logical presence; source failures must not invent departures or healthy states. Initial observation is a baseline, not an arrival.

## Zones and events

- Discover existing `zone.*` entities from HA. Use HA's GPS tracker zone classification; **do not** implement independent geographic calculations.
- The App intentionally owns enrolled-resident zone transitions rather than directly exposing general HA zone triggers, so administrator/excluded users cannot generate DH Presence zone events.
- Persist per-resident zone baseline under `/data`; suppress repeated, stale, ambiguous, unavailable and initial-baseline transitions.
- Dynamically create per-zone MQTT notification switches on the same DH Presence device, default OFF. Keep GPS/Wi-Fi notification switches independent and persist selections.
- Preserve machine-event contract `event.dh_presence_app_event`: `arrival`, `departure`, `gps_in`, `gps_out`, `wifi_in`, `wifi_out`, `wifi_lost` (legacy, no longer produced) and `zone_enter`, `zone_leave`. Events are non-retained; local HA notification packages decide whether to call `script.write2log` based on the corresponding switch.
- Stable zone switch identity is based on `zone.entity_id`; editing the display name does not change it. A changed zone entity ID creates a new identity.

## MQTT, Recorder and UI

- One MQTT Device, one aggregate `binary_sensor.dh_presence_app_residents_home`, per-resident GPS/Wi-Fi binary sensors and distance sensors, plus diagnostics, operations, mode selection, notification switches and one Event entity.
- Preserve released MQTT identifiers and state semantics. Current GPS distance has no changing metadata attributes; do not add extra Recorder counters or dynamic history sensors for zone events.
- HA's native `zone.*` state is the source for the **person count card**; it counts configured HA persons and is not a count of DH Presence registrations.
- The private administrator Ingress diagnostics card may show registration IP/MAC, user/device association and source troubleshooting details. Ordinary users cannot retrieve those protected fields; do not confuse admin-only UI with MQTT/Recorder publication.
- Use the shared DigitalHouses product status/control card. Human-readable messages are generated in the site's HA package rather than the public App.
- `telemetry_enabled` remains in configuration for the experimental pilot, but this product is not yet admitted to reporting (`telemetry_allowed: false`, `release: null` in the registry). No statistics sender is implemented; telemetry migration is deferred.

## Acceptance limitations

Verify actual router tracker reliability, multi-device ownership binding and site-specific exclusions before integrating this pilot with alarms or other safety-sensitive decisions. Presence reports are not a substitute for verified security signals.

## Recent events UI contract (0.1.28)

- App Configuration `events_history_limit` defaults to 5 (valid 1–20); the App owns truncation, storage and ordering. HA must not keep a parallel last-five list via helpers, templates or automations.
- Append a history entry only after successful publish of a current MQTT machine Event. Persist a bounded JSON list under `/data`, restore on startup and prune records belonging to excluded/nonparticipating residents.
- Publish only a read-only retained MQTT diagnostic view for the last N events. The UI has only App-provided label/details/timestamp and local timestamp formatting. Never put IP/MAC/credentials in this history.
- **Exclude the changing diagnostic history sensor from Home Assistant Recorder**. This is not a per-event measurement history entity; retain the original machine Event contract and any existing Recorder policy for it.
