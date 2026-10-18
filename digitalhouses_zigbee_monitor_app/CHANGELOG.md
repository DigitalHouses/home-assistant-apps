# Changelog

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
