# DigitalHouses Sync — implementation and operations

This is the development-stage Home Assistant OS App. It is **not yet installable** as a released product. No production image or release tag exists.

## Runtime scope

- Supervisor App / container; not a custom integration.
- MQTT credentials come from the Supervisor MQTT service. No broker IP is embedded.
- App data is under `/data`, Home Assistant is mounted at `/homeassistant` **read-only** in 0.0.1.
- Availability watcher records previously online installations; offline never proves uninstall.
- The preview publishes diagnostic version and process started-at sensors for the App itself.
- Optional manual Plex preflight fetches immutable YAML from GitHub and compares it with Storage/Recorder without touching HA files.
- A separately confirmed command can create an audit receipt under /data for an identical installed Recorder; see [Plex adoption](docs/ADOPTION.md).
- No Home Assistant YAML is changed.

## Design for v1

The write-enabled implementation must switch the config mapping explicitly, remain confined to App-owned paths (`/homeassistant/dashboards/dh`, `/homeassistant/packages/dh`), validate the entire candidate set, and preserve a recoverable previous generation. Existing locally edited files are conflicts, not files to overwrite.

Do not assume package changes are immediately applied; the operator receives an explicit restart-required state. Existing panel and package configurations must be adopted cautiously (no duplicate dashboard registration).

## Sources and standards

- `docs/standards/DIGITALHOUSES_APP_STANDARD.md`
- `docs/standards/PRODUCT_NAMING_STANDARD.md`
- `docs/standards/HA_PACKAGE_VERSIONING_STANDARD.md`
- `docs/standards/REPOSITORY_GOVERNANCE.md`
- `docs/standards/IMMUTABLE_DELIVERY_AND_TELEMETRY_STANDARD.md`
- `docs/standards/PRODUCT_TELEMETRY_POLICY.md`

Next: product teams publish canonical YAML bundles and MQTT contracts; then implement active sync and two-instance pilot.

