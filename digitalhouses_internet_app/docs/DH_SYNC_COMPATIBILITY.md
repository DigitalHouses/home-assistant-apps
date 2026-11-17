# Internet App — контракт с DH Sync

**Версия App:** 0.1.25. **Стандарт:** DH Sync Discovery Contract v1 и DH Sync Resources Standard.

## Публикация MQTT

- Топик: `DigitalHouses/Global/digitalhouses_internet_app/sync`.
- QoS: **1**. Retain: **true**.
- Публикация: на каждом успешном MQTT connect/reconnect (без отдельного heartbeat).
- Версия берётся из `APP_VERSION`, то есть из фактически установленной версии App, а не из Git-ревизии файлов YAML.

```json
{
  "schema": 1,
  "product_id": "digitalhouses_internet_app",
  "type": "app",
  "version": "0.1.25",
  "repository": "https://github.com/DigitalHouses/home-assistant-apps",
  "product_path": "digitalhouses_internet_app",
  "dashboard": "dh-system"
}
```

## Канонические ресурсы в репозитории

| Тип | Путь | Идентификатор |
| --- | --- | --- |
| View | `dashboards/ru/13_internet.yaml` | `path: internet` |
| Recorder package | `packages/common/dh_internet_app_global_package.yaml` | `dh_internet_app_global_package` |
| Уведомления RU | `packages/locales/ru/dh_internet_app_notification_local_package.yaml` | `dh_internet_app_notification_local_package` |

DH Sync размещает View на панели `/dh-system/`; создаёт её при необходимости и обновляет YAML при изменении файлов GitHub `main`. Пакеты определяются по верхнеуровневому ключу и не дублируются на другом пути. Ничего из `examples/` DH Sync не устанавливает.

## Обратная совместимость

- Текущий MQTT runtime namespace остаётся `DigitalHouses/Global/dh_internet_app/`.
- Старые MQTT Discovery device/unique-id/`entity_id` сохраняются.
- Данные в `/data`, Recorder history, recovery, Speedtest, telemetry consent и управление App остаются без изменений.
- Уведомления используют прежние `event.dh_internet_app_event` и `persistent_notification.create` — никаких локальных сервисов доставки.
- DH Sync не обновляет контейнер Internet App, а Internet App не записывает файлы на стороне HA.

**Примечание:** текущий контракт App требует `telemetry_enabled=true` для запуска runtime. Если App остановлен из-за отсутствия согласия, retained `/sync` от предыдущего запуска может оставаться у брокера; DH Sync трактует его как источник опубликованных YAML, а не признак состояния App.
