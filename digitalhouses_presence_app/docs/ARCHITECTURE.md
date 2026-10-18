# DigitalHouses Presence App — runtime architecture (0.1.27)

Status: experimental HAOS App. Earlier ARP/PING presence pilots (0.1.14–0.1.24) have been superseded by HA router trackers since 0.1.25. Registration still performs **one-time** active ARP verification. See the changelog for historical pilots.

## Responsibilities and data flow

```text
HA Mobile Companion GPS device_tracker ────────────┐
                                                    ├→ enrolled-resident state engine
HA router Wi-Fi device_tracker (MAC-bound) ─────────┘  ├→ durable confirmed state (/data)
                                                       ├→ retained MQTT Discovery/state
HA zone.* catalogue + GPS tracker zone state ─────────→ enrolled-resident ZoneMonitor
                                                       └→ QoS1 non-retained machine events
                                                                    ↓
                                                      local HA notification package
                                                        event.received / write2log
```

**App-owned zone filtering is intentional.** Native HA zone triggers can consider HA persons outside the DH Presence roster, including administrators. The App processes **only** resident trackers eligible after user-ID exclusions; `exclude_users` is enforced before zone monitoring. The App reuses HA's own zone classification, does **not** calculate a second geofence, persists the last eligible resident zone baseline and publishes `zone_enter`/`zone_leave` after a true observed transition. Ambiguous zone names, stale observations and unavailability do not assert transitions. A new baseline does not fabricate an entrance.

The App owns identity binding, exclusions, source evidence, state persistence, MQTT and authenticated registration. HA owns the geographic zone definitions and underlying tracker state. The local HA package owns language, event gating and delivery; the reusable App does not call private `write2log` services.

## GPS / Wi-Fi / Hybrid

- GPS: authoritative Companion tracker status, including native HA zone labels and last source report timestamp.
- Wi-Fi: the resident's saved router `device_tracker` linked by MAC. Only a valid unique `source_type: router` association may supply `home`/`not_home`; source errors/ambiguity become UNAVAILABLE.
- **Wi-Fi = `zone.home` only**: it represents the *local router network at the HA installation*, not arbitrary HA zones or the phone's ability to reach HA remotely over Cloudflare. Other zones rely on GPS.
- Hybrid: combines GPS with independently trusted local router tracker evidence according to the existing state engine. `wifi_absence_minutes` is a legacy compatibility option ignored since 0.1.25. Do not treat lost API access as a verified negative.
- All modes: source-specific machine events and diagnostics remain independent of the aggregate selected mode. Preserve unknown and last-known distinctions; never manufacture departure due to source failure.

## Registration and protected IP/MAC diagnostics

Supervisor native Ingress authenticates the user. Registration requires local direct access to HA; the App verifies the apparent local phone address and performs a fresh on-link ARP MAC proof. This one-time identity binding is not the runtime Wi-Fi monitoring algorithm.

The server keeps enrollment name/user/tracker/IP/MAC in private `/data` state. Home Assistant administrators may see IP and MAC in the private administrative Ingress diagnostics card, with server-side admin authorization. Ordinary residents must not access that data. MQTT states/events, shared dashboards and Recorder do not publish these registration IP/MAC fields.

Multi-device ownership remains an explicit experimental limitation: an authenticated HA user session does not cryptographically attest that the selected Companion tracker belongs to that exact physical device. No alarm automation is accepted on this pilot alone.

The current experimental registration uses narrowly approved `host_network` and `NET_RAW` for the one-time ARP proof only. Do not expand container privileges for routine Wi-Fi presence.

## MQTT contracts, operations, Recorder

- One stable HA MQTT device `dh_presence_app`, published via `homeassistant/device/dh_presence_app/config`.
- Retained states express current facts; QoS1 non-retained MQTT Event payloads express actual transitions only. Synchronize confirmed state before transient events, never replay old transitions after MQTT reconnect.
- Public machine events are independent of switch configuration. Zone notification switches are dynamic, persisted and OFF by default; source GPS/Wi-Fi notification switches are independent. The obsolete general presence switch is retired.
- `script.write2log` is a **site-specific local HA package** action, not a dependency of App execution.
- Per-resident distance sensor uses the current distance without changing attributes. The aggregate resident roster has bounded status/identity metadata: review Recorder update volume before expanding it. Do not add zone count sensors when native `zone.*` person counts are already available.
- IP/MAC remain available through admin-only Ingress, not through retained MQTT attributes or machine event payloads.
- The single status/control card follows the repository's Unified Product Status Card contract. Product runtime owns operation facts; the dashboard formats them.

## Lifecycle and deferred production gates

The App is experimental and installed from repository sources without a GHCR `image:`. Registry entry `digitalhouses_presence_app` currently has `telemetry_allowed: false` and `release: null`; runtime warns if `telemetry_enabled` is selected but does not send usage statistics. Immutable image delivery and telemetry eligibility are separate, deferred production tasks.

For exact fields and identifiers see [MQTT_CONTRACT.md](MQTT_CONTRACT.md). For scenario coverage see [TEST_PLAN.md](TEST_PLAN.md). For historical release changes see [CHANGELOG.md](../CHANGELOG.md).

## Bounded UI event history (0.1.28)

The App owns a separate bounded and durable **presentation-only** history cache at `/data/presence_event_history.json`. Its size is controlled solely by `events_history_limit` in Supervisor App Configuration (default 5, range 1–20). An entry is appended only after a transient machine Event publish is acknowledged by MQTT; the App prepares its label/details. Existing registered-resident filters apply and excluded/removed residents are removed from the retained cache. Restart never emits synthetic transitions or backfills lost events.

The only HA interface is one new MQTT diagnostic sensor exposing a retained snapshot of App-prepared `items` on `events/history`. The Markdown card simply loops over these items and formats local time. This is a UI state read model, not an alternative event transport or a local HA templated-history engine. No extra helper/automation/second event stream is added.

Because the list changes whenever an Event arrives, **`sensor.dh_presence_app_recent_events` must be excluded from the local Recorder**. The App's own bounded file is authoritative for the short UI history; native machine Event history remains separate under the home's normal Recorder policy.
