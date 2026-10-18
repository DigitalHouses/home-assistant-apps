# DigitalHouses Zigbee Monitor App — installation and acceptance

Version: **0.1.6 (experimental)**. Run only after the production GHCR image
`ghcr.io/digitalhouses/digitalhouses_zigbee_monitor_app:0.1.6` is published
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

The App computes discovered network counts, confirmed device and
offline counts, MQTT-message activity rate and TOP lists. Unknown availability
is never a real zero. When any device is confirmed offline, that positive count
is an explicitly partial lower bound if other devices are unknown. The `spammers` and `incidents` scalar entities remain
unavailable until the respective engines are implemented.

## Питание, availability и активность MQTT

App уже подписан на `<base_topic>/#` Zigbee2MQTT. Он читает из
retained `bridge/devices` официальные поля `type` / `power_source`
(например `Battery`, `Mains (single phase)`, `DC Source`)
и показывает их в Recorder-excluded `inventory_details`.

Для каждого IEEE фиксируется дата и время **последней наблюдаемой новой
публикации MQTT** из его собственного топика; retained/MQTT DUP, события
групп, служебные `bridge/*` и команды `/set`/`/get` игнорируются.
Устройство может публиковать MQTT после получения Zigbee-сообщения,
но эта временная отметка **не является** достоверным временем последней
радиопередачи Zigbee. Чтобы получить именно это время, Zigbee2MQTT
должен публиковать отдельный `advanced.last_seen`, а он по умолчанию
выключен; App не изменяет эту настройку.

Последний MQTT timestamp сохраняется в SQLite вместе с минутными
агрегатами, без записи каждого сообщения. UI детали обновляются не чаще
раза в минуту по активности. После перезапуска последнее значение берётся
из SQLite; у устройств без наблюдений остаётся `null`.

**Политика достоверности:** `availability` берётся исключительно из
`<base_topic>/<friendly_name>/availability` Zigbee2MQTT, если такой
статус поступал; без него статус остаётся `unknown`. Не подменяем
`online` последним MQTT-сообщением и не создаём свои timeout/ping,
особенно для батарейных EndDevice. Глобальный offline-счётчик остаётся
`unavailable`, если нет подтверждённых offline и при этом не вся availability
известна. Подтверждённые offline отображаются как положительный счётчик и
в `offline_details` **даже при неизвестных других устройствах**. Метаданные
`availability_complete` и `availability_unknown` указывают на неполноту.

Источник: https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html
и https://www.zigbee2mqtt.io/guide/configuration/device-availability.html

## События появления/исчезновения устройств и Zigbee2MQTT

Текущее состояние устройства берётся только из retained
`<base_topic>/<friendly_name>/availability`. Текущее состояние каждого
экземпляра Zigbee2MQTT — из retained `<base_topic>/bridge/state`.
Это два независимых источника: при остановке Z2M нельзя объявлять все
его устройства offline.

Переходные машинные события публикуются через MQTT Event Discovery:
`event.dh_zigbee_monitor_app_event`, MQTT topic
`DigitalHouses/Global/dh_zigbee_monitor_app/event`.

| event_type | Переход |
|---|---|
| `device_offline` | подтверждённое online → offline устройства |
| `device_online` | подтверждённое offline → online устройства |
| `zigbee2mqtt_offline` | `bridge/state` online → offline |
| `zigbee2mqtt_online` | `bridge/state` offline → online |

Каждое событие несёт `schema_version=1`, `event_type`,
`observed_at`, `network_id`, `previous_state`, `current_state` и
`severity`. Для device-события дополнительно присутствуют
`ieee_address` и `friendly_name`, для Z2M — `base_topic`.
Это не локализованное уведомление, а типизированный факт.

Машинные события отправляются **QoS 1, retain=false** после
публикации retained текущего состояния. Первый известный статус,
retained при подключении, MQTT DUP и первичная сверка после
переподключения не генерируют событие. После потери связи с самим
Zigbee2MQTT baseline устройств сбрасывается, чтобы восстановление
источника не породило массовые «восстановления» конечных устройств.

Последнее состояние остаётся доступным в `inventory_details`,
`networks_details`, `offline_details`, независимо от получения Event
в HA. События не доставляются задним числом после простоя HA.

Включать уведомления для пользователей должен **локальный HA-пакет**.
Опциональный пример:
`examples/packages/dh_zigbee_monitor_notifications_example.yaml`.
Он иллюстрирует прямой `event.received` + `trigger.id` + `choose`
+ `persistent_notification.create`; для production замените действие
на действующий `script.write2admins` или выбранный `notify.*`.

Ограничение: `bridge/state` различает запущен/остановлен, **но не
измеряет перегрузку**, зависание без MQTT LWT, длительность задержек
доставки или загрузку CPU. Никаких фиктивных «overload» событий.

## Ручное «Обновить» (read-only)

По подтверждённому стандарту Internet App команда `Refresh` обновляет
фактические данные продукта и показывает статус выполнения, а не требует
здоровья каждого опционального источника.

Для Zigbee Monitor полнота `Refresh` означает:
- повторное обнаружение существующих сетей Zigbee2MQTT;
- получение `bridge/devices` и подтверждённого `bridge/state = online`
  для каждой обнаруженной сети после начала операции;
- успешную публикацию доступного инвентаря/состояния.

**Availability каждого отдельного устройства не обязательна для завершения
Refresh.** Если Zigbee2MQTT не отправляет такие сообщения (например,
`availability.enabled: false`), числовой `offline`
по-прежнему `unavailable`, а `offline_details` показывает пустой
**подтверждённый** список и флаг неполных данных. Диагностический
`inventory_details` показывает `availability_not_reported`.
Мы не записываем фиктивный offline = 0.

Если bridge либо inventory недоступны, обновление завершается ошибкой
после тайм-аута с указанием именно отсутствующей части. `last_refresh`
изменяется только после подтверждённого успешного обновления.

## Обновление из статусной карточки

Кнопка «Версия» проверяет опубликованные GitHub Release и устанавливает
`binary_sensor.dh_zigbee_monitor_app_update_available`, если новая версия
найдена. Это информационный индикатор, **не разрешение на установку**.

Кнопка «Новая версия» появляется только при
`update.digitalhouses_zigbee_monitor_app_update = on` — установленная
на объекте Supervisor update-сущность, проверенная в пилотном HA.
При нажатии карточка вызывает `update.install` с
`entity_id: update.digitalhouses_zigbee_monitor_app_update` и
`backup: true`, после подтверждения пользователя. Никаких переходов на
предполагаемые URL страницы Supervisor.

Если новая версия обнаружена в App, но Supervisor ещё не предлагает
установку, кнопка установки остаётся скрытой до обновления каталога.
**Карточка сообщает об этом прямо**: «Релиз опубликован, Supervisor не
предлагает установку». Наличие обновления GitHub Release не означает,
что установка возможна прямо сейчас. Кнопка не появляется по одному
лишь App binary_sensor.

Иконка обновления/предупреждения имеет приоритет над кратковременной
зелёной отметкой успешной проверки версии; при отказе Zigbee2MQTT
показывается ошибка источника, а успешный check не объявляет сеть
здоровой. В заголовке стрелка отображается только для семантически
**более новой** версии, а не любой отличающейся строки. При недоступном
App показано отсутствие связи; во время установки Supervisor в
приоритете реальный `in_progress` и его процент.

Таймер показывает `мм:сс`, финальная длительность округляется
до целых секунд (как в Internet App). YAML-карточка и Dashboard —
отдельные конфигурации Lovelace: обновление Python App **не заменяет**
вручную вставленный YAML в панели HA.

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
- No local delivery notifications are installed by the public App: it publishes
  four machine Event types for optional site-local Home Assistant automation.
- Anomaly detection and incident engine are not implemented yet.
- End-to-end tests against a real HAOS installation and Recorder are required
  before declaring production acceptance.
