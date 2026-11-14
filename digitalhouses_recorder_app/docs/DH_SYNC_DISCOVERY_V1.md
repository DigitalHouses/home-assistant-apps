# DigitalHouses Recorder App — DH Sync Discovery v1

**Status:** source-level dashboard compatibility reviewed against the immutable
Recorder App `0.1.28` release. Proposed `DH-Compatible-App` range is limited
to `>=0.1.28,<0.1.29`. **Live frontend acceptance is still outstanding:**
this metadata-only change must remain Draft until operator confirmation.
No dashboard installation, CORE/HOME modification, or YAML adoption is implied. The canonical specification is
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
| `DH-Compatible-App` | `>=0.1.28,<0.1.29` (source-level candidate; live UI pending) |
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

## Recorder 0.1.28 compatibility review — source-level evidence

The reviewed runtime is the immutable release
`digitalhouses_recorder_app-v0.1.28`, whose source resolves to
`2434d53dd9af2485e5650625b8a84fbd4e95f410`.
The App's `config.yaml` declares `0.1.28`; the running-version
`sensor.dh_recorder_app_version` and MQTT Discovery device/origin versions
share the validated `APP_VERSION`. The established product-level
`availability` and retained `/sync` are independent of database/storage
subsystem availability.

The canonical RU file, after stripping its initial DH metadata comment lines,
matches `examples/lovelace/dh_recorder_app_dashboard.yaml` byte-for-byte.
The **original Git blob SHA-1** is
`45dd279a425c0165deccdb0b53e6d9fe6b37a8af`. The source is the
maintained Recorder App dashboard from the 0.1.28 release; no card,
template, graph, service call, view title, or Lovelace `path: recorder`
was changed. Only the compatibility comment was added here. The independent
view revision stays at **1.0.0**, with date **2026-11-14**.

All Recorder `sensor.*`, `binary_sensor.*`, `number.*` and `button.*`
references in the view are checked against the **real 0.1.28 MQTT
Discovery payload** with optional storage enabled. The exceptions are the
Supervisor-provided `update.digitalhouses_recorder_app_update` update entity
and `button.press` / `update.install` action names; these are not App MQTT
entities. Existing refresh, check-updates, Supervisor update-with-backup and
app-restart actions, rolling data graphs, Top-entities attributes and offline
placeholders are preserved. They are not replaced by new identities.

The compatibility expression is accepted by the DH Sync
`resource_preview.compatible` grammar and includes **only 0.1.28**,
excluding both 0.1.27 and 0.1.29. It is a review candidate based on
source/runtime contract evidence, **not evidence of successful live rendering**.

## Live CORE HAOS acceptance required before merging

The operator has reported Recorder App **0.1.28 Online** in DH Sync 0.2.0.
This is evidence of MQTT product discovery but **not** visual acceptance of
the dashboard. The CORE browser pages were not connected when checked;
a read-only network probe established that the CORE HAOS web host responds,
but an authenticated UI/entity/HACS-resource audit was not available.

Before this PR leaves Draft, inspect the current Recorder dashboard in CORE
HAOS **without editing it**, and confirm:

1. Recorder App Version reads `0.1.28`; the database connected/writing
   cards, database details and optional disk usage render, or show truthful
   unavailable states when a subsystem is not configured.
2. Mushroom template/chips/number cards, `button-card >= 5.0`,
   `mini-graph-card` (including the hourly/daily `delta` graphs), and
   `custom:entity-progress-card-template` all load without missing-resource
   errors. These are frontend/HACS dependencies, not bundled by Recorder App.
3. The Refresh, Check updates, optional Supervisor Update (backup-before-update)
   and Restart controls are visible and correctly configured. No destructive
   actions or updates are required as part of acceptance.
4. Top Recorder 24h/all-time tables show absolute row counts and attribute
   templates as intended; `path: recorder` remains the single existing
   Lovelace view path. Note any user-customized source differences for later
   *separate* DH Sync adoption comparison.

**Do not apply a view, install HACS cards, mutate `/config`, restart HA,
run an update, or initiate rollback during this review.** Once live
acceptance is reported, the PR can be made Ready for normal CI-gated merge.

## Remaining limitations

- Only the existing Russian locale is verified at the source level;
  no English placeholder is generated.
- A working CORE view may differ from the repository's maintained
  example; DH Sync must diff and back up an existing local file before
  a separately approved adopt/apply. Product-only changes do not authorize
  replacement.
- The DH Sync 0.2.0 preview pin registry currently covers PVE/Plex only;
  pinning the **future immutable merged SHA** of this Recorder-only PR is a
  separate DH Sync change. The product MQTT `/sync` record does not grant
  installer authorization.
- No Recorder executable version bump, other-product changes, package
  creation, or automatic install is permitted for this metadata update.



## Regression and acceptance

```bash
python -m unittest discover -s digitalhouses_recorder_app/tests -p 'test_*.py'
python scripts/validate_repository.py
```

Product tests cover exact retained topic/payload, producer owner, version
sharing, connect/reconnect QoS 1, unchanged public identities, the locked
immutable baseline Git blob SHA, an exact unchanged Lovelace body, the narrow
App 0.1.28 compatibility range, the real Discovery entity set, controls,
graphs and frontend dependency references. CI also checks the repository
contract and Recorder container image. Tests **do not** claim visual HACS
rendering or live CORE/Home Assistant acceptance.

After a released App `0.1.28` is installed with explicit consent to
statistics collection, inspect the retained `/sync` topic, restart or
reconnect MQTT, verify `availability` and Version/Started at, then review
the candidate dashboard in a **separate** HA/DH Sync adoption step.
