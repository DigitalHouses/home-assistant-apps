# DigitalHouses Sync App — 0.6.3

**Single standard:** [DH Sync Developer Standard](../docs/standards/DH_SYNC_DEVELOPER_STANDARD.md).

DH Sync publishes GitHub-owned Home Assistant panels and packages, using retained MQTT `/sync` as its **only product registry**.

- Admit every product whose canonical repository is under GitHub owner `DigitalHouses`, with no availability, product, or version filters.
- Read ordered panel definitions from `digitalhouses_sync_app/dashboards/*.yaml`. Each file controls its dashboard's title, icon, sidebar visibility, `require_admin`, and referenced Views.
- Read standalone Views from the MQTT-discovered product's `dashboards/ru/*.yaml`. A View can appear in multiple panels, with independent tab icon and title.
- Use the sequence of entries in each panel file as the tab order. MQTT `dashboard` is ignored.
- Apply dashboard content via Home Assistant's official WebSocket APIs (Storage mode), not direct `.storage` edits or local View YAML copies.
- Synchronize packages from `packages/common/*.yaml` and `packages/locales/ru/*.yaml`, with safe atomic writes and backups.
- Automatically request a quick HA YAML reload for ordinary package changes. For Recorder configuration, the admin button **«Проверить и обновить»** checks HA configuration and requests a **single Home Assistant Core restart** if the canonical Recorder package revision is not yet activated; subsequent clicks with the same revision are idempotent. The automatic MQTT/hourly cycle never restarts Core; no HAOS/Supervisor reboot or other Agent/App restart.
- Automatically sync after retained MQTT changes and then hourly. The admin Ingress button **«Проверить и обновить»** forces a fresh GitHub scan and immediately applies changed dashboards/packages. No confirmation.

**Clean start:** v0.6.0 does not migrate old dashboards, former View folders, or MQTT routing. Existing dashboard URLs present in the new YAML are updated; unrelated or legacy panels are not deleted automatically.

**Recorder on HOME:** DH Sync 0.6.2 installed `dh_pbs_agent_recorder_package`
but `homeassistant.reload_all` cannot reload its entity inclusion filter.
After upgrading DH Sync to **0.6.3**, press «Проверить и обновить» once.
It detects already-installed Recorder packages through a persistent,
content-based activation receipt, performs `check_config`, and requests a
Home Assistant **Core-only** restart via the existing Supervisor-token-authenticated
HA API. The source revision is then marked requested; a second click with
unchanged Recorder resources will not trigger another restart.
A configuration-check or Core API failure remains visible and retryable.
The graph will show statistics only after HA Recorder collects new states
and completes statistics aggregation. No history is invented or backfilled.

Tests: `PYTHONPATH=digitalhouses_sync_app/rootfs/app:digitalhouses_sync_app/tests python -m unittest discover -s digitalhouses_sync_app/tests -p 'test_*.py'`

## Telemetry (0.6.2)

DH Sync uses the common [Product Telemetry Policy](../docs/standards/PRODUCT_TELEMETRY_POLICY.md)
and [Telemetry Protocol v1](../docs/standards/TELEMETRY_PROTOCOL_V1.md).

For statistics DigitalHouses receives the product name/identifier, released version and a
random persistent installation identifier. The server determines country from network
metadata. No home address, username, MQTT settings, hardware inventory, monitored data,
credentials, or IP address is included in the heartbeat payload.

**Explicit acceptance is required:** Home Assistant App option `telemetry_enabled: false`
remains false for fresh installations. Setting it true confirms the current telemetry/privacy
terms and permits normal runtime. When false, supported policy-v2 operation does not activate.
The client sends at most one normal heartbeat daily (±30-minute jitter), and telemetry
network failures never stop activated synchronization. Authenticated deletion removes
server history and rotates the local installation identity, but continued use reports again.

**Upgrade warning:** Existing installations previously had no telemetry option, so an
unplanned automatic upgrade stops DH Sync until the operator explicitly sets
`telemetry_enabled: true` and restarts the App. Jurisdiction-specific legal/privacy
review of mandatory public rollout remains a separate responsibility.
