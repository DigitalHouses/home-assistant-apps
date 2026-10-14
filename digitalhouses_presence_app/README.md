# DigitalHouses Presence App

**Status: experimental installable GPS pilot, version 0.1.6.** Not approved for alarm automation.

This application belongs to `DigitalHouses/home-assistant-apps/digitalhouses_presence_app` and is installed from the Home Assistant **Settings → Apps → App Store** interface after refreshing the configured DigitalHouses repository. No separate GitHub repository, shell installer or manual copy to Home Assistant is needed.

## Pilot capabilities

- Registers each resident with **one** explicit GPS `device_tracker` from that resident's phone. Names come from HA; multiple Companion devices signed in as the same user are not automatically included.
- The startup mode is configured in the App's Configuration tab and can be switched live in HA via `select.dh_presence_app_mode` (on the same MQTT device). HA selection survives restart, while a changed config default takes priority.
- Logs a confirmed MQTT Discovery publish on `homeassistant/device/dh_presence_app/config`, retries failures, and re-announces on HA birth and periodically. MQTT broker delivery does not prove HA accepted a payload. Version 0.1.6 additionally checks HA Core API for the MQTT integration and expected Presence entities, and logs the result. If none appear, check HA MQTT integration logs for schema errors.
- Publishes a single DigitalHouses Presence MQTT Device, aggregate `binary_sensor.dh_presence_app_residents_home`, individual resident GPS binary sensors and numeric straight-line distance, version/started diagnostics and one MQTT Event.
- Persists last confirmed logical resident states under `/data`; expired/missing sources never become `not_home`. A never-confirmed aggregate remains unavailable.
- Excluded users never create entities.
- MQTT events are non-retained; HA notification packages own human-facing messages.

**Not available yet:** in-app registration UI / WebSocket Core adapter; ARP Wi-Fi probing; trustworthy network absence; Wi-Fi/Hybrid correction and standard App operation card. Selecting `wifi` without an active Wi-Fi engine does not mean anyone is away. Selecting `hybrid` currently uses GPS-only evidence.

## Presence Lovelace card

The maintained [Russian Presence card](examples/lovelace/presence_app_card_ru.yaml) is a `vertical-stack` that displays the aggregate “Мы дома” state, the actual `select.dh_presence_app_mode` control, and **all** configured residents with their per-phone GPS availability and distance. Residents are resolved dynamically from the shared MQTT binary sensor's `residents` attribute: adding another `device_tracker` to the App configuration does not require editing the card.

A full `sections` page embedding this same card is available as [dashboard YAML](examples/lovelace/dh_presence_app_dashboard.yaml). Both examples require `custom:button-card >= 5.0` and Mushroom. Paste the *card* file under a dashboard **Manual YAML card**; paste the *dashboard* file when editing the complete dashboard view in YAML.

The mode selector is functional. The status and resident rows are observational. The App does not yet implement `sensor.dh_presence_app_card` or product-level refresh/release-check buttons, so this card deliberately does **not** expose pretend operation controls or claim to implement the full [DigitalHouses Unified Status Card](../docs/standards/UNIFIED_PRODUCT_STATUS_CARD_STANDARD.md). App installation/restart remains Supervisor-owned. GPS-unavailable shows the last confirmed state with a warning, not an assertion of live presence. Wi-Fi and Hybrid limitations remain unchanged.

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
