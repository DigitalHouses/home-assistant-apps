# Changelog

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
