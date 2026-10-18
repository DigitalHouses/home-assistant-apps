# DigitalHouses Zigbee Monitor App — installation and acceptance

Version: **0.1.3 (experimental)**. Run only after the production GHCR image
`ghcr.io/digitalhouses/digitalhouses_zigbee_monitor_app:0.1.3` is published
and verified by repository release workflows.

## Requirements

- Home Assistant OS and the MQTT integration with Supervisor MQTT service.
- Each Zigbee2MQTT instance connected to that MQTT broker.
- Zigbee2MQTT `availability.enabled: true` on all monitored instances to
  populate offline counts (required for complete availability; default Z2M
  setting is false). Do not trigger Zigbee pings from this App.
- The application discovers networks automatically from Zigbee2MQTT bridge MQTT messages; no network list is needed.

Example App options:

```yaml
telemetry_enabled: true
log_level: info
```

On MQTT connection the App listens to retained `+/bridge/devices` and
`+/bridge/info` (and equivalent 2–3-component prefixes). A bridge is accepted
**only if the coordinator IEEE can be validated**. For each confirmed bridge
the App subscribes to the exact discovered `base_topic/#`. No broker-wide
`#` subscription or Zigbee2MQTT control request is used.

Coordinator IEEE becomes the durable network identity, and the current
`base_topic` is an updateable route, stored in `/data/activity.sqlite3`.
Discovery is rerun after MQTT reconnect, and during manual refresh. Former
v0.1.0 manual network IDs are retained as migration hints when matching
bridge topics are recognized. A coordinator *replacement* at an existing
topic is not automatically treated as the same network: a deliberate
migration is required to avoid corrupting history.

If none are found, the App stays running and waits for a recognizable
bridge message. It does **not** publish a false "0 devices" as reliable.
MQTT bridge info isn't guaranteed to be retained on all installations;
retained `bridge/devices` provides the boot-time fallback.

Discovery supports Zigbee2MQTT MQTT `base_topic` paths containing **1 to 3
segments**. Longer hierarchies are not autodetected in this release.

The `network_id` is preserved across base-topic changes; each device is
keyed by IEEE. History and installation-specific telemetry state live
under `/data`, backed up with the Home Assistant App (cold backup).

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

The first release computes discovered network counts, confirmed device and
offline counts, MQTT-message activity rate and TOP lists. Unknown availability
is never a real zero. The `spammers` and `incidents` scalar entities remain
unavailable until the respective engines are implemented.

## Обновление из статусной карточки

Кнопка «Версия» обращается к опубликованным GitHub Release и сообщает,
есть ли новая версия. При подтверждении новая кнопка «Новая версия»
появляется по состоянию `binary_sensor.dh_zigbee_monitor_app_update_available`.
Она открывает страницу установленного приложения в Home Assistant Supervisor.

**Установка и резервное копирование остаются под управлением Supervisor.**
Обнаруженный GitHub-релиз ещё не гарантирует, что Supervisor уже загрузил
актуальный каталог или сделал обновление доступным. В этом случае обновите
каталог приложений в HA и затем установите обновление там.
Команда `update.install` не вызывается, пока нет подтверждённой
устанавливаемой Supervisor update-сущности.

Таймер операции показывает `мм:сс`, а итоговая длительность округляется
до целых секунд (как в Internet App). YAML-карточка и Dashboard — это
отдельные конфигурации Lovelace: обновление Python App **не заменяет**
ранее вручную вставленный YAML в панели HA.

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
