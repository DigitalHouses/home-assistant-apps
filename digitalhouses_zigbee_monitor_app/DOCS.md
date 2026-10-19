# DigitalHouses Zigbee Monitor App — installation and acceptance

Version: **0.1.12 (experimental)**. Run only after the production GHCR image
`ghcr.io/digitalhouses/digitalhouses_zigbee_monitor_app:0.1.12` is published
and verified by repository release workflows.

## Единый конфиг координаторов и репитеров (0.1.11)

**Порядок для владельца HA:** запустить с пустыми списками →
дождаться auto-discovery → открыть штатный конфиг App →
при желании дополнить поля → посмотреть результат в дереве.
Без единого объекта в конфиге приложение запускается и выполняет
Zigbee2MQTT мониторинг.

Схема Supervisor `options`:

```yaml
telemetry_enabled: true
log_level: info
coordinators: []
repeaters: []
```

После обнаружения по MQTT появляется, например:

```yaml
coordinators:
  - ieee: "0x00124b002e1330dd"
    name: "zigbee2mqtt"
    model: ""                  # Физическая модель, если известна
    critical: false
    management_ip: ""          # USB сам по себе IP не имеет
    addon_slug: ""             # Не угадываем чужой Supervisor App
    healer_method: disabled   # Декларация, действие не выполняется
    power_switch: ""
repeaters: []
```

Дополнительные поля **необязательные**: достаточно IEEE.
Имена, модель, адрес, Critical, Supervisor App и PoE можно заполнить
позднее. Отсутствующие поля не считаются ошибкой запуска.
Репитеры — отдельный список; автодобавляются лишь точно
распознанные специализированные Router (для текущей версии модель
ZigStar-01/ZigStar-01 Repeater). *Zigbee Router* не равен
специализированному репитеру: неизвестные модели остаются только
в инвентаре, пока пользователь не укажет их вручную.

Детали реализации: `/addons/self/options/config` (GET),
`/addons/self/options` (POST) с default Supervisor ролью. Перед
автодобавлением App снова читает собственную текущую конфигурацию,
объединяет **только отсутствующие IEEE** и не изменяет ни одно
поле уже введённого объекта. Изменение Options действует после
следующего запуска Supervisor App; Zigbee Monitor также обновляет
собственное представление из прочитанных Options без рестарта.
При отсутствии Supervisor или сетевой ошибке App продолжает
мониторинг, а следующая попытка синхронизации будет позже.
При обновлении с 0.1.10 первая запись координатора перенесёт
имеющиеся пользовательские значения из SQLite, если они корректны.

В дереве IP показывается с **✅** после успешного настоящего ICMP
Ping и с **❓** при отсутствии ответа, некорректном IP или
недоступной проверке. Необходим `NET_RAW`, но роль Supervisor
остаётся `default`; команда Ping ограничена по времени и адресу.
Неответ по ICMP не доказывает сбой Zigbee (ICMP может блокироваться).
Ни Ping OK, ни Bridge online не подавляют персональный RPM:
см. [INCIDENT-001](docs/KNOWN_FAILURE_SCENARIOS.md).

**Безопасность:** никаких активных Zigbee-запросов, выключений PoE
или перезапусков Zigbee2MQTT, даже если `healer_method` выбран.
Привязки не верифицированы и Healer всегда OFF. Отдельные
`repeaters_details` — диагностический JSON, не Recorder.

## Беспаспортный реестр Zigbee2MQTT (0.1.10)

Сведения каждого агента состоят из двух независимых частей.

- **Автоматически:** сеть по IEEE, base_topic, Bridge, RPM, Zigbee version,
  serial USB/TCP, очевидный TCP host/IP, данные устройств и Problems.
- **Пользовательская policy (SQLite, HA UI):** display_name, critical,
  hardware_model, management_host, healer_method, addon_slug, power_switch.
  Никаких паспортных YAML и предварительного списка координаторов.
- Настройки доступны в Dashboard «Настройки агентов» и MQTT Device.
  Пустое текстовое значение сбрасывает override. Critical = OFF и
  healer_method = disabled по умолчанию.
- management_host — **дополнительный интерфейс управления**; для USB
  не выводится из serial, даже если это ZigStar-01 в режиме USB.
  Наличие адреса пока не означает успешный Ping.
- Опция метода восстановления — только **декларация намерения**.
  Любая привязка Supervisor App или power switch помечена unverified.
  **Healer в 0.1.10 всегда выключен**, никаких опасных команд
  в App не реализовано. Неподтверждённые связи запрещено
  считать готовыми к управлению.
- Прежний паспортный link_ping_entity не переносится;
  независимая сетевая диагностика будет реализована отдельно.
  `critical` — пользовательская характеристика, не подавляет
  независимые Problem или RPM.
- Recorder: только прежние четыре скаляра; новые switch/select/text
  исключены, значения сохранены в SQLite App.

## Пассивное дерево Zigbee2MQTT (0.1.9)

Дерево — инфраструктурное: одна ветка на автоматически обнаруженный
координатор/Zigbee2MQTT. Это не граф Zigbee Mesh.

- Источник: retained MQTT bridge/info после подтверждения сети и её IEEE.
- В SQLite хранится только разрешённый набор полей: тип координатора,
  версия Zigbee2MQTT, firmware revision, USB/TCP endpoint (без credentials),
  IP из явного TCP IP URI, Zigbee channel/PAN, время получения.
- Подробности публикуются только в networks_details (Recorder OFF).
  Исторический набор из четырёх scalar-сенсоров остаётся без изменений.
- При отсутствии bridge/info остаётся unknown; старые metadata после MQTT
  reconnect не выдаются за новый источник.
- TCP не означает PoE; USB не имеет сетевого Ping. Ретейнд-снимок bridge/info
  не доказывает работоспособность координатора или Zigbee радиообмена.
- Supervisor slug, ZigStar model, Critical, power switch и Healer нельзя
  уверенно обнаружить по одному MQTT. Для списка других Supervisor Apps
  требуются расширенные права; в 0.1.9 роль default не меняется.
- Никаких Zigbee-запросов, ручных паспортов и автоматического восстановления.

## Реальный аварийный сценарий, который обязана обнаруживать диагностика

[INCIDENT-001: скрытое зависание Zigbee при `bridge=online`](docs/KNOWN_FAILURE_SCENARIOS.md)
— **не гипотеза, а ранее наблюдавшийся отказ**: Zigbee2MQTT работал,
логов об ошибках не было, Zigbee-устройства переставали отвечать.
RPM относительно индивидуального baseline введён именно для обнаружения
подобной аномалии. Ни Bridge online, ни health, ни Ping не имеют
права автоматически подавлять `mqtt_traffic_low_problem`.

Приёмка: проверять `bridge_offline=OFF` одновременно с устойчивым
`mqtt_traffic_low=ON` без ошибок Z2M. Недостаточная наблюдаемость —
`unknown`; это не основание объявлять сеть исправной.
Healer **не должен** сам выполнять рестарт/PoE по одному RPM без
политики безопасности, подтверждённой привязки и дополнительной диагностики.

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

Минимальная политика для текущей реализации — **четыре** Recorder ON
сущности: `networks`, `devices`, `offline`, `messages_rate_5m`.
Они содержат только числовые states без динамических JSON-атрибутов.
`spammers` и `incidents` пока являются `unavailable`-заглушками,
поэтому не участвуют в записи до реализации соответствующих движков.

Важная особенность фильтра HA Recorder:
`include.entities` содержит точные четыре entity IDs, тогда как
`exclude.entity_globs` исключает весь префикс Zigbee Monitor
для `sensor`, `binary_sensor`, `button`, `event`. При таком
комбинированном фильтре точные `include.entities` имеют приоритет над
`exclude.entity_globs`, что позволяет записывать только согласованные
четыре метрики продукта, а остальную конфигурацию Recorder не заменять.
Проверить **фактически объединённую** site-конфигурацию особенно важно,
если другие пакеты также задают include/exclude filters.

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

## Problems Engine · независимые признаки по сети (0.1.8)

Автообнаруженные Zigbee2MQTT формируют **три диагностических**
`binary_sensor` с `device_class: problem`, `entity_category: diagnostic`:

| ID в MQTT Discovery | Значение ON |
|---|---|
| `<network_id>_bridge_offline_problem` | Z2M подтвердил `bridge/state=offline` |
| `<network_id>_devices_offline_problem` | Есть хотя бы одно подтверждённое Offline-устройство при живом Z2M |
| `<network_id>_mqtt_traffic_low_problem` | Устойчивое снижение RPM относительно порога |

**ON** — подтверждён именно диагностический признак, не поломка
координатора. **OFF** — при полном достоверном покрытии. Если источник
неизвестен, флаг `unavailable` по отдельному validity topic.
`device_offline` и `bridge_offline` — независимые сущности; падение
Z2M не объявляет автоматическое восстановление каждого устройства.

Агрегатор: `sensor.dh_zigbee_monitor_app_problems`. Числовой state —
число подтверждённых ON, только достоверный ноль; UI-атрибуты
`active`, `unknown`, `severity`, `coverage_complete`. Состояние
и `active` обновляются **немедленно** при смене подтверждённого
binary-флага, не по частоте Recorder. Текущий пакет Recorder исключает
все эти diagnostic entities.

К каждому автоматически обнаруженному Z2M добавляются в Home Assistant
`switch.dh_zigbee_monitor_app_<network_id>_rpm_auto` (автоматический
порог, по умолчанию ON) и
`number.dh_zigbee_monitor_app_<network_id>_rpm_threshold`
(ручной порог, 1…10000 RPM, стандартное значение 10).
Настройки сохраняются в SQLite и применяются без рестарта.

Алгоритм:
- MQTT-пакеты считаются постоянно; по минутам — локальная SQLite, без
  Recorder на каждую сеть.
- Ручной порог работает после прогрева 10 мин; автоматический после
  65 мин непрерывного наблюдения и при достаточной исторической
  активности (минимум 20 активных минут за прежние 60 и среднее >=4 RPM).
- В автоматическом режиме порог 25% от среднего baseline, чтобы
  детектировать **резкое падение**, а не нормальные колебания.
  На время подтверждённой проблемы порог замораживается.
- Устойчиво низкий RPM в течение 5 мин → ON; восстановление >=130%
  порога в течение 2 мин → OFF. До достаточной истории — unavailable.
- Перезапуск App/MQTT очищает временные окна; свежие показатели не
  выдаются за данные непрерывного наблюдения. Новые настройки в HA
  не создают ложных transient событий.
- Сетевой RPM подтверждает лишь **аномалию активности**. Он не доказывает,
  что радиоотсек координатора завис. Активные пробы ZigStar-01,
  health_check, ICMP/TCP и восстановление PoE пока не включены.

События `problem_started`, `problem_recovered` публикуются **только для
аномалии RPM** на старый
topic `DigitalHouses/Global/dh_zigbee_monitor_app/event`
после изменения retained-состояний. Отдельно продолжают публиковаться
события availability/bridge, поэтому HA-автоматизации могут выбирать
типы событий без удвоения уведомлений.

UI:
- `examples/lovelace/dh_zigbee_monitor_app_problems_card_ru.yaml` — самостоятельная
  Mushroom-карточка в стиле PVE Agent;
- полный Dashboard — сводная таблица всех сетей с RPM и
  auto-entities для настройки порогов. Для auto-entities нужна
  установленная frontend-карточка HACS (`custom:auto-entities`).
- Статусная карточка App остаётся **строго о самом приложении**,
  никакие прикладные проблемы туда не попадают.

## Инциденты, подтверждённые Zigbee2MQTT · SQLite (0.1.7)

Инциденты — отдельный backend-продуктовый показатель, не часть
унифицированной статусной карточки Zigbee Monitor App. История хранится в
`/data/activity.sqlite3`, **не в Recorder** и без записи каждого MQTT
пакета. Две подтверждённые категории:

- `device_offline`: Zigbee2MQTT публикует offline **при живом bridge**;
- `zigbee2mqtt_offline`: авторитетный `bridge/state=offline`.

Идентификаторы объектов: сеть — постоянный `network_id` координатора
(IEEE), устройство — `network_id + IEEE`, а не friendly_name.
На первое подтверждение создаётся ровно один активный инцидент;
повторные availability не плодят записи. При восстановлении он
закрывается, а запись остаётся в SQLite.

- В живом переходе `online → offline` точно фиксируется `started_at`.
- Если после запуска приходит retained `offline`, начало
  **неизвестно**: `started_at=null`, но `first_observed_at` реально.
- Восстановление `offline → online` закрывает инцидент с `resolved_at`;
  длительность публикуется только при известном начале.
- После перезапуска/разрыва MQTT retained `online` закрывает старую
  запись как `resolution_source=reconciliation`, но не создаёт
  дополнительное transient событие; точное время фактического
  восстановления при этом может быть раньше времени сверки.
- Когда bridge offline, нельзя выдавать массовые инциденты устройств:
  device availability временно перестаёт быть достоверной. Ранее
  открытые device incident записи не удаляются как «восстановленные»;
  после возвращения источника требуется подтверждение Z2M.

`sensor.dh_zigbee_monitor_app_incidents`: активные подтверждённые
инциденты; **нулевое значение** допустимо только при полной наблюдаемости
bridge и availability всех устройств; иначе `unavailable`, если
подтверждённых проблем нет. Положительное число при неполном
покрытии — нижняя граница; это указано в details.

`sensor.dh_zigbee_monitor_app_incidents_details`: текущий список
`incidents` (до 40), `total`, `truncated`, `observation_complete`
и `recent_resolved` (до 20). Recorder OFF; после восстановления
история видна в Dashboard без пустого исторического HA-графика.
SQLite историю не обрезаем без согласованной политики retention.

Не пытаемся распознавать загруженность CPU, MQTT delivery latency или
«зависание при bridge online» из отсутствия сообщений от батарейных
датчиков. Это отдельная задача после диагностики доступного
health/metrics источника.

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

Статусная карточка Zigbee Monitor — **строго состояние самого App**.
Она отображает только:
- фактическую установленную версию App в заголовке;
- `idle` → «Приложение запущено» при доступном MQTT status sensor;
- `running` → действие и таймер `мм:сс`;
- `success` → реальный результат `refresh/check` и измеренную длительность;
- `error` → ошибку операции (не замаскирована благополучным состоянием сети);
- недоступный `sensor.dh_zigbee_monitor_app_card` → «Нет связи с приложением»;
- реальный процесс установки Supervisor и подтверждённый им процент.

**Запрещено** смешивать состояние App с прикладными данными: числом
устройств, Zigbee2MQTT online/offline, unknown availability, инцидентами,
MQTT-трафиком, списком Offline или информацией о наличии GitHub-релиза.
Для каждого из этих показателей есть отдельная карточка или сенсор.

Кнопки управления App остаются по стандарту:
«Обновить» / «Версия» / «Новая версия» / «Перезапуск».
Кнопка установки, как и прежде, появляется **только** при
`update.digitalhouses_zigbee_monitor_app_update = on`.
Новый GitHub Release без Supervisor update не меняет статусную карточку
и не создаёт нефункциональную кнопку. Результат `check` показывает
«Версия проверена», но не превращается в статус сети или уведомление о
релизе; точный release flag остаётся в отдельной App-сущности.

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
- Anomaly / spam detection is not implemented yet; confirmed Zigbee2MQTT
  source/device outage incident engine is included as of 0.1.7.
- End-to-end tests against a real HAOS installation and Recorder are required
  before declaring production acceptance.
