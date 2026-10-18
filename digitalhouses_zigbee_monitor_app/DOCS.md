# DigitalHouses Zigbee Monitor App — installation and acceptance

Version: **0.1.0 (experimental)**. Run only after the production GHCR image
`ghcr.io/digitalhouses/digitalhouses_zigbee_monitor_app:0.1.0` is published
and verified by repository release workflows.

## Requirements

- Home Assistant OS and the MQTT integration with Supervisor MQTT service.
- Each Zigbee2MQTT instance connected to that MQTT broker.
- Zigbee2MQTT `availability.enabled: true` on all monitored instances to
  populate offline counts (required for complete availability; default Z2M
  setting is false). Do not trigger Zigbee pings from this App.
- Configure at least one explicit network with immutable `network_id`.

Example Zigbee2MQTT App options:

```yaml
zigbee2mqtt:
  - network_id: floor_1
    name: Первый этаж
    base_topic: zigbee2mqtt_1
  - network_id: floor_2
    name: Второй этаж
    base_topic: zigbee2mqtt_2
telemetry_enabled: true
log_level: info
```

Names and topics above are examples. No installation-site addresses or
credentials are embedded in the public application.

The `network_id` is a stable logical identifier; `friendly_name` and HA
`entity_id` are never the database key. Each device is keyed by IEEE, with
historical minute counts retained through friendly-name changes. History and
installation-specific telemetry state live under `/data` and are backed up
with the Home Assistant App (cold backup).

## Telemetry consent and privacy

Acceptance via `telemetry_enabled` (default `false`) is mandatory for
supported operation. When false the App logs refusal and exits; on acceptance
the product sends only the approved schema, telemetry policy version,
installation UUID, canonical product ID and version to the official endpoint.
The random installation token is a secret used for authorization. Telemetry
unavailability does not interrupt core monitoring. Delete Telemetry is
available through the HA MQTT device's diagnostic button.

Do not transmit the Zigbee device inventory, IEEE addresses, MQTT topics or
other monitoring details to DigitalHouses telemetry.

## Recorder policy

Install or merge the reference policy:
`examples/packages/dh_zigbee_monitor_app_global_package.yaml`.

**Do not overwrite a site's Recorder include/exclude.** Confirm that only
historical scalar sensors are recorded; detail, event and app-card entities
must remain excluded. Inspect the actual Recorder DB after at least 24 hours.

The first release computes configured network counts, confirmed device and
offline counts, MQTT-message activity rate and TOP lists. Unknown availability
is never a real zero. The `spammers` and `incidents` scalar entities remain
unavailable until the respective engines are implemented.

## Dashboard

Reference Lovelace:
`examples/lovelace/dh_zigbee_monitor_app_dashboard.yaml`.
The layout is `sections` and uses Mushroom and custom:button-card. It is
intentionally a view: calculations, filtering and history are App-owned.

## Limitations

- MQTT message rate is not Zigbee RF airtime/packet rate.
- Top 24h and 7d may include incomplete observation windows after fresh install;
  snapshots include `window_complete`.
- Does not perform automatic healing, device control, reporting configuration,
  Zigbee interviews or Zigbee pings.
- Source availability depends on Zigbee2MQTT configuration and retained state.
- No event-based offline incident notifications or anomaly detection yet.
- End-to-end tests against a real HAOS installation and Recorder are required
  before declaring production acceptance.
