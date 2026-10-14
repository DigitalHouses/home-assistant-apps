# DigitalHouses Presence App 0.1.8 — experimental pilot

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

**Wi-Fi pilot limitation:** `gps` works; `hybrid` uses GPS only pending verified Wi-Fi input; selecting `wifi` makes aggregate presence unavailable rather than advertising an old GPS result as a Wi-Fi observation.

**Excluded administrators:** Only explicitly configured trackers are tracked. The old `exclude_users` HA User ID list is still supported for legacy records that include a known User ID. In the new single-tracker format the app cannot prove the account owner from a `device_tracker` alone; therefore combining tracker-only registration with non-empty `exclude_users` fails loudly. Omit excluded users' trackers from the roster. There is no implicit admin exclusion.

**Migration from 0.1.0:** the previous user-ID-keyed saved state cannot be securely linked to a new tracker. Its old file is read, but new tracker records initialize as unknown and establish a baseline from fresh GPS data without generating fake arrival/departure events. Only stored v2 tracker identities are subsequently restored. Back up the App before upgrading if historical configuration is important.

## Source confidence and event semantics

Home Assistant Core is queried through `http://supervisor/core/api`, authorized by `SUPERVISOR_TOKEN`. The GPS entity must have a fresh timezone-aware `last_updated`. Stale, unknown or unavailable data cannot initiate a departure. The last *confirmed* state survives restart in `/data/presence_state.json`; corrupted existing persistence prevents start.

A source/aggregate transition is a machine event only after first real observation of the running process. MQTT retained state is synchronized before transient QoS1 events. Transient events are never replayed after reboot or reconnect. The initial state of an unconfigured home is **unavailable**, not off. Distance is computed from Home latitude/longitude and fresh GPS coordinates, with no additional attributes.

## Installation

Use Home Assistant **Settings → Apps → App Store** and the already configured DigitalHouses repository URL. Install the experimental App through the native menu. This initial version builds from the Dockerfile supplied in the repository; it does not require manually installing a zip or copying scripts. MQTT broker integration must be available to Supervisor (`mqtt:need`).

## MQTT device not found in Home Assistant

1. Inspect App log for `MQTT Discovery published topic=homeassistant/device/dh_presence_app/config components=...`. This proves broker QoS1 acknowledgment only, not acceptance by HA.
2. Inspect `MQTT presence state published` to prove live-state path.
3. Wait one GPS polling interval and inspect the App log for `HA MQTT Discovery acceptance check`: it checks HA Core for the MQTT integration and expected Presence entity IDs. If none appear, note that entities may have been renamed.
4. In Home Assistant **Settings → Devices & services → MQTT**, verify MQTT integration (not just Mosquitto App) is connected and discovery is enabled with prefix `homeassistant`.
5. If broker publication succeeded but no device exists, inspect Home Assistant Core logs for `mqtt`, `dh_presence_app`, `discovery`, or `Invalid config`. Do not delete other devices, clear all retained topics, or recreate the MQTT integration.
6. The App automatically republishes on HA birth and every five minutes. No host-side script needed.

## One-time names in the App

Set resident human names in the App's **Configuration** tab; existing `residents` tracker strings remain unchanged:

```yaml
residents:
  - device_tracker.13promax_sky
resident_names:
  - device_tracker: device_tracker.13promax_sky
    user_name: "Имя жильца"
```

Supervisor persists `resident_names` alongside the App's other settings. Only enrolled GPS trackers are allowed; unregistered or duplicate tracker keys and empty user names are rejected at startup. Leaving `resident_names: []` is safe for existing users. The App continues reading the actual device label from its HA `device_tracker` friendly name; it publishes `user_name` (or null) and `device_name` in machine events. MQTT aggregate resident attributes also include `user_name`. No second HA Person resolver or local package map is used.

## One-time user/device name mapping

Preserve the original `residents` tracker list. Add optional names once in the App's Configuration UI:

```yaml
residents:
  - device_tracker.13promax_sky
resident_names:
  - device_tracker: device_tracker.13promax_sky
    user_name: "Имя жильца"
```

Supervisor stores the App options persistently. Only registered trackers can be mapped; duplicates, blanks, extra keys and unknown trackers are rejected. If a mapping is omitted, the App works as before and reports `user_name: null`, using the actual tracker friendly name as `device_name`. Mapping does not change the stable resident key, device identification or previously confirmed presence.

## Local Recorder and notifications

- Install [the Russian HA package](examples/packages/dh_presence_app_notification_local_package_ru.yaml) at `/config/packages/dh_presence_app_notification_local_package_ru.yaml`; use `homeassistant: packages: !include_dir_named packages`. The file's top-level key is `automation:`.
- `arrival`, `departure`, `wifi_in`, `wifi_out` each uses `event.received → trigger.id → choose → script.write2log`, exactly one direct call with `title` and `message`. No duplicate `logbook.log`, `persistent_notification.create` or intermediate notification event.
- The MQTT Event entity may be retained in Recorder history according to existing Recorder filters and retention. Any logging performed inside `script.write2log` itself remains a local responsibility; this package does not write SQL.
- `first_arrival` / `last_departure` are machine event facts, not inferred from the later aggregate state. `Режим дома: присутствие/отсутствие` is notification text only, not a security-mode change.
- Person and device names are supplied by the App itself from one-time Supervisor name mapping plus the tracker's HA friendly name; the package has no name registry and never queries HA `person`.
- Wi-Fi branches remain inactive while the independently verified Wi-Fi engine is not available. GPS source events are not independently notified to avoid duplicates.

## Lovelace dashboard and status card

- [Standalone Russian card](examples/lovelace/presence_app_card_ru.yaml) — paste into Home Assistant as **Manual card (YAML)**.
- [Full sections view](examples/lovelace/dh_presence_app_dashboard.yaml) — paste into a complete Lovelace view YAML editor.
- Requires Mushroom and `custom:button-card >= 5.0`, already used by other DigitalHouses dashboards.
- The resident rows are generated from `binary_sensor.dh_presence_app_residents_home` → `residents` attribute. Distance and GPS freshness use actual per-resident MQTT entity IDs; no local MAC, user ID, IP, or customer-specific tracker is hardcoded.
- Switch mode via actual HA `select.dh_presence_app_mode`. Wi-Fi-only is explicitly labelled unsupported during pilot. A stale GPS source is flagged; previous confirmed presence is presented as historical rather than live.
- Events and runtime start time are available through two read-only Mushroom chips. No invented App-owned update/restart services or operations are used.
- HAOS Supervisor owns install and restart. The standardized foreground `sensor.dh_presence_app_card` runtime operation contract is future work and must not be simulated by frontend YAML.

## Known limitations

Automatic registration from phone is not available until a minimum authorized HA Core custom integration is implemented and validated. The 14 October WebSocket proof of concept must not be misrepresented as an installed feature. Wi-Fi probing, 15+ minute iPhone sleep qualification and robust negative Wi-Fi verification remain unproven; no scanner or negative ARP result affects presence.

Telemetry is not emitted in this experimental preproduction pilot **even when** `telemetry_enabled: true`; the config flag is reserved for the eventual policy-compliant supported release. Startup now logs this explicitly. MQTT availability does not demonstrate Home Assistant Core API access. Startup logs the result of the first Core configuration/trackers read; a 403/404 there must be handled as a real Core API or tracker problem, separately from the already removed Bashio timezone lookup. Do not deploy to Amir, and do not use the pilot to arm/disarm an alarm.

## Next acceptance milestones

See [testing plan](docs/TEST_PLAN.md), [requirements](docs/REQUIREMENTS.md), and [MQTT contract](docs/MQTT_CONTRACT.md).
