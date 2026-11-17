# DigitalHouses Plex Agent — DH Sync 0.6.0 contract

The sole authoritative contract is
[DH Sync Developer Standard](../../docs/standards/DH_SYNC_DEVELOPER_STANDARD.md).
This document describes only Plex Agent's implementation, not a separate
compatibility, admission or Dashboard-routing standard.

## MQTT identity

Plex Agent publishes retained `/sync` via its existing Paho client on
every successful MQTT connect/reconnect with QoS 1 and `retain=true`.

- Default: `DigitalHouses/Global/digitalhouses_plex_agent/sync`
- Additional instance: `DigitalHouses/Global/digitalhouses_plex_agent/<instance_id>/sync`

The published JSON has exactly six keys:

```json
{
  "schema": 1,
  "product_id": "digitalhouses_plex_agent",
  "type": "agent",
  "version": "0.8.23",
  "repository": "https://github.com/DigitalHouses/home-assistant-apps",
  "product_path": "digitalhouses_plex_agent"
}
```

The shown version is illustrative: runtime `BuildInfo.version` is used
rather than a hard-coded value. No Dashboard, View, ordering, permissions,
machine address, credentials or Git SHA is published. An older retained
`dashboard` field is ignored by DH Sync 0.6.0 before the next reconnect.

The separate availability/LWT and Home Assistant MQTT Discovery topics stay
unchanged. Offline does not remove the product or clear retained `/sync`.
No additional MQTT connection, heartbeat, timer, migration, or manual
approval is required.

## Canonical GitHub resources

| Resource | Path | Stable identity |
| --- | --- | --- |
| Russian Lovelace View | `digitalhouses_plex_agent/dashboards/ru/12_plex.yaml` | `product_id: digitalhouses_plex_agent` + `path: dh-plex-agent` |
| Common Recorder Package | `digitalhouses_plex_agent/packages/common/dh_plex_app_package.yaml` | `dh_app_plex_monitoring_package` |

The View is one self-contained Lovelace `type: sections` document, not
a Dashboard definition. Its approved cards and `path` stay unchanged.
The Package retains its original entity IDs and one top-level key.
Plex Agent currently ships no localized notification Package; empty
`packages/locales/ru/` resources are not required.
Sample YAML in `examples/` is not installed by DH Sync.

Only DH Sync-owned `digitalhouses_sync_app/dashboards/*.yaml` controls
Dashboard title, icon, access, visibility, View membership and ordering.
One View can be used in several Dashboards. Plex Agent does not register
sidebars or edit Home Assistant `.storage`.

For inclusion in a Dashboard, send the following to the DH Sync maintainer:

```yaml
product: digitalhouses_plex_agent
path: dh-plex-agent
```

## Validation

- `python -m unittest discover -s digitalhouses_plex_agent/tests -v`
- `python scripts/validate_repository.py`
- Confirm QoS 1 retained `/sync` on connect/reconnect.
- Preserve the View `path` and existing Package/entity identities.

Historical 0.8.17–0.8.20 implementation notes are recorded in
[CHANGELOG.md](../CHANGELOG.md), not in the active DH Sync contract.
