# DigitalHouses Recorder App — DH Sync Discovery v1

**Status:** product candidate for Recorder App `0.1.28`. No deployment to
Home Assistant, compatibility-range certification, or YAML adoption is implied
by merging this document. The canonical specification is
[`digitalhouses_sync_app/docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md`](../../digitalhouses_sync_app/docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md).

## Source and identity

- Canonical product: `digitalhouses_recorder_app`, type `app`.
- Repository: `https://github.com/DigitalHouses/home-assistant-apps`.
- Product directory: `digitalhouses_recorder_app`.
- Running version: the validated `APP_VERSION` used by MQTT Discovery
  `device.sw_version`, `origin.sw_version`, and
  `sensor.dh_recorder_app_version`. The App version is defined by
  `config.yaml` and the released immutable GHCR image; it is not the
  dashboard revision.

## MQTT producer

The existing single App instance publishes:

```text
DigitalHouses/Global/digitalhouses_recorder_app/sync
```

On **each successful MQTT connection and reconnect**, the existing Paho
client publishes the following **QoS 1 retained** JSON using its existing
`publish_json` method:

```json
{
  "schema": 1,
  "product_id": "digitalhouses_recorder_app",
  "type": "app",
  "version": "0.1.28",
  "repository": "https://github.com/DigitalHouses/home-assistant-apps",
  "product_path": "digitalhouses_recorder_app"
}
```

The version is illustrative; it is built from the currently **running** App,
never fetched from GitHub. The repository URL and product path are constants,
not editable through MQTT or the App options. This message is a **claimed
source only**, not permission to fetch/execute/install YAML or executable code.
It contains no database host/user/password, MQTT credential, installation ID,
IP address, tenant data or telemetry data. No new timer, heartbeat, client,
broker subscription or reconnect strategy is added.

## Existing product contract — unchanged

| Interface | Value |
| --- | --- |
| Product availability | `DigitalHouses/Global/digitalhouses_recorder_app/availability` |
| MQTT Discovery | `homeassistant/device/digitalhouses_recorder_app/config` |
| MQTT Discovery device ID | `digitalhouses_recorder_app` |
| Version | `sensor.dh_recorder_app_version` |
| Started at | `sensor.dh_recorder_app_started_at` |
| DB availability | `DigitalHouses/Global/digitalhouses_recorder_app/database_availability` |
| DB status availability | `DigitalHouses/Global/digitalhouses_recorder_app/database_status_availability` |
| DB static availability | `DigitalHouses/Global/digitalhouses_recorder_app/database_static_availability` |
| Storage availability | `DigitalHouses/Global/digitalhouses_recorder_app/storage_availability` |

The product-level LWT is retained `offline` at QoS 1, and a successful
connect publishes retained `online`. It is separate from DB/storage subsystem
availability. When the App stops normally, it publishes product `offline`
before disconnecting. MQTT loss invokes the existing LWT. The retained `/sync`
metadata remains at the broker through disconnections; neither offline nor the
mere absence of a message proves uninstall. No uninstall tombstone or
automatic dashboard removal is introduced.

Recorder queries, rankings, sensors, database configurations, events, settings,
backup, telemetry-consent gating, release checks and manual refresh all retain
their public contracts.

## Canonical Lovelace resource

| Field | Value |
| --- | --- |
| Path | `dashboards/ru/10_recorder.yaml` |
| `DH-View` | `dh_recorder_app` |
| `DH-View-Version` | `1.0.0` |
| `DH-View-Date` | `2026-11-14` |
| Lovelace path | `recorder` |
| View type | `sections` |
| Source baseline | `examples/lovelace/dh_recorder_app_dashboard.yaml` |

This is an unchanged standalone copy of the maintained Russian dashboard
apart from its DH-View comment header. Existing entities, controls, data
templates and view path are preserved. Existing user-edited copies under HA
`/config` must not be silently replaced or adopted. DH Sync must compare and
back up existing files before a user-approved adoption.

Frontend custom-card requirements: **Mushroom**, **button-card >= 5.0**
(for `update_timer`), **mini-graph-card**, and
**entity-progress-card / custom:entity-progress-card-template**.
They must be installed separately; DH Sync does not install HACS components.
The dashboard continues to display its existing offline/unknown states.

**No canonical HA package is published:** Recorder App currently uses its
App/MQTT Discovery integration and maintains no general-purpose HA package.
Do not add empty `packages/` directories.

**Open gaps:**
- Only the maintained Russian dashboard is currently available. English
  translation is not yet approved; no placeholder EN view is provided.
- No `DH-Compatible-App` range is asserted. The YAML is copied from a
  maintained view but live HA acceptance across version ranges has not yet
  been completed. DH Sync must not auto-apply an unverified revision.
- A real broker/HA reconnect and UI acceptance check after packaging the new
  GHCR release remains outstanding. The read-only Sync catalog has been
  implemented separately; this producer does not test its end-to-end
  installation behavior.

## Regression and acceptance

```bash
python -m unittest discover -s digitalhouses_recorder_app/tests -p 'test_*.py'
python scripts/validate_repository.py
```

Product tests cover exact retained topic/payload, producer owner, version
sharing, successful and failed connects, reconnect republishing, unchanged
public topic identities, QoS 1/retain flags and the canonical dashboard
baseline. They do not claim live HA acceptance or HACS card compatibility.

After a released App `0.1.28` is installed with explicit consent to
statistics collection, inspect the retained `/sync` topic, restart or
reconnect MQTT, verify `availability` and Version/Started at, then review
the candidate dashboard in a **separate** HA/DH Sync adoption step.
