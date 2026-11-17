# DigitalHouses PVE Agent — DH Sync 0.6.0 resources

**Normative specification:** [DH Sync Developer Standard](../../docs/standards/DH_SYNC_DEVELOPER_STANDARD.md).
**Notifications:** [Events & Notifications Standard](../../docs/standards/EVENTS_AND_NOTIFICATIONS_STANDARD.md).

## Product identity (MQTT)

The existing MQTT client publishes on every successful connect/reconnect:

```text
DigitalHouses/Global/digitalhouses_pve_agent/<instance_id>/sync
```

Publish options: **QoS 1**, **retain=true**. Payload:

```json
{
  "schema": 1,
  "product_id": "digitalhouses_pve_agent",
  "type": "agent",
  "version": "<running agent version>",
  "repository": "https://github.com/DigitalHouses/home-assistant-apps",
  "product_path": "digitalhouses_pve_agent"
}
```

The agent reuses its existing stable `instance_id` and MQTT connection.
No `dashboard`, `panel`, `view`, `order`, permissions, secrets, or Git SHA
are sent. Availability/LWT remain separate and do not control DH Sync discovery;
disconnect does not clear the retained `/sync`.

## Canonical resources

All paths below are relative to `digitalhouses_pve_agent/`:

| Resource | File | Stable View path |
| --- | --- | --- |
| Proxmox View | `dashboards/ru/10_pve_proxmox.yaml` | `dh_pve_agent` |
| UPS View | `dashboards/ru/11_pve_ups.yaml` | `dh_pve_agent_ups` |
| Common Package | `packages/common/dh_pve_agent_package.yaml` | — |
| Russian notifications | `packages/locales/ru/dh_pve_agent_notification_local_package.yaml` | — |

The notifications package uses portable `persistent_notification.create`.
Private `script.write2admins` delivery is an **opt-in example only**, under
`examples/`; it is never distributed by DH Sync. Do not install both the
canonical notification package and a local copy of the same automation.

Each canonical View is a self-contained Lovelace View with a stable `path`.
View metadata comments are informational; GitHub commit history tracks changes.
View/Package updates do not require a Linux Agent release.

## Ownership

The PVE Agent owns its MQTT declaration, two Views and Packages. Only DH Sync
owns Dashboard panel files, View placement and order, sidebar labels/icons and
access controls. A View can be referenced from multiple panels.

For panel registration, provide to DH Sync:

- `digitalhouses_pve_agent` + `dh_pve_agent`
- `digitalhouses_pve_agent` + `dh_pve_agent_ups`

No compatibility allowlist, online requirement, version matching, manual Apply
approval, or legacy-YAML migration belongs in the PVE Agent.

## Validation

```bash
PYTHONPATH=digitalhouses_pve_agent python -m pytest digitalhouses_pve_agent/tests -q
python scripts/validate_repository.py
```
