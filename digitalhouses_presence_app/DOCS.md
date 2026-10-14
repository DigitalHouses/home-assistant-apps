# DigitalHouses Presence App 0.1.1 — experimental pilot

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

**Mode from both places:** `presence_mode` in App Configuration sets the initial/default mode. Home Assistant shows `select.dh_presence_app_mode` on the DigitalHouses Presence App MQTT device (also present in the example Lovelace dashboard). A selection in HA applies live and persists in `/data/presence_mode.json`; on restart it is retained unless the App Configuration default was actually changed. Selecting the same mode does not restart anything. Invalid MQTT commands are ignored.

**Wi-Fi pilot limitation:** `gps` works; `hybrid` uses GPS only pending verified Wi-Fi input; selecting `wifi` makes aggregate presence unavailable rather than advertising an old GPS result as a Wi-Fi observation.

**Excluded administrators:** Only explicitly configured trackers are tracked. The old `exclude_users` HA User ID list is still supported for legacy records that include a known User ID. In the new single-tracker format the app cannot prove the account owner from a `device_tracker` alone; therefore combining tracker-only registration with non-empty `exclude_users` fails loudly. Omit excluded users' trackers from the roster. There is no implicit admin exclusion.

**Migration from 0.1.0:** the previous user-ID-keyed saved state cannot be securely linked to a new tracker. Its old file is read, but new tracker records initialize as unknown and establish a baseline from fresh GPS data without generating fake arrival/departure events. Only stored v2 tracker identities are subsequently restored. Back up the App before upgrading if historical configuration is important.

## Source confidence and event semantics

Home Assistant Core is queried through `http://supervisor/core/api`, authorized by `SUPERVISOR_TOKEN`. The GPS entity must have a fresh timezone-aware `last_updated`. Stale, unknown or unavailable data cannot initiate a departure. The last *confirmed* state survives restart in `/data/presence_state.json`; corrupted existing persistence prevents start.

A source/aggregate transition is a machine event only after first real observation of the running process. MQTT retained state is synchronized before transient QoS1 events. Transient events are never replayed after reboot or reconnect. The initial state of an unconfigured home is **unavailable**, not off. Distance is computed from Home latitude/longitude and fresh GPS coordinates, with no additional attributes.

## Installation

Use Home Assistant **Settings → Apps → App Store** and the already configured DigitalHouses repository URL. Install the experimental App through the native menu. This initial version builds from the Dockerfile supplied in the repository; it does not require manually installing a zip or copying scripts. MQTT broker integration must be available to Supervisor (`mqtt:need`).

## Known limitations

Automatic registration from phone is not available until a minimum authorized HA Core custom integration is implemented and validated. The 14 October WebSocket proof of concept must not be misrepresented as an installed feature. Wi-Fi probing, 15+ minute iPhone sleep qualification and robust negative Wi-Fi verification remain unproven; no scanner or negative ARP result affects presence.

Telemetry is not emitted in this experimental preproduction pilot; the config flag is reserved for the eventual policy-compliant supported release. Do not deploy to Amir, and do not use the pilot to arm/disarm an alarm.

## Next acceptance milestones

See [testing plan](docs/TEST_PLAN.md), [requirements](docs/REQUIREMENTS.md), and [MQTT contract](docs/MQTT_CONTRACT.md).
