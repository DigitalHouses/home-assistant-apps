# DigitalHouses Presence App 0.1.15 — experimental pilot

## Private administrator debug (0.1.12+, compact UI in 0.1.13)

The native Ingress UI has an administrator-only registration diagnostics card.
For each phone it shows the resident's name, device, GPS tracker, IP and MAC
**recorded when the device was registered**, GPS state and report timestamp.
This is a saved network binding, not a claim of current connectivity.

In 0.1.13, the native UI displays compact responsive rows, Russian status chips and Copy actions for enrollment IP and MAC. The last GPS report is formatted in Home Assistant's configured time zone from the authenticated Core config endpoint; if unavailable, UTC is labelled explicitly. The admin API permissions and regular resident privacy remain unchanged.

The backend authenticates the Ingress user ID and checks their active
`system-admin` group against Home Assistant Core through Supervisor's
authorized `config/auth/list` WebSocket. Unauthorized callers receive 403;
unavailable verification yields 503. The private endpoint never publishes to
MQTT or Recorder; the normal resident status API omits IP/MAC.

The additional Lovelace admin diagnostics launcher reads
`hass.user.is_admin` for visibility and opens the same Ingress panel.
No manual administrator IDs or configuration changes are needed.

## Wi-Fi MAC verification (0.1.14; positive evidence only)

Registration persists `device_tracker`, IP and MAC. Every 60 seconds the
App performs fresh local ARP and confirms **HOME** only when the reply MAC
equals the enrolled MAC. Existing per-resident Wi-Fi MQTT binary sensors
publish that home evidence without extra integrations or HA device entities.
The probe's last verified timestamp and status are diagnostic attributes.
The administrator Ingress page shows these observations alongside the private
enrollment IP/MAC, while normal resident API and MQTT do not expose IP/MAC.

iOS sleep, a blocked ARP reply, IP reassignment and subnet failure are
unverified results. Keep the last positive Wi-Fi HOME up to
`wifi_absence_minutes` (default 15); then mark the Wi-Fi source
**unavailable**. Never generate NOT_HOME, `wifi_out`, `departure` or
a 'last person left' notification from ARP silence. The selected `wifi`
mode may confirm HOME but cannot yet confirm away. In `hybrid` mode,
fresh Wi-Fi HOME corrects even an old valid GPS away report; otherwise
the previous trusted GPS observation applies. GPS mode remains default.

**This is a staged feature, not accepted full Wi-Fi presence/absence.**
The next step must establish independent, affirmative Wi-Fi disconnection
evidence without relying on Nmap, the router or NetAlertX. No alarm
logic may use the Wi-Fi-only unknown state as away.

## Configuration
The App Store's native **Configuration** tab is the supported installation and settings UI. This build deliberately does not register any custom Home Assistant frontend panel.

Select **one GPS phone tracker per resident** using the Home Assistant App configuration:

```yaml
presence_mode: gps
residents:
  - device_tracker.serzhan_iphone
  - device_tracker.asylmura_iphone
```

There is no manual HA user ID, display name or Mobile Companion device ID input per resident. Tracker `friendly_name` is used as the MQTT display name after HA supplies it; otherwise the entity ID yields a provisional label. The resident identity is derived from the selected tracker, so an iPad logged in under the same HA account is *not* automatically tracked.

**Mode from both places:** `presence_mode` in App Configuration sets the initial/default mode. Home Assistant shows `select.dh_presence_app_mode` on the DigitalHouses Presence App MQTT device (also present in the example Lovelace dashboard). A selection in HA applies immediately (without waiting for GPS polling) and persists in `/data/presence_mode.json`; on restart it is retained unless the App Configuration default was actually changed. Selecting the same mode does not restart anything. Invalid MQTT commands are ignored.

**Wi-Fi pilot limitation:** each registered phone gets a separate Wi-Fi binary sensor in the same DH Presence MQTT Device; it is unavailable pending a real Wi-Fi engine.  `gps` works; `hybrid` uses GPS only pending verified Wi-Fi input; selecting `wifi` makes aggregate presence unavailable rather than advertising an old GPS result as a Wi-Fi observation.

**Excluded administrators:** Only explicitly configured trackers are tracked. The old `exclude_users` HA User ID list is still supported for legacy records that include a known User ID. In the new single-tracker format the app cannot prove the account owner from a `device_tracker` alone; therefore combining tracker-only registration with non-empty `exclude_users` fails loudly. Omit excluded users' trackers from the roster. There is no implicit admin exclusion.

**Migration from 0.1.0:** the previous user-ID-keyed saved state cannot be securely linked to a new tracker. Its old file is read, but new tracker records initialize as unknown and establish a baseline from fresh GPS data without generating fake arrival/departure events. Only stored v2 tracker identities are subsequently restored. Back up the App before upgrading if historical configuration is important.

## Source confidence and event semantics

Home Assistant Core is queried through `http://supervisor/core/api`, authorized by `SUPERVISOR_TOKEN`. A valid GPS source must have a timezone-aware report timestamp (`last_reported` preferred, otherwise `last_updated`). Age alone does not invalidate its last-known position. Unknown, unavailable, malformed or impossible-future tracker values still do not initiate a departure. The last *confirmed* state survives restart in `/data/presence_state.json`; corrupted existing persistence prevents start.

A source/aggregate transition is a machine event only after first real observation of the running process. MQTT retained state is synchronized before transient QoS1 events. Transient events are never replayed after reboot or reconnect. The initial state of an unconfigured home is **unavailable**, not off. Distance uses last-known GPS coordinates and is not a live movement measurement. The GPS binary sensor reports its original `gps_reported_at` as an attribute.

## Installation

Use Home Assistant **Settings → Apps → App Store** and the already configured DigitalHouses repository URL. Install the experimental App through the native menu. This initial version builds from the Dockerfile supplied in the repository; it does not require manually installing a zip or copying scripts. MQTT broker integration must be available to Supervisor (`mqtt:need`).

## MQTT device not found in Home Assistant

1. Inspect App log for `MQTT Discovery published topic=homeassistant/device/dh_presence_app/config components=...`. This proves broker QoS1 acknowledgment only, not acceptance by HA.
2. Inspect `MQTT presence state published` to prove live-state path.
3. Wait one GPS polling interval and inspect the App log for `HA MQTT Discovery acceptance check`: it checks HA Core for the MQTT integration and expected Presence entity IDs. If none appear, note that entities may have been renamed.
4. In Home Assistant **Settings → Devices & services → MQTT**, verify MQTT integration (not just Mosquitto App) is connected and discovery is enabled with prefix `homeassistant`.
5. If broker publication succeeded but no device exists, inspect Home Assistant Core logs for `mqtt`, `dh_presence_app`, `discovery`, or `Invalid config`. Do not delete other devices, clear all retained topics, or recreate the MQTT integration.
6. The App automatically republishes on HA birth and every five minutes. No host-side script needed.

## Native authenticated Ingress registration (0.1.11 pilot)

No adapter, HA custom integration or dashboard JavaScript resource is needed.
Install DH Presence from the Home Assistant App Store, open its **Open Web UI**
(Ingress), select the phone's GPS tracker and press **Зарегистрировать**
while connected through the phone's direct local HA URL.

Supervisor provides `X-Remote-User-Id` and
`X-Remote-User-Display-Name`. Its authenticated proxy forwards the
actual HA Core transport peer in the last two X-Forwarded-For hops.
The App rejects missing/spoofed proxy identities, nonlocal URLs and remote
clients. It then verifies a fresh active ARP reply on the connected LAN
before recording the MAC. The browser provides only the explicitly selected
GPS tracker, not an IP, MAC or HA username.

The App stores accepted registration in
`/data/presence_registrations.json` mode 0600 and dynamically enrolls
the resident, including name and device in MQTT state. Legacy `residents`
and `resident_names` configuration remain supported solely for migration.

This authentication identifies the HA user, not cryptographically which
physical phone owns a chosen tracker. A second phone/iPad using the same
HA account must be explicitly selected; field acceptance and cross-device
identity proof remain open. Do not use for alarm decisions. ARP here is a
**one-time enrollment probe**, not a Wi-Fi presence or absence signal.

## Legacy one-time names in App Configuration (not for new installs)

Set resident human names in the App's **Configuration** tab; existing `residents` tracker strings remain unchanged:

```yaml
residents:
  - device_tracker.13promax_sky
resident_names:
  - device_tracker: device_tracker.13promax_sky
    user_name: "Имя жильца"
```

Supervisor persists `resident_names` alongside the App's other settings. Only enrolled GPS trackers are allowed; unregistered or duplicate tracker keys and empty user names are rejected at startup. Leaving `resident_names: []` is safe for existing users. The App continues reading the actual device label from its HA `device_tracker` friendly name; it publishes `user_name` (or null) and `device_name` in machine events. MQTT aggregate resident attributes also include `user_name`. No second HA Person resolver or local package map is used.

## Wi-Fi link notification semantics (0.1.15)

- First active ARP sample after App startup is a **baseline**; it does not send an artificial Wi-Fi connection notification.
- After baseline, a registered phone's fresh matching MAC changes Wi-Fi from unavailable to HOME and emits `wifi_in` once. It is machine evidence of MAC response, not proof of AP association.
- After `wifi_absence_minutes` (default 15) without any fresh positive MAC, the Wi-Fi source becomes unavailable and emits `wifi_lost` **once**. The package says "Wi-Fi не подтверждается", **never** "Отключился" or "Жилец ушёл" based only on ARP silence.
- When a MAC reply returns, another `wifi_in` may be emitted. Duplicate probes and App restarts must not spam write2log. `wifi_out` remains dormant pending independently confirmed disconnection.
- Only `script.write2log(title, message)` runs for each event; names come from the existing App registration records, not another mapping.

## Local Recorder and notifications

- Install [the Russian HA package](examples/packages/dh_presence_app_notification_local_package_ru.yaml) at `/config/packages/dh_presence_app_notification_local_package_ru.yaml`; use `homeassistant: packages: !include_dir_named packages`. The file's top-level key is `automation:`.
- `arrival`, `departure`, `wifi_in`, `wifi_lost`, and future verified `wifi_out` each uses `event.received → trigger.id → choose → script.write2log`, exactly one direct call with `title` and `message`. No duplicate `logbook.log`, `persistent_notification.create` or intermediate notification event.
- The MQTT Event entity may be retained in Recorder history according to existing Recorder filters and retention. Any logging performed inside `script.write2log` itself remains a local responsibility; this package does not write SQL.
- `first_arrival` / `last_departure` are machine event facts, not inferred from the later aggregate state. `Режим дома: присутствие/отсутствие` is notification text only, not a security-mode change.
- Person and device names are supplied by the App itself from one-time Supervisor name mapping plus the tracker's HA friendly name; the package has no name registry and never queries HA `person`.
- Wi-Fi branches remain inactive while the independently verified Wi-Fi engine is not available. GPS source events are not independently notified to avoid duplicates.

## Lovelace dashboard and status card

- [Standalone Russian card](examples/lovelace/presence_app_card_ru.yaml) — paste into Home Assistant as **Manual card (YAML)**.
- [Full sections view](examples/lovelace/dh_presence_app_dashboard.yaml) — paste into a complete Lovelace view YAML editor.
- Requires Mushroom, `custom:button-card >= 5.0` and **HACS Auto Entities** (`custom:auto-entities`). Install Auto Entities before pasting the maintained card/dashboard YAML; otherwise the universal entity list cannot render.
- Universal auto-entities list discovers `*dh_presence_app_*` across domains (sensors, binary sensors, event, select and native button entities), plus the optional Supervisor `update.digitalhouses_presence_app_update`. New enrolled phones are picked up automatically; no resident key is hardcoded. The existing unified chip actions remain at the top for direct use.
- `sensor.dh_presence_app_last_refresh` is visible in the list and as a timestamp chip. `unknown` after App restart and before the first **successful manual** `REFRESH` is expected; a periodic GPS poll does not advance it.
- The resident rows are generated from `binary_sensor.dh_presence_app_residents_home` → `residents` attribute. Distance and GPS freshness use actual per-resident MQTT entity IDs; no local MAC, user ID, IP, or customer-specific tracker is hardcoded.
- In the **Жильцы** roster every title displays `user_name (device_name)` from the App's one-time `resident_names` mapping. Until mapped, the card explicitly displays `Имя не задано (device_name)`; it never guesses a resident name from the device. Rows are sorted by mapped names.
- Switch mode via actual HA `select.dh_presence_app_mode`. Wi-Fi-only is explicitly labelled unsupported during pilot. Old GPS reports are explicitly labelled last-known with the original report time; unavailable sources remain marked as such.
- Events and runtime start time are available through read-only Mushroom chips. Runtime now owns Refresh and Check version commands; restart/install are native Supervisor actions.
- HAOS Supervisor owns install and restart. The runtime publishes actual `sensor.dh_presence_app_card` operation state and verified release information. The App never performs its own container update/restart.

## Known limitations

Native Ingress registration and active ARP one-time enrollment are implemented in the 0.1.11 draft without any Core adapter, but require live HAOS field acceptance of forwarded client-IP provenance, host networking and raw socket permissions before claiming operational readiness. The 14 October WebSocket proof of concept must not be misrepresented as an installed feature. Wi-Fi probing, 15+ minute iPhone sleep qualification and robust negative Wi-Fi verification remain unproven; no scanner or negative ARP result affects presence.

Telemetry is not emitted in this experimental preproduction pilot **even when** `telemetry_enabled: true`; the config flag is reserved for the eventual policy-compliant supported release. Startup now logs this explicitly. MQTT availability does not demonstrate Home Assistant Core API access. Startup logs the result of the first Core configuration/trackers read; a 403/404 there must be handled as a real Core API or tracker problem, separately from the already removed Bashio timezone lookup. Do not deploy to Amir, and do not use the pilot to arm/disarm an alarm.

## Next acceptance milestones

See [testing plan](docs/TEST_PLAN.md), [requirements](docs/REQUIREMENTS.md), and [MQTT contract](docs/MQTT_CONTRACT.md).

## Device naming, GPS freshness, and operations (0.1.9 historical policy)

- MQTT Device is named **DH Presence**; its immutable identifier stays `dh_presence_app`, preserving HA entity IDs and histories.
- HA tracker `last_reported` is preferred where provided because identical reports do not advance `last_updated`. No HTTP poll of unchanged source state counts as a new phone report; a stale GPS source remains unavailable.
- GPS binary sensor requires a fresh valid HA tracker report. Distance is unavailable unless there are fresh numeric latitude/longitude values. Wi-Fi sensor is present for every registered tracker but is unavailable until independently verified Wi-Fi observations exist.
- Refresh is a full immediate GPS observation and retained MQTT publish, **not** an App restart. Unfresh or missing registered sources make the foreground result an error; no false successful last-refresh timestamp.
- Check Version filters GitHub Releases for stable `digitalhouses_presence_app-vX.Y.Z` tags. No published release means latest-version diagnostics stay unknown rather than claiming an upgrade. Background check every 24h does not take over the foreground card.
- Native `update.digitalhouses_presence_app_update` gates the New Version chip. Supervisor install and restart use normal HA actions. No elevated Supervisor permissions are granted to the App.

## Last-known GPS policy (0.1.10)

- Home Assistant is the only GPS source. Its latest valid state and coordinates remain usable for a stationary phone even after multiple days without a new report.
- `gps_freshness_seconds` is informational for GPS age labels and still applies to Wi-Fi evidence; it no longer disables GPS home/distance.
- Every registered resident exposes actual `gps_reported_at` in MQTT state and on the GPS binary sensor. The timestamp is never replaced with the time the App polled HA.
- A manual Refresh checks and republishes the last-known HA state. A successful refresh verifies the read and MQTT publication, not that the phone transmitted a new position.
- When the source changes to unknown/unavailable, source-specific availability still reports that fact. Previously confirmed household presence is preserved without synthesizing a new transition.
- Remaining limitation: the last known GPS position can be incorrect after a resident moves without a phone report. This pilot must not yet be used for alarm automation.
