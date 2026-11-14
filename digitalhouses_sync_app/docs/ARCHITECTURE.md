# DigitalHouses Sync — текущая архитектура

**Источник правил размещения YAML:** [DH Sync Resources Standard](../../../docs/standards/DH_SYNC_RESOURCES_STANDARD.md).

- Продукты обнаруживаются по существующим MQTT `/sync` metadata.
- Единственное правило допуска Git-источника: владелец GitHub `DigitalHouses`.
- DH Sync читает публичный Git (общий кэш), без GitHub REST API, токенов и платных сервисов.
- При обнаружении и затем периодически синхронизирует **только** опубликованные `dashboards/ru/*.yaml`, `packages/common/*.yaml` и `packages/locales/ru/*.yaml`.
- `examples/` не участвует; отсутствие каталога ресурсов нормально.
- Сравнение по Lovelace `path` и YAML package key. При отличии — backup и атомарная замена, без пользовательского подтверждения.
- Конфликты имён или ключей не исправляются наугад. Не трогает `.storage`, не удаляет файлы после исчезновения продукта из MQTT или GitHub.
- Не обновляет код Apps/Agents и не перезапускает Home Assistant. Изменения HA packages могут потребовать обычного перезапуска HA.

Реализация: `rootfs/app/auto_sync.py` и `rootfs/app/git_source.py`.

MQTT-контракт: [DH Sync Discovery Contract v1](DH_SYNC_DISCOVERY_CONTRACT_V1.md).
