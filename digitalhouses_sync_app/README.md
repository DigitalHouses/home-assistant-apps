# DigitalHouses Sync App — v0.1.0

**First experimental release candidate, release PR #499, ready for review. GHCR image not yet published.**

Version **0.1.0** is a **strictly read-only MQTT product catalog**. This is the first safe operational pilot before the separate YAML update/rollback feature is enabled.

## User-visible functionality

- Admin-only HAOS Supervisor Ingress dashboard, port 8099, showing discovered DigitalHouses products.
- Product ID, running version, instance ID, availability and owning GitHub repository/product path.
- Only structurally valid `https://github.com/DigitalHouses/<repo>` references are accepted.
- Reads current MQTT retained `/sync` messages and remembers accepted metadata under `/data/product_sources.json`.
- Existing product availability remains separate; offline never deletes the product or its saved source metadata.
- Publishes DH Sync's own MQTT Discovery Version, Started-at and `/sync`.

## Security and scope

The installed App runtime has **no Home Assistant configuration mount or Home Assistant API permission**. The Ingress endpoint serves only GET; all POST requests return HTTP 405. YAML cannot be installed, updated or rolled back by the v0.1.0 App. There is no GitHub download or YAML file mutation in the installed runtime.

An earlier opt-in YAML transaction engine is kept **in the GitHub source for future work**, not called or exposed by the running v0.1.0 App. PVE/UPS and Plex YAML compatibility is still being reviewed for installed Agent 0.5.89 and 0.8.18.

No telemetry integration is enabled (`telemetry_allowed: false` remains unchanged), and no external app repository/CORE service is required.

## Acceptance

After an immutable GitHub release/GHCR build, install in CORE HAOS and check the three retained MQTT entries for PVE, Plex and DH Sync. Check that no YAML, `.storage`, packages or agent executable files were changed. Additional homes are out of scope for this first trial.

See [First version](docs/FIRST_VERSION.md), [MQTT Discovery Contract](docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md), [Product requirements](docs/PRODUCT_REQUIREMENTS.md).
