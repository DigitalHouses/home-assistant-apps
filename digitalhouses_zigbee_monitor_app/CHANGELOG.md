# Changelog

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
