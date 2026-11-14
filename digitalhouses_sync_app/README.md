# DigitalHouses Sync App — v0.1.4

**Released v0.1.3 pilot successfully validated on CORE; v0.1.4 is the approved-source refresh candidate.**

Version **0.1.4** remains a **strictly read-only MQTT product catalog and GitHub YAML compatibility preview**. This is the first safe operational pilot before the separate YAML update/rollback feature is enabled.

## User-visible functionality

- Admin-only HAOS Supervisor Ingress dashboard, port 8099, showing discovered DigitalHouses products.
- Product ID, running version, instance ID, availability and owning GitHub repository/product path.
- Only structurally valid `https://github.com/DigitalHouses/<repo>` references are accepted.
- Reads current MQTT retained `/sync` messages and remembers accepted metadata under `/data/product_sources.json`.
- Existing product availability remains separate; offline never deletes the product or its saved source metadata.
- Publishes DH Sync's own MQTT Discovery Version, Started-at and `/sync`.

## Security and scope

The installed App runtime has **no Home Assistant configuration mount or Home Assistant API permission**. The Ingress endpoint serves only GET; all POST requests return HTTP 405. YAML cannot be installed, updated or rolled back by the v0.1.4 App. GitHub YAML content is downloaded only for explicitly requested preview; never installed or written.

An earlier opt-in YAML transaction engine is kept **in the GitHub source for future work**, not called or exposed by the running v0.1.4 App. PVE/UPS and Plex product compatibility has been accepted for installed Agent 0.5.89 and 0.8.18; live-file diff, backup, Apply/rollback are not yet implemented.

No telemetry integration is enabled (`telemetry_allowed: false` remains unchanged), and no external app repository/CORE service is required.

## Acceptance

CORE HAOS already passed the v0.1.3 retained MQTT and GitHub directory discovery pilot. For v0.1.4, refresh and verify the three approved resource rows against the new immutable SHA pins. Check that no YAML, `.storage`, packages or agent executable files were changed. Additional homes are out of scope for this first trial.

See [First version](docs/FIRST_VERSION.md), [MQTT Discovery Contract](docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md), [Product requirements](docs/PRODUCT_REQUIREMENTS.md).

## GitHub dashboards preview (v0.1.3)

The admin-only Ingress panel now offers an explicit **Проверить GitHub-ресурсы** GET link. It reads the `dashboards/ru/` directory of the recognized products at fixed immutable Git SHAs; MQTT supplies identity and installed version only, never the Git revision or a download URL. The preview displays all discovered views, their independent `DH-View-Version`, compatibility header and current source-approval status. This feature does not compare Home Assistant's local files and does not authorize an update. PVE #502 and Plex #508 have merged, and the approved YAML ranges now include PVE 0.5.89 and Plex 0.8.18. This is source compatibility only; installed HAOS YAML is not compared or modified. The installed App still has no Home Assistant config mount, YAML Apply or rollback path.
