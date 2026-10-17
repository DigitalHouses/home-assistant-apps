# DigitalHouses Presence App

**Status: experimental GPS + configurable PING/ARP network-reachability pilot, version 0.1.24.** Observe for several days; do not use for alarm arming until accepted.

This application belongs to `DigitalHouses/home-assistant-apps/digitalhouses_presence_app` and is installed via **Settings → Apps → App Store**.

## Stored router Wi-Fi tracker (0.1.24)

From the local Ingress phone registration UI, selecting a GPS tracker previews a matching HA router `device_tracker` by the phone's actively ARP-verified MAC. Pressing **Зарегистрировать** now persists the matched `wifi_tracker` on the same resident registry record. On an existing registered GPS tracker (same authenticated user, same verified MAC), only the Wi-Fi link is updated; registration fields are preserved. If no unique router tracker is available, GPS registration still works and a previously stored Wi-Fi link is retained. Admin debug displays the linked entity and its current HA state. Older registry files load without changes.

**Important:** This is a stored association only. The App still uses its existing PING/ARP probes for actual Wi-Fi status and does not yet switch the presence engine to HA router trackers. GPS and notifications remain unchanged.

## Wi-Fi presence and hybrid mode (0.1.17)

Every 60 seconds the App probes the enrolled private LAN IP with direct `arping`. A valid reply from the exact registered MAC means Wi-Fi HOME. A *completed* ARP probe with **zero responses** for 15 consecutive minutes (configurable) means the device is not reachable by ARP: Wi-Fi binary sensor **OFF**. This may generate `wifi_out` and in `hybrid` mode an actual departure / last-person-left decision even if the last iOS GPS reading was HOME. A later verified MAC response restores HOME. Default `gps` mode remains independent of Wi-Fi absence.

**Important limitation:** iOS may not answer ARP during sleep while still on Wi-Fi. Wi-Fi OFF here means *not detected by active LAN probe*, not proof of Wi-Fi being switched off. On-link route, execution or permission failures and MAC conflicts produce `unavailable` instead, reset the absence timer and never produce a negative presence transition. No Nmap, router, NetAlertX or extra HA tracking entity is required.

The maintained dashboard dynamically creates a Mushroom card for each configured resident (name + device): final presence status and its transition timestamp; GPS status/transition timestamp; Wi-Fi status/transition timestamp. Unknown timestamps render as a dash. All timestamps originate in the App's existing MQTT resident roster, and are shown in the browser's local timezone. There is no manual per-person YAML configuration and no IP/MAC exposed in MQTT.

## Global household Wi-Fi detection switches (0.1.22)

Two persisted MQTT switches on the **existing DH Presence device** control **all registered phones**, not individual residents:

- `switch.dh_presence_app_ping` — ICMP echo to the registered private IP; default OFF.
- `switch.dh_presence_app_arp` — active ARP with exact registered MAC verification; default ON (legacy behavior).

Both ON: **any successful method → Wi-Fi HOME**. Only when **both** enabled checks finish with explicit no-reply does the configured `wifi_absence_minutes` negative debounce run; probe errors or ARP MAC conflicts are inconclusive. If both OFF, Wi-Fi monitoring is disabled and its sensors report UNAVAILABLE (not OFF). GPS mode stays independent; Hybrid falls back to GPS during Wi-Fi uncertainty. Switching either method from HA establishes a new Wi-Fi baseline without creating synthetic events; switches are stored in `/data/presence_probes.json`. PING and ARP are checked every 60 seconds on each enrolled phone. These are **detection** switches, not the separate Notify · Wi-Fi switch.

**Reliability:** An ICMP reply proves that *something* answers at the enrolled IP, not the MAC or phone identity. Keep DHCP reservations for all registered phones, especially PING-only. If ARP detects a MAC mismatch, even a positive PING does not prove the registered phone is present. Failed commands and ambiguous responses are UNKNOWN, not confirmed absence. Phones may ignore both ICMP and ARP while sleeping. A completed no-reply debounce only means LAN reachability was lost; it is **not proof of Wi-Fi disassociation**. Wi-Fi-only/Hybrid absence should not be used for security until field-tested.

The maintained Lovelace card and dashboard expose the same two global detection switches. The notification package examples were reworded for either method; existing local HA packages must be updated separately if their human-readable messages still mention ARP specifically. The event types and automations did not change.

## Notification switches (0.1.18)

The DH Presence MQTT device publishes three persisted MQTT switches: `switch.dh_presence_app_notify_presence` (default ON: `arrival`/`departure`), `switch.dh_presence_app_notify_gps` (default OFF: `gps_in`/`gps_out`) and `switch.dh_presence_app_notify_wifi` (default OFF: `wifi_in`/`wifi_out`/`wifi_lost`). Homeowners control them from HA Device or Lovelace, independently of GPS/Wi-Fi/Hybrid choice. They suppress only human `script.write2log` notifications in the [local HA package](examples/packages/dh_presence_app_notification_merge_named_ru.yaml), never MQTT Event publishing or Recorder. Settings survive restarts; do not add HA `input_boolean` helpers. For existing merge-named installations, replace the local notification package with the updated keyed example after the app upgrade.

## Pilot capabilities

- Registers each resident with **one** explicit GPS `device_tracker` from that resident's phone. Names come from HA; multiple Companion devices signed in as the same user are not automatically included.
- The startup mode is configured in the App's Configuration tab and can be switched live in HA via `select.dh_presence_app_mode` (on the same MQTT device). HA selection survives restart, while a changed config default takes priority.
- Logs a confirmed MQTT Discovery publish on `homeassistant/device/dh_presence_app/config`, retries failures, and re-announces on HA birth and periodically. MQTT broker delivery does not prove HA accepted a payload. Version 0.1.6 additionally checks HA Core API for the MQTT integration and expected Presence entities, and logs the result. If none appear, check HA MQTT integration logs for schema errors.
- Publishes one MQTT Device named **DH Presence**, aggregate `binary_sensor.dh_presence_app_residents_home`, individual GPS and Wi-Fi binary sensors and numeric straight-line distance, version/started diagnostics and one MQTT Event.
- Persists last confirmed logical resident states under `/data`; expired/missing sources never become `not_home`. A never-confirmed aggregate remains unavailable.
- Excluded users never create entities.
- MQTT events are non-retained; HA notification packages own human-facing messages.

**Staged single-install pilot in 0.1.11:** Native **Supervisor Ingress**
registration UI is included in the same Home Assistant App. No Core adapter,
custom integration, frontend resource or `configuration.yaml` edit. The
user opens the App's **Open Web UI** button, selects the phone GPS tracker
while using the phone on direct home Wi-Fi, and enrolls. Supervisor supplies
the authenticated user ID and display name; the App validates a directly
connected client IP with a fresh ARP reply and stores the MAC locally.
**Not implemented:** verified continuous Wi-Fi presence/absence, autonomous
Companion device-to-WebSocket attestation and alarm integration. The GPS presence engine remains unchanged by the diagnostic update.


## Administrator-only network diagnostics (0.1.12)

The native DH Presence interface includes a private **Диагностика регистрации** card. In 0.1.13 the view is compact on phones, status labels are in Russian, the last GPS report uses the HA-configured timezone (explicit UTC fallback), and saved IP/MAC fields have one-tap Copy buttons. Only an authenticated Home Assistant administrator can see all resident registrations, including the name, device, tracker, IP and MAC recorded at registration, current GPS state and last GPS report time. This does not assert current Wi-Fi reachability.

The App authorizes each private request server-side by using its existing Supervisor token to query Home Assistant Core's administrator list and match the Ingress user ID. Ordinary residents get HTTP 403; authorization failures get 503 without any IP/MAC payload. The ordinary `/api/status` response no longer includes addresses. MQTT/Recorder still do not publish them.

An optional [Lovelace administrator debug launcher](examples/lovelace/presence_admin_debug_card_ru.yaml) uses `hass.user.is_admin` to hide itself for non-admins. The full dashboard and canonical Presence card also include this launcher. No separate integration or additional credential is required.

## Presence Lovelace card

The maintained [Russian Presence card](examples/lovelace/presence_app_card_ru.yaml) is a `vertical-stack` that displays the aggregate “Мы дома” state, the actual `select.dh_presence_app_mode` control, and **all** configured residents with their per-phone GPS availability and distance. Residents are resolved dynamically from the shared MQTT binary sensor's `residents` attribute: adding another `device_tracker` to the App configuration does not require editing the card.

A full `sections` page embedding this same card is available as [dashboard YAML](examples/lovelace/dh_presence_app_dashboard.yaml). Both examples require `custom:button-card >= 5.0`, Mushroom and **[Auto Entities](https://github.com/thomasloven/lovelace-auto-entities)** (install through HACS before opening the dashboard). The universal `auto-entities` section matches every entity containing `dh_presence_app_` (including button/select/event entities) plus the optional native Supervisor update entity. New residents appear without editing YAML. Actions remain at the top in the standard chips and are also accessible as native rows in the entity list; the Refresh stamp chip distinguishes no manual refresh from a completed one. Paste the *card* file under a dashboard **Manual YAML card**; paste the *dashboard* file when editing the complete dashboard view in YAML.

The mode selector is functional. The status and resident rows are observational. The App exposes genuine operation entities (`sensor.dh_presence_app_card`, `button.dh_presence_app_refresh`, `button.dh_presence_app_check_updates`, refresh-state and version diagnostics) following the [DigitalHouses Unified Status Card](../docs/standards/UNIFIED_PRODUCT_STATUS_CARD_STANDARD.md). Refresh reads currently stored HA tracker states immediately and succeeds when all configured GPS sources have valid last-known evidence and the MQTT state was published. This does not request a new GPS fix from iOS. Version checks query stable product-tagged GitHub Releases. Installation/restart remain Supervisor-owned. GPS last-known `home`/`not_home` and distance remain available even after days without iOS movement; this is **last-known evidence, not live GPS**. Each GPS sensor exposes actual `gps_reported_at`, and the card shows the report time and labels aged results as last-known. An unknown/unavailable/malformed source is still unavailable, and the last confirmed logical state is retained without inventing an arrival/departure. `last_reported` is preferred to `last_updated`; polling HA never fabricates a new report. Distance requires last-known valid coordinates. Each registered phone also gets a Wi-Fi binary sensor; until the independently verified Wi-Fi engine is installed it remains unavailable, rather than pretending the phone is absent. Hybrid limitations remain unchanged.

## Registration launcher card (optional)

The maintained Russian dashboard includes a **Регистрация телефона**
`custom:button-card` launcher. A standalone card is available as
[`presence_registration_card_ru.yaml`](examples/lovelace/presence_registration_card_ru.yaml).
No separate HA frontend resource or adapter is needed.

- On released `0.1.10`, the launcher states registration is unavailable and
  **does not navigate**. It does not claim a mobile registration endpoint exists.
- Once `0.1.11+` has passed network/Ingress acceptance and is installed,
  the launcher opens the native Supervisor Ingress path
  `/app/8133339d_digitalhouses_presence_app`.
- Registration is still performed inside the App's own Ingress page on the
  phone's local Home Assistant connection, not via Lovelace Javascript.

## One-click native phone registration (0.1.11 pilot)

1. Install/update **DigitalHouses Presence App** through the normal HA App
   Store. No extra packages, integration, HACS card or files are needed.
2. On the **phone being enrolled**, connect to home Wi-Fi and open Home
   Assistant through its direct local URL, then open **DH Presence**
   in the HA sidebar (native Ingress). An administrator can also use
   **Settings → Apps → DH Presence → Open Web UI**.
3. Select the phone's existing GPS tracker and press **Зарегистрировать**.
   The HA user name comes from authenticated Supervisor Ingress headers;
   IP comes from the verified HA Core transport hop, and MAC from a fresh
   on-link active ARP response, **not** from manually typed fields.
4. The App stores the binding under `/data/presence_registrations.json`,
   enrolls the resident automatically, and the MQTT roster shows
   `Имя жильца (Устройство)`. Registered residents remain across restarts.
5. A second phone or iPad under the same HA account must be chosen explicitly
   and is never auto-enrolled. Admin exclusions require verified HA user ID.

The included Ingress UI is sufficient for registration and listing enrolled
phones. The optional Lovelace card uses Mushroom, button-card and Auto
Entities for advanced monitoring; it is **not a prerequisite** to using the
App. No manually filled `resident_names` is required for newly enrolled
phones; that configuration remains only for existing pilot migrations.

**Security boundary:** Home Assistant Ingress asserts user identity, but
does not by itself cryptographically prove which of a user's devices sent
the request. An unexpected proxy/VPN/Cloudflare route, no LAN ARP reply or
a missing selected GPS tracker fails registration. `host_network` and
`NET_RAW` for one-off ARP are now **explicitly approved for the 0.1.11 experimental pilot**, guarded by an exact-capability repo validator and negative tests. Live on-site HAOS Ingress/ARP acceptance still needs to be performed after installation. No alarm control or negative Wi-Fi evidence is
enabled by registration.

## Legacy resident name mapping (migration only; do not configure anew)



Add an optional `resident_names` mapping under **Settings → Apps → Presence App → Configuration**; the original `residents` list remains unchanged. Example:

```yaml
residents:
  - device_tracker.13promax_sky
resident_names:
  - device_tracker: device_tracker.13promax_sky
    user_name: "Имя жильца"
```

Each entry explicitly associates **one registered tracker** with a person's name. Supervisor retains this App configuration across restarts and upgrades; there is no second naming table in HA Packages and no runtime `person` lookup. The device label still comes from the tracker's HA friendly name. Unmapped residents show their device names alone. Invalid/duplicate/unregistered associations fail validation. Stable resident keys, MQTT entities and confirmed presence remain unchanged.

## Recorder and notifications package

[The local Russian HA package](examples/packages/dh_presence_app_notification_local_package_ru.yaml) processes the existing `event.dh_presence_app_event` directly. For `arrival`, `departure`, verified `wifi_in`, and `wifi_lost` (missing Wi-Fi confirmation), plus future genuinely verified `wifi_out`, it calls the site's existing `script.write2log` **once** with `title` and `message`. No duplicate `logbook.log`, `persistent_notification.create` or extra MQTT device is introduced. The MQTT Event entity can be stored by Home Assistant Recorder, subject to the local Recorder filters and retention. Whether `write2log` also logs anything is specific to that local script.

First confirmed arrival (whole-house `not_home → home`) produces `Режим дома: присутствие`; final confirmed departure (`home → not_home`) produces `Режим дома: отсутствие`. These are messages, not physical alarm/security mode changes.

The App owns a one-time `device_tracker` → `user_name` map through the optional `resident_names` list in Supervisor App Configuration. Existing `residents` entries remain unchanged. The App publishes `user_name` (or JSON null) and the real GPS tracker friendly name `device_name` on machine events. The local package displays `user_name (device_name)`, or the device name alone when unmapped; it does not search `person` or maintain a duplicate name dictionary.

Install the package in `/config/packages/dh_presence_app_notification_local_package_ru.yaml` with `homeassistant: packages: !include_dir_named packages` and check that `script.write2log` accepts `title` and `message`. The App emits `wifi_in` only after an initial baseline has been observed; it emits `wifi_lost` once after the configured 15-minute loss of positive Wi-Fi proof. An iPhone failing ARP does **not** mean a verified disconnect; `wifi_out` remains reserved for future stronger proof.

## Install through Home Assistant

1. Add `https://github.com/DigitalHouses/home-assistant-apps` under **Settings → Apps → App Store → Repositories** if not already configured.
2. Refresh App Store metadata and open **DigitalHouses Presence App** (Experimental).
3. Install, then open **Configuration** and add the phone's exact GPS `device_tracker` entity to the `residents` list (one string per phone). Do not add iPads left at home.
4. Leave `presence_mode: gps` for functional tracking. After startup, a `select.dh_presence_app_mode` entity is available in the MQTT device and in the example dashboard. Do not register excluded administrators' trackers. Legacy HA User ID exclusions cannot be derived reliably from a tracker alone; a tracker-only roster with `exclude_users` configured fails visibly instead of silently tracking an excluded user.
5. Save and start the App. Check **Logs** and the `DigitalHouses Presence App` MQTT Device in HA.
6. For update, use the ordinary Home Assistant Apps interface after a new version is published. Do not install ZIP files or run ad-hoc copy commands.

A fresh installation with no registered residents remains unknown and must never display an empty home.

This version is built locally by Supervisor (no `image:` field and no GHCR release). Immutable registry delivery and mandatory consent/telemetry are future production acceptance gates.

Read [DOCS.md](DOCS.md) and [docs/TEST_PLAN.md](docs/TEST_PLAN.md) before using presence outside the laboratory.
