# Changelog

## 0.1.20

- Per-network and global four-state infrastructure FSM: BOOTING, HEALTHY,
  DEGRADED, CRITICAL; preserved, recorder-visible entities and transient
  machine events published after retained FSM states.
- Replace graph-only EMA and separate delayed incident input with one 300s
  rolling RPM for live tree, alarms and the recorder-facing numeric sensor.
- MPM below the active threshold degrades immediately and escalates after
  five continuous minutes. Repeater Zigbee offline needs 60 seconds;
  bridge offline is immediately critical. End-device availability stays
  independent of the infrastructure FSM.
- Persist first observed baseline at 30 seconds after BOOTING; use the minimum
  complete HEALTHY hourly rate from the trailing 24 hours thereafter.
  AUTO threshold is integer ceil(baseline/2); MANUAL accepts zero to disable
  the RPM alarm. Existing per-site manual settings are preserved by migration.
- Store minute-level validity/health evidence (no per-MQTT-packet writes),
  expose 168 hourly and seven 24-hour summaries in per-network
  Recorder-excluded details, preserving the 30-day retention policy.
- Update the existing dashboard, tree, trends and sample Recorder allowlist.
  Healer remains OFF; HAOS site configuration is not modified.


## 0.1.19

- Confirmed two TI `ti.router` Zigbee Router repeaters on Ruslan site
  (`0x00124b002e1458f9`, `0x00124b002e0cc5a6`) belong to
  `zigbee2mqtt_1`. Recognize exact `ti.router` model as specialized
  repeater, without classifying every Zigbee Router as one.
- Nest recognized repeaters beneath their **actual discovered** Zigbee2MQTT
  network in the established ASCII tree, deriving membership from
  `bridge/devices` IEEE. Unconfirmed entries remain visible only as
  unassigned, never silently attached to a guessed network.
- Report Zigbee repeater availability independently from inventory presence
  and management IP Ping; unknown remains unknown.
- Preserve existing Supervisor Options, independent offline device card,
  MPM trend sensors, Recorder allowlist and Healer OFF. No new HA entities.

## 0.1.18

- Read-only lookup of Home Assistant Device Registry through the existing
  /homeassistant mount. Only exact MQTT zigbee2mqtt_<IEEE> identifiers are
  accepted; no name matching and no invented navigation links.
- Optional offline_details.devices[*].ha_device_id supports HA Device page links.
  The Recorder-facing offline count remains strictly numeric.
- Dashboard + standalone offline Lovelace card navigate to HA device page on click,
  falling back to ordinary text when the HA registry has no verified match.
- Coordinator/repeater tree, Healer and MQTT metrics remain unchanged.

## 0.1.17

- Добавлен числовой диагностический сенсор
  `sensor.dh_zigbee_monitor_app_<network_id>_rpm_threshold_effective`.
  При ручной настройке сразу отображает заданный порог,
  при автоматической — только фактически вычисленный текущий threshold;
  если он ещё неизвестен, сенсор unavailable, не ложный 0 или
  сохранённый ручной параметр. Порог не пересчитывается в UI.
- Для каждой Z2M добавлен независимый графический датчик
  `sensor.dh_zigbee_monitor_app_<network_id>_rpm_smooth`:
  EMA(15 одноминутных значений, alpha=0.125), один снимок в минуту,
  без динамических MQTT/Recorder-атрибутов. Два графика
  auto-entities за 24 ч и 7 дней используют теперь EMA,
  а не дребезжащие сырые показания.
- Исходный `*_rpm` и реальный RPM в Pulse сохраняются.
  Сглаживание **только для UI**, не участвует в
  `mqtt_traffic_low`, baseline, авариях или Healer.
- В компактном ASCII-дереве координатора отдельная строка
  `Devices: total (online, offline)` с unknown при наличии;
  `Status` показывает только Bridge. Репитеры и общий
  корень сохраняются.
- Удалена заглушка `sensor.dh_zigbee_monitor_app_spammers`
  из MQTT Discovery и карточки сводки. Подсчёт spam/anomalies
  ещё не реализован; MQTT рейтинги по окнам 1ч/24ч/7д сохранены.
- Recorder фильтр дополнен строго двумя семействами
  `*_rpm_smooth`, `*_rpm_threshold_effective`, не включая
  JSON-диагностику. Для истории в HA необходимо синхронизировать
  пример Recorder package.
- Доступность конфигурации Zigbee2MQTT подтверждается,
  но её содержимое приложение **ещё не читает и не разбирает**.
  Supervisor App settings/slug автоматически не извлекаются.

## 0.1.16

- Независимая RPM-временная серия для каждого автоматически
  обнаруженного экземпляра Zigbee2MQTT: MQTT Discovery
  `sensor.dh_zigbee_monitor_app_<network_id>_rpm`.
  Идентификатор стабилен по `network_id`, имя соответствует сети,
  состояние только число с единицей `messages/min` и
  `state_class: measurement`; динамических JSON-атрибутов нет.
- Публикация не чаще одного раза в минуту на сеть (при изменении
  значения); быстрое обновление Pulse в дереве остаётся как было.
  При отсутствии проверенного online Bridge серия становится
  unavailable, а не записывает фиктивный ноль.
- Два динамических графика `custom:auto-entities` + штатный
  `history-graph`: все сети за 24 часа и за 7 дней. Новые Z2M
  добавляются без правки Lovelace. Есть отдельный переносимый YAML.
- Recorder разрешает только `sensor.dh_zigbee_monitor_app_*_rpm`
  поверх четырёх предыдущих скалярных сенсоров; полные JSON,
  события и прочая диагностика по-прежнему исключены.
  После установки пользователю необходимо обновить локальный
  HA Recorder package: GitHub не обновляет /config автоматически.
- Старое компактное дерево, RPM alarm baseline, Healer и другие
  механизмы приложения не менялись.

## 0.1.15

- RPM в дереве виден сразу после получения `bridge/state=online`:
  сначала `0.0` как предварительное измерение, затем скорость
  поступающих **новых не-retained MQTT сообщений устройств**.
- Для старта используется до 300 секунд текущей сессии; первые
  10 секунд знаменатель ограничен для защиты от скачков оценки.
  Окно данных агрегировано по секундам (ограниченная память).
  Публикация не чаще одного раза в 10 секунд; события не вызывают
  отдельный MQTT-поток обновлений для каждого сообщения.
- Новое поле в `networks_details`: `rpm_phase=warming_up` пока
  данные предварительные; `measured` после штатного прогрева.
  Дерево при прогреве выводит короткую пометку `· прогрев`.
- **Независимая защита от ложных инцидентов:** `mqtt_traffic_low`,
  baseline и 5-минутный Recorder-сенсор `messages_rate_5m`
  НЕ используют предварительный RPM; их прогрев, гистерезис
  и требования к полноте данных не меняются.
- ASCII-дерево остаётся компактным (6 строк/координатор,
  5 строк/репитер), Healer OFF, доступы к Supervisor неизменны.

## 0.1.14

- Read-only self-check of the `/homeassistant` mount and the fixed path
  `/homeassistant/zigbee2mqtt/configuration.yaml`, without reading the
  file contents. Reports only mounted, directory and file openability.
- New MQTT Discovery diagnostic
  `sensor.dh_zigbee_monitor_app_config_access` (Recorder excluded):
  state `ready`, `mount_missing`, `directory_missing`,
  `file_missing` or `file_unreadable`, and safe boolean-like attributes.
- Check on startup and every minute. Reject symlinked target, unknown
  diagnostic values and unexpected secret-like fields.
- App configuration, Zigbee control, Healer, RPM and **entire Lovelace
  Dashboard including the original ASCII tree** unchanged.
- This does NOT parse Zigbee2MQTT YAML or discover App Supervisor slugs.

## 0.1.13

- Конфигурация HA доступна приложению по `/homeassistant` **только для
  чтения** через Supervisor mapping `homeassistant_config`; никакой
  записи в файлы HA или повышения роли `hassio_role: default`.
- Это **подготовка источника данных** для будущего сопоставления
  Zigbee2MQTT с установленными Apps. В версии 0.1.13 **ещё нет**
  чтения или разбора `/homeassistant/zigbee2mqtt/configuration.yaml`;
  координаторы и поля `addon_slug` не изменяются автоматически.
- Файлы конфигурации HA могут содержать секреты. Запрещено
  публиковать их содержимое в MQTT, журналах и телеметрии.
- Dashboard ASCII-дерево, существующие настройки, RPM, Healer и
  управление Zigbee/PoE **не изменялись**.

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
