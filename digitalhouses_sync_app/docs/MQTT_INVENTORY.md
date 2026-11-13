# DH Sync — existing availability inventory (read-only audit)

This list is based on current product sources in `home-assistant-apps` at the time of drafting. It is an adapter table, **not** a demand to rename topics. Product teams must confirm actual deployed behavior, LWT, retain, and release version.

| Canonical product | Current product-level availability topic |
| --- | --- |
| `digitalhouses_pve_agent` | `DigitalHouses/Global/digitalhouses_pve_agent/<instance_id>/availability` |
| `digitalhouses_plex_agent` | `DigitalHouses/Global/digitalhouses_plex_agent/availability` for default `plex`; a non-default instance appends `/<instance_id>` |
| `digitalhouses_recorder_app` | `DigitalHouses/Global/digitalhouses_recorder_app/availability` |
| `digitalhouses_network_app` | `DigitalHouses/Global/dh_network_app/availability` |
| `digitalhouses_zigbee_monitor_app` | `DigitalHouses/Global/dh_zigbee_monitor_app/availability` |
| `digitalhouses_speedtest_app` | `DigitalHouses/Global/speedtest/availability` (deprecated product) |
| `digitalhouses_backblaze_app` | `DigitalHouses/Global/backblaze/availability` |

Further products (Presence, Internet, Aqara Switch, Climate, etc.) require product-owner confirmation before their availability namespaces enter the live DH Sync adapter list.

The preview App only considers positively observed `online` on known namespaces a new installation. Existing `offline` changes known state but never removes the installation. Missing retained data is `unknown`, not `uninstalled`.

Do not derive products from arbitrary matching MQTT sensor names; do not use subsystem availability as product identity.

**Important:** This adapter is a temporary v0.0.1 preview. Before production v1, verify actual deployed topics, discovery, variant instance IDs and reconnect behavior across HA restart. Allow manual add/adopt for legacy sites where reliable retained data is absent.

