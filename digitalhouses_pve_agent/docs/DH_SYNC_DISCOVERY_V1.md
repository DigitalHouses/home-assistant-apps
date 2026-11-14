# DH PVE Agent — DH Sync Discovery Contract v1

Status: product PR candidate. No release or deployment to live PVE/HA
performed. Canonical spec:
[DH Sync Discovery Contract v1](https://github.com/DigitalHouses/home-assistant-apps/blob/feature/digitalhouses-sync-app-contract/digitalhouses_sync_app/docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md).

## Identity and source

- Canonical product ID: `digitalhouses_pve_agent`; registry type: `agent`
  (existing `digitalhouses-stats/digitalhouses_stats/product_registry.json`).
- Release version: read exactly once at agent startup from
  `digitalhouses_pve_agent/VERSION` by `app.main._version()`, the same
  value already passed to Home Assistant Discovery and runtime diagnostics.
  The new payload contains the **running** version. An installed update
  restarts the agent; the following MQTT connect publishes the new version.
- Repository: `https://github.com/DigitalHouses/home-assistant-apps`
  (constant, not a user-configurable MQTT/CLI value).
- Product directory: `digitalhouses_pve_agent`.

## MQTT topic

The PVE Agent already uses one stable `instance_id` on every installation.
It defaults to the 32-character `/etc/machine-id` and can be explicitly set
through the existing `general.instance_id` config option.

Therefore PVE **always** publishes the instance-qualified variant:

```text
DigitalHouses/Global/digitalhouses_pve_agent/<instance_id>/sync
```

The message is sent via the **existing** Paho MQTT client on every successful
connect (including reconnect), **QoS 1, retained**. No new timer, reconnect
loop, broker connection or subscription. The announcement is static per
running process; a product version change is announced on the next normal
connection after restart.

Typical JSON for released 0.5.88 (the version is dynamically read, not fixed
in code):

```json
{
  "schema": 1,
  "product_id": "digitalhouses_pve_agent",
  "type": "agent",
  "version": "0.5.88",
  "repository": "https://github.com/DigitalHouses/home-assistant-apps",
  "product_path": "digitalhouses_pve_agent"
}
```

No IP, hostname, site ID, credentials, user, serial, token, SHA or YAML version
is included. A custom old `mqtt.topic_prefix` is **preserved** for all
previous messages, while the new `/sync` remains in the canonical
`DigitalHouses/Global/digitalhouses_pve_agent` namespace.

## Existing MQTT / HA contract — unchanged

- Product-level availability: the existing
  `<mqtt.topic_prefix>/<instance_id>/availability`, usually
  `DigitalHouses/Global/digitalhouses_pve_agent/<instance_id>/availability`,
  retained `online` after connect, retained QoS1 LWT `offline`.
- UPS availability: `<mqtt.topic_prefix>/<instance_id>/ups/availability`
  (subsystem only; *not* an agent installation indicator).
- HA MQTT Discovery:
  `homeassistant/device/dh_pve_agent_<instance_id>/config`
  (existing device ID and MQTT prefix semantics, retained).
- Version: `sensor.dh_pve_agent_version`. Process started:
  `sensor.dh_pve_agent_started`.
- A disconnected agent does not delete the retained `/sync` message.
  Offline does **not** mean uninstall. The existing retry/backoff, LWT,
  UPS/NUT safety, Recorder, notifications, CLI and install/update paths
  are untouched.

## Implementation and trust boundary

- `app/topics.py:build_topics`: constructs exact canonical `sync` topic
  from the existing resolved instance ID; no changes to previous topics.
- `app/sync_discovery.py:build_sync_payload`: produces exactly five
  public identity fields plus schema from the runtime release version.
- `app/main.py:build_runtime`: passes the same `_version()` as Discovery.
- `app/mqtt_bridge.py:MqttBridge._on_connect`: publishes retained QoS1
  once per successful connect/reconnect.

Repository identity is a **claim** from the MQTT publisher. The PVE Agent
publishes a fixed, known URL; it does not take a repository URL from MQTT
and therefore does not need a URL allowlist of its own. DH Sync validates
the exact `DigitalHouses` GitHub owner through structural URL parsing.
DH Sync v0.1.0 displays accepted /sync data in a read-only catalog;
its Apply controller still uses only the three independently reviewed
and pinned Proxmox/UPS/Plex commits. This message is **not permission**
to download or install files, code or updates.

## Validation and open acceptance

```bash
PYTHONPATH=digitalhouses_pve_agent python -m pytest digitalhouses_pve_agent/tests -q
python scripts/validate_repository.py
```

Product regression tests validate instance-qualified and legacy override
topics, exact JSON fields, registry identity, genuine version source,
GitHub URL structure, connect/reconnect/failed-connect mock publication,
no leaked secrets, unchanged LWT/availability and no periodic announcements.

Gaps: broker-side retained QoS1 delivery and consumer display on real
PVE/HA have **not** been tested yet; production release and rollout require
separate approval. The corresponding canonical PVE dashboards belong to
separate PR #502. The candidate release source is `VERSION=0.5.89`; the feature appears
on operational agents only after publishing the canonical GitHub Release
and explicitly updating each selected PVE host.
