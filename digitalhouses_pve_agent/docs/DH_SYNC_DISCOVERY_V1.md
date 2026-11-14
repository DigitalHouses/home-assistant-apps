# PVE Agent — MQTT DH Sync Discovery v1

**Status:** released as DigitalHouses PVE Agent 0.5.89 and validated live on
CORE PVE 192.168.11.240 against MQTT broker 192.168.11.242.

**Canonical consumer contract:**
[DH Sync Discovery Contract v1](../../digitalhouses_sync_app/docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md).

**Canonical resource publication standard:**
[DH Sync Resources Standard](../../docs/standards/DH_SYNC_RESOURCES_STANDARD.md).
The PVE-specific resources and rollout caveats are in
[DH Sync resources](DH_SYNC_RESOURCES.md).

## Identity and publication

The running PVE Agent uses the existing stable `instance_id`, derived from
its configured `general.instance_id` or `/etc/machine-id`. On every
successful MQTT connect or reconnect, the existing MQTT client publishes
**QoS 1, retained** JSON to:

```text
DigitalHouses/Global/digitalhouses_pve_agent/<instance_id>/sync
```

The payload is generated from the *running* Agent version (same `VERSION`
source as Home Assistant Discovery):

```json
{
  "schema": 1,
  "product_id": "digitalhouses_pve_agent",
  "type": "agent",
  "version": "0.5.89",
  "repository": "https://github.com/DigitalHouses/home-assistant-apps",
  "product_path": "digitalhouses_pve_agent"
}
```

The version above is illustrative, not hard-coded. No host IP, credentials,
hostname, site identity or authorization secret is included. Existing
configurable MQTT topic prefixes remain valid for legacy traffic; `/sync`
always uses the canonical `DigitalHouses/Global/digitalhouses_pve_agent`
namespace. There is no new MQTT client, heartbeat, polling loop or reconnect
logic.

## Unchanged product contracts

- Existing product-level retained online/offline availability and LWT.
- Independent UPS availability and NUT/UPS shutdown protection.
- Existing Home Assistant MQTT Discovery and stable entity IDs, including
  `sensor.dh_pve_agent_version` and `sensor.dh_pve_agent_started`.
- CLI, updater, Recorder and notification event contracts.

Retained `/sync` is a declaration of a product source, not proof of online
availability or evidence of uninstall. A disconnected PVE Agent does not
delete its retained metadata.

## DH Sync behavior

DH Sync 0.4.0+ discovers this metadata and **automatically** synchronizes
canonical RU dashboards and packages from the public Git repository owned by
DigitalHouses, on discovery and hourly. The owner is the only product-source
admission rule. Product version, optional revision comment headers and
`product_path` are not approval gates. Earlier manual Apply/pinned-source
descriptions are superseded.

The Agent **does not** download YAML or install packages itself. See
[DH Sync resources](DH_SYNC_RESOURCES.md) for the exact published files and
auto-sync impact.

## Acceptance

Release v0.5.89 was installed and verified on CORE with matching release
commit, connected MQTT, actual retained QoS 1 `/sync` content and live UPS
telemetry. The two CORE v3 views were visually accepted separately. New DH
Sync automatic file synchronization should be validated by DH Sync's own
tests and runtime diagnostics; it is not part of PVE Agent's Linux executable.
