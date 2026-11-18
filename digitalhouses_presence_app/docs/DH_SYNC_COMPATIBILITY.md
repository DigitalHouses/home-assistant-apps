# DH Presence App — DH Sync 0.6.0

The only authoritative developer contract is
[DH Sync Developer Standard](../../docs/standards/DH_SYNC_DEVELOPER_STANDARD.md).

## MQTT declaration

The existing Paho client publishes QoS 1, retained `/sync` on every
successful connection and reconnection:

`DigitalHouses/Global/digitalhouses_presence_app/sync`

The JSON has exactly six keys: `schema: 1`,
`product_id: digitalhouses_presence_app`, `type: app`,
`version` (from `APP_VERSION`), `repository:
https://github.com/DigitalHouses/home-assistant-apps`, and
`product_path: digitalhouses_presence_app`.

This declaration is independent of availability and the older operational
MQTT base `DigitalHouses/Global/dh_presence_app`, which remains unchanged
to preserve Home Assistant entity IDs and existing automations. It does
not carry Dashboard/View routing, per-home values, or credentials. No
second client, heartbeat, or extra timer is introduced.

## Canonical view

- File: `digitalhouses_presence_app/dashboards/ru/presence.yaml`
- Pair: `product: digitalhouses_presence_app` + `path: presence`
- One self-contained Lovelace `sections` View, retaining the existing
  four-column layout and stable entity IDs.
- Frontend dependencies: Mushroom, Button Card >= 5.0, and HACS Auto Entities.
  These are required by the maintained four-column view in `examples/`
  as well. Installing the View is not a method of installing these resources.

The matching legacy example remains in `examples/lovelace/` for manual
use; only `dashboards/ru/` is published to DH Sync.

## Packages

There is currently **no portable canonical Package** for automatic
installation. The two existing Russian notification packages stay under
`examples/packages/` for opt-in, manual local use: they deliberately call
the private per-home `script.write2log`. Automatically installing either
one would violate the DH Sync portability rule and could duplicate an
already installed automation. Existing automation IDs, event schemas, and
notification behavior are unchanged. Recorder exclusions also remain
managed per home; do not overwrite an existing Recorder configuration.

The presence App does not create or modify any DH Sync Dashboard. To place
this View in a panel, send the following to the DH Sync maintainers:

```yaml
- product: digitalhouses_presence_app
  path: presence
```

## Verification

- `PYTHONPATH=digitalhouses_presence_app/rootfs/app python -m unittest discover -s digitalhouses_presence_app/tests -v`
- `python scripts/validate_repository.py`
- Confirm retained QoS 1 `/sync` after connect and reconnect using an MQTT subscriber.
