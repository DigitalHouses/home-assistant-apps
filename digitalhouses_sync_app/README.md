# DigitalHouses Sync App — 0.6.4

**Single standard:** [DH Sync Developer Standard](../docs/standards/DH_SYNC_DEVELOPER_STANDARD.md).

DH Sync publishes GitHub-owned Home Assistant panels and packages, using retained MQTT `/sync` as its **only product registry**.

- Admit every product whose canonical repository is under GitHub owner `DigitalHouses`, with no availability, product, or version filters.
- Read ordered panel definitions from `digitalhouses_sync_app/dashboards/*.yaml`. Each file controls its dashboard's title, icon, sidebar visibility, `require_admin`, and referenced Views.
- Read standalone Views from the MQTT-discovered product's `dashboards/ru/*.yaml`. A View can appear in multiple panels, with independent tab icon and title.
- Use the sequence of entries in each panel file as the tab order. MQTT `dashboard` is ignored.
- Apply dashboard content via Home Assistant's official WebSocket APIs (Storage mode), not direct `.storage` edits or local View YAML copies.
- Synchronize packages from `packages/common/*.yaml` and `packages/locales/ru/*.yaml`, with safe atomic writes and backups.
- Automatically request a quick HA configuration reload when packages change. Never restart HA or change other Apps/Agents.
- Automatically sync after retained MQTT changes and then hourly. The admin Ingress button **«Проверить и обновить»** forces a fresh GitHub scan and immediately applies changed dashboards/packages. No confirmation or navigation; the result and errors appear in the same compact Ingress. Counts cover packages, individual Views and dashboard metadata/order; products and technical details are collapsed by default.

**Clean start:** v0.6.0 does not migrate old dashboards, former View folders, or MQTT routing. Existing dashboard URLs present in the new YAML are updated; unrelated or legacy panels are not deleted automatically.

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

### Operational journal

The admin Ingress LOG uses shared DH Journal 1.1.0 (local SQLite at /data/dh_sync.db, latest 3000 records). Search, severity filter, RU/EN, full text export and confirmed clear. Legacy history is migrated on startup; unsafe legacy details are omitted. Debug is enabled by the App log_level setting. Toast notifications use the shared library; one meaningful sync result, no unchanged scheduled checks. Browser-local settings (enabled and 60 minutes by default) are in Technical information; language follows LOG. The journal is diagnostic only, never a registry or sync prerequisite.
