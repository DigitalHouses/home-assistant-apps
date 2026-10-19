# Changelog

## 0.1.12

- Fix Supervisor own-App Options autofill under `hassio_role: default`:
  `/addons/self/options/validate` is denied by the Supervisor security
  middleware (403); `POST /addons/self/options` already validates the options
  against the App schema and is permitted. Remove inaccessible double-validation.
- Regression test verifies one allowed POST without privilege escalation.
  Both `coordinators` and `repeaters` remain optional; Healer remains OFF.

## 0.1.11

- Вместо 0.1.10 MQTT agent controls — два независимых декларативных
  Supervisor App Options списка `coordinators` и `repeaters`. Оба по
  умолчанию пустые; отсутствие описаний не блокирует запуск.
- Читаем свои Options через Supervisor API (default role); подтверждённые
  IEEE автоматически дописываются один раз в собственный конфиг,
  существующие пользовательские поля никогда не перезаписываются.
- Только уверенно распознанные выделенные репитеры из Router inventory;
  прочие Router (розетки, лампы) остаются только в обычном инвентаре.
  Ручное добавление репитера по IEEE поддерживается.
- При первом автоматическом добавлении координатора безопасно переносим
  ранее введённые поля 0.1.10 из SQLite. После миграции пользовательская
  конфигурация принадлежит исключительно App Options.
- ICMP Ping выполняется только по явно указанному management_ip или IP
  из официального TCP endpoint координатора; USB сам IP не получает.
  Неответ/невалидный адрес — ❓; реальный ответ — ✅. Ping сам по себе
  не является Zigbee Problem.
- Исходное ASCII-дерево сохранено, в нём добавлены поля проверки IP,
  независимая ветка репитеров и статус неактивных привязок.
- Healer, рестарты Zigbee2MQTT и управление PoE по-прежнему OFF.
  Recorder: прежние четыре скалярных сенсора; repeater details исключены.

## 0.1.10

- Беспаспортный реестр агентов: per-network пользовательские поля в SQLite,
  стабильная привязка к автоматически обнаруженному network_id / IEEE.
  Редактирование через MQTT Discovery HA UI: имя, Critical,
  модель оборудования, адрес управления, будущий метод восстановления,
  Supervisor App slug и PoE power switch.
- Никаких конфигурационных YAML паспортов и ручного списка сетей.
  Автообнаруженные IEEE/Bridge/USB/TCP/RPM остаются источником истины.
  ZigStar hardware model и PoE не угадываются по Zigbee adapter.
- Невалидные и retained команды настроек отклоняются; отдельные
  сети изолированы; сброс строковых полей — пустое значение.
- Привязки Supervisor и выключателя явно unverified, Healer всегда OFF:
  нет права рестарта, запросов к Z2M и управления PoE.
- Dashboard сохраняет исходное рабочее ASCII-дерево; добавлена только
  информация о policy и панель редактирования связей.
- Новые диагностические switch/select/text исключаются из Recorder.
  Четыре исторических скаляра не изменены.

## 0.1.9

- Автоматическое дерево Zigbee2MQTT из обнаруженных MQTT-сетей, не Zigbee Mesh.
  Без паспортов, новых Recorder сущностей и глобального FSM.
- Пассивный bridge/info: IEEE, координатор, Zigbee firmware revision, Z2M
  version, USB/TCP endpoint, IP только при явном TCP IP, channel/PAN.
  Только allowlist в SQLite, без MQTT-паролей и network key.
- networks_details: infrastructure, флаг получения info в MQTT-сессии,
  раздельные active/unknown reasons для каждой сети.
- Supervisor slug, ZigStar, PoE, Critical и Healer не угадываются.
  Без расширения роли Supervisor (default).
- Refresh перечитывает также retained bridge/info, но его успешность от
  наличия необязательных инфраструктурных данных не зависит.
- Без Zigbee-команд, ping и Auto-Healer.

## 0.1.8

- Problems Engine по контракту `dh_pve_agent`: независимые подтверждённые
  `device_class: problem` по каждому автоматически обнаруженному Z2M:
  `bridge_offline`, `devices_offline`, `mqtt_traffic_low`.
- Один агрегатор `sensor.dh_zigbee_monitor_app_problems` с `active`,
  `unknown`, `severity` и `coverage_complete`; нет фиктивного нуля при
  неполных данных. Бинарные статусы и агрегат публикуются при изменении.
- События `problem_started` и `problem_recovered` только для новой
  аномалии RPM; для Offline уже существуют device/zigbee2mqtt события,
  не создаём дубликаты уведомлений. Retained bundle прежде Event.
- Per-network настройки RPM через MQTT Discovery: `switch` автоматического
  порога и `number` ручного (1..10000). Настройки сохраняются в SQLite,
  активируются без рестарта и не требуют паспортов.
- Анализ трафика по минутным SQLite-агрегатам независимо по каждой сети;
  manual: 10-мин прогрев, auto: 65-мин прогрев, достаточная история и
  личный baseline. При недостатке данных статус unknown. Подтверждение
  low RPM 5 мин, восстановление 2 мин с 1.3x гистерезисом; не трактовать
  падение трафика как доказанную неисправность координатора.
- В `networks_details`: total, online, offline, unknown, per-network
  RPM, текущий порог и baseline. Новая Mushroom-карточка проблем.
  Настройки автоматически выведены в Dashboard через auto-entities.
- Регулярная публикация диагностических snapshot не создаёт новых
  Recorder-сущностей: установленный allowlist из четырёх скаляров
  не изменён. Никаких запросов к Zigbee-устройствам и Auto-Healer.

## 0.1.7

- SQLite engine для подтверждённых инцидентов `device_offline` и
  `zigbee2mqtt_offline`, отдельные сети по стабильному coordinator
  `network_id`, устройства по IEEE; история сохраняется после рестарта App.
- На переходе live `online→offline` фиксируем `started_at` и
  `first_observed_at`. Для retained offline при старте сохраняем
  `first_observed_at`, но `started_at=null`: не придумываем начало сбоя.
  Retained recovery после перезапуска закрывает инцидент как reconciliation,
  не выдавая ложное машинное событие.
- Скаляр `incidents` показывает только подтверждённые открытые проблемы:
  положительный lower-bound допустим с неполными статусами; ноль — только
  при полной достоверной availability. Не добавлен в HA Recorder.
- `incidents_details` (Recorder OFF): активные инциденты, причина,
  время первого наблюдения и начала, `recent_resolved` (до 20),
  фактическая длительность, причина восстановления. Источник SQLite.
- При потере `bridge/state` устройства не считаются массово offline.
  Данные availability устройства во время bridge offline игнорируются,
  прежние availability инвалидаются для исключения ложных событий
  после восстановления источника.
- Dashboard: активные + недавние завершённые инциденты. Удалён
  пустой график Recorder по не записываемому `incidents`.
- Статусная карточка App и 4-метрический Recorder-пакет не изменены;
  событие HA `event.dh_zigbee_monitor_app_event` остаётся отдельным
  machine-only contract без локальных получателей уведомлений.

## 0.1.6

- Подтверждённые Zigbee2MQTT offline теперь всегда отображаются в offline_details,
  даже если у других устройств ещё `unknown`; числовой offline = количество
  **подтверждённых** offline (нижняя граница), при 0+unknown сенсор по-прежнему unavailable.
- Разделены device availability и state Zigbee2MQTT bridge. При `bridge/state=offline`
  события массового offline устройств не синтезируются.
- Машинные MQTT Events через HA Device Discovery, `event.dh_zigbee_monitor_app_event`:
  `device_offline`, `device_online`, `zigbee2mqtt_offline`, `zigbee2mqtt_online`.
  Транспорт QoS 1, `retain: false`. Сначала публикуется состояние, затем событие.
- Запуск App, retained replay, повторные MQTT доставки, первичная инициализация
  и восстановление MQTT не создают ложных уведомлений: событие только при подтверждённом
  изменении ранее наблюдавшегося состояния в рабочей сети.
- Пример локальной HA-автоматизации уведомлений: прямой `event.received` →
  `trigger.id` → `choose` → delivery без глобальных посредников.
- Нет Zigbee-запросов, управления устройствами, новых динамических Recorder сущностей.
  Детектировать перегрузку Z2M по одному `bridge/state` невозможно.

## 0.1.5

- Источник истины о питании устройств: retained MQTT `bridge/devices`,
  поля `power_source` и `type`, без ручного ввода или эвристик по имени.
- В `inventory_details` добавлены `power_source`, `power_class`,
  `power_label`, `device_type` и `last_mqtt_message_at` (UTC).
- Последнее MQTT-сообщение определяется только из реальных, не retained и
  не MQTT DUP, публикаций в известных топиках устройств.
- Последняя MQTT-активность записывается в SQLite **пакетом не чаще
  одной записи на устройство за минуту**, совместно с агрегатами, и
  сохраняется при смене имени/перезапуске.
- В Dashboard добавлены столбцы «Питание» и «Последний MQTT (UTC)».
- MQTT activity не объявляется Zigbee RF last_seen, не генерирует Zigbee
  запросы и **не заменяет** подтверждённые Zigbee2MQTT availability.
- Новых HA-сущностей и динамических Recorder-атрибутов нет.

## 0.1.4

- Исправлен ошибочный fail продуктового Refresh при отсутствии
  опциональных MQTT device availability от Zigbee2MQTT.
- Refresh, по стандарту Internet App, успешно завершается после
  получения новых подтверждённых bridge/state и bridge/devices,
  публикации реальной инвентаризации и состояния сети.
- Offline и offline_details остаются unavailable при неизвестной
  availability; фиктивный ноль не публикуется.
- Проверка bridge/inventory выполняется после команды, устаревшее
  состояние не считается успешным Refresh; ошибки и timeout
  различают отсутствие bridge и inventory.
- Regression tests: Zigbee2MQTT availability выключена, частичная
  инвентаризация, неответивший bridge, sticky error и duplicate Refresh.

## 0.1.3

- Инвентаризация MQTT: per-device availability `online/offline/unknown`,
  код и русская причина отсутствия данных, сводные `availability_unknown` и
  `availability_complete`. Данные только в Recorder-excluded `inventory_details`.
- UI: каноническая компактная карточка управления по стандарту PVE Agent,
  встроена также в Dashboard; отдельная таблица доступности устройств.
- Исправлена полнота Manual Refresh: ждём inventory, bridge/state и availability,
  не записываем успешный last_refresh по одному bridge/devices.
- Добавлен диагностический `sensor.dh_zigbee_monitor_app_refresh_state`
  (`idle/updating/error`), не пишется в Recorder.
- Статус успешной операции показывается 5 секунд, затем возвращается в idle;
  ошибка сохраняется до следующей команды.

## 0.1.2

- Исправлен запуск HAOS App: совместимость Alpine `py3-paho-mqtt` 1.x и paho-mqtt 2.x.
- Нормализованы MQTT callbacks `on_connect`/`on_disconnect` для обеих версий.
- Добавлены регрессионные тесты и обязательный smoke-test MQTT-клиента
  внутри собранного Docker-образа с реально установленным Alpine paho.

## 0.1.1

- Automatically discover Zigbee2MQTT instances via coordinator-verified retained
  `bridge/devices` and `bridge/info` MQTT topics (1–3 level base topics).
- Remove required per-network settings from HAOS App configuration.
- Persist coordinator IEEE / stable network ID / current base topic in SQLite;
  rediscover on reconnect and during read-only refresh.
- Preserve existing 0.1.0 manual network IDs as compatibility hints where possible.
- Avoid displaying fictitious network count zero before any network is detected.

## 0.1.0

- Experimental initial release of DigitalHouses Zigbee Monitor App.
- Support multiple independent Zigbee2MQTT base topics and IEEE-based identity.
- Read-only inventory, Z2M availability and retained-aware MQTT activity counting.
- Home Assistant MQTT Discovery with separate Recorder-safe numeric metrics and detailed UI entities.
- SQLite minute aggregation, limited historical rankings (1h / 24h / 7d).
- Supervisor MQTT credentials, standard status card operations and mandatory privacy consent/telemetry.
- Offline transitions/incident notifications and anomaly spam classification are **not yet implemented**;
  their HA entities remain unavailable instead of fabricating zero values.
