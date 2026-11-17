# DigitalHouses Sync App — 0.6.0

**Single standard:** [DH Sync Resources Standard](../docs/standards/DH_SYNC_RESOURCES_STANDARD.md).

DH Sync publishes GitHub-owned Home Assistant panels and packages, using retained MQTT `/sync` as its **only product registry**.

- Admit every product whose canonical repository is under GitHub owner `DigitalHouses`, with no availability, product, or version filters.
- Read ordered panel definitions from `digitalhouses_sync_app/dashboards/*.yaml`. Each file controls its dashboard's title, icon, sidebar visibility, `require_admin`, and referenced Views.
- Read standalone Views from the MQTT-discovered product's `dashboards/ru/*.yaml`. A View can appear in multiple panels, with independent tab icon and title.
- Use the sequence of entries in each panel file as the tab order. MQTT `dashboard` is ignored.
- Apply dashboard content via Home Assistant's official WebSocket APIs (Storage mode), not direct `.storage` edits or local View YAML copies.
- Synchronize packages from `packages/common/*.yaml` and `packages/locales/ru/*.yaml`, with safe atomic writes and backups.
- Automatically request a quick HA configuration reload when packages change. Never restart HA or change other Apps/Agents.
- Automatically sync after retained MQTT changes and then hourly. No user confirmation or extra product registry.

**Clean start:** v0.6.0 does not migrate old dashboards, former View folders, or MQTT routing. Existing dashboard URLs present in the new YAML are updated; unrelated or legacy panels are not deleted automatically.

Tests: `PYTHONPATH=digitalhouses_sync_app/rootfs/app:digitalhouses_sync_app/tests python -m unittest discover -s digitalhouses_sync_app/tests -p 'test_*.py'`
