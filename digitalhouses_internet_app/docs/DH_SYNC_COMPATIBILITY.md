# Internet App — контракт с DH Sync 0.6.0

**Версия контракта App:** с 0.1.26. **Действующий стандарт:** [DH Sync Developer Standard](../../docs/standards/DH_SYNC_DEVELOPER_STANDARD.md).

## Публикация MQTT

- Топик: `DigitalHouses/Global/digitalhouses_internet_app/sync`.
- QoS: **1**. Retain: **true**.
- Публикация: на каждом успешном MQTT connect/reconnect через существующий клиент, без отдельного heartbeat и таймера.
- Версия берётся из `APP_VERSION` запущенного App, независимо от ревизий YAML в GitHub.

```json
{
  "schema": 1,
  "product_id": "digitalhouses_internet_app",
  "type": "app",
  "version": "0.1.26",
  "repository": "https://github.com/DigitalHouses/home-assistant-apps",
  "product_path": "digitalhouses_internet_app"
}
```

В `/sync` **нет** имени Dashboard, списка Views, порядка вкладок или настроек доступа.
Старые retained-сообщения с полем `dashboard` DH Sync 0.6.0 игнорирует в этой части; миграция не требуется. При штатном отключении App retained `/sync` не удаляется. Статус `availability` публикуется отдельно и не управляет реестром DH Sync.

## Канонические ресурсы в репозитории

| Тип | Путь | Идентификатор |
| --- | --- | --- |
| View | `dashboards/ru/13_internet.yaml` | `path: internet` |
| Recorder package | `packages/common/dh_internet_app_global_package.yaml` | `dh_internet_app_global_package` |
| View EN (ручной импорт) | `dashboards/en/13_internet.yaml` | `path: internet` |
| Уведомления EN (ручной импорт) | `packages/locales/en/dh_internet_app_notification_local_package.yaml` | `dh_internet_app_notification_local_package` |
| Уведомления RU | `packages/locales/ru/dh_internet_app_notification_local_package.yaml` | `dh_internet_app_notification_local_package` |

DH Sync читает эти YAML из основной ветки GitHub. Internet App публикует только **самостоятельную View** с постоянным `path: internet`. Название Dashboard, состав и порядок вкладок, иконки размещения и права доступа определяются исключительно файлами `digitalhouses_sync_app/dashboards/*.yaml`; одна View может быть включена в несколько панелей.

Чтобы разместить View, передайте в профильный чат DH Sync пару: `product_id=digitalhouses_internet_app`, `path=internet`. Internet App не редактирует файлы панелей. Файлы из `examples/` не устанавливаются DH Sync. Изменения канонических YAML не требуют выпуска нового контейнера App.

## Сохранение контрактов Internet App

- MQTT runtime namespace остаётся `DigitalHouses/Global/dh_internet_app/`.
- MQTT Discovery, device/unique-id/`entity_id` сохраняются.
- Данные в `/data`, Recorder history, recovery, Speedtest, telemetry consent и управление App остаются без изменений.
- Уведомления продолжают использовать `event.dh_internet_app_event` и `persistent_notification.create`.
- DH Sync не обновляет контейнер Internet App, а Internet App не записывает YAML на стороне Home Assistant.

**Примечание:** App требует `telemetry_enabled=true` для запуска runtime. Если App не запущен, ранее опубликованный retained `/sync` может сохраняться на MQTT-брокере; DH Sync использует его как объявление ресурса, а не как показатель состояния App.

Текущая реализация DH Sync выбирает RU. Английские ресурсы можно установить вручную вместо русских, не одновременно.
