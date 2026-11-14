# DH Sync v0.1.0 — первый безопасный пилот (только MQTT-каталог)

**Статус:** PR #499 готов к проверке и автоматическому выпуску, первый GHCR образ ещё не опубликован, реальное Ingress тестирование CORE ещё не проведено.

## 1. Что входит в опубликованный App v0.1.0

- Через Supervisor `mqtt:need` подключается к уже существующему брокеру.
- Читает retained JSON `DigitalHouses/Global/+/sync` и `DigitalHouses/Global/+/+/sync` и существующий product-level availability.
- Строго проверяет владельца GitHub `DigitalHouses`, topic, schema, product_id и product_path.
- Показывает в admin-only Ingress список продуктов: ID, версия, instance ID, Online/Offline/Unknown, GitHub repo/path.
- Хранит принятые MQTT-метаданные в `/data/product_sources.json`, не удаляет при offline.
- Сам публикует `digitalhouses_sync_app` MQTT diagnostics и `/sync`.

## 2. Что НЕ входит в исполняемое приложение

- Любая установка или замена YAML, Lovelace views/packages, Recorder, Storage.
- Доступ к Home Assistant Core REST/WebSocket API, Supervisor control, HA config mount.
- GitHub скачивание файлов по MQTT URL, установка обновлений агентов или HACS.
- Формы Apply/Rollback, автоматический перезапуск HA, внешняя телеметрия.

Дизайн и тесты транзакционного YAML SyncEngine сохранены **только в кодовой базе** для следующей версии; штатный runtime `app.py` не импортирует ни `SyncEngine`, ни `CoreAPI`, ни панели Apply/Rollback. Его HTTP сервер поддерживает GET; любой POST возвращает 405.

**Это намеренный первый этап:** CORE MQTT уже показал PVE Agent 0.5.89 и Plex Agent 0.8.18, но канонические YAML ещё ограничены версиями PVE 0.5.88 и Plex 0.8.17. Преждевременно вводить Apply нельзя.

## 3. Пилот CORE

После выпуска через существующий DigitalHouses Release Policy и публикации immutable GHCR:

1. Установить App v0.1.0 только на CORE HAOS.
2. Открыть admin-only Ingress; убедиться, что присутствуют PVE v0.5.89, Plex v0.8.18 и DH Sync v0.1.0, с верным GitHub `DigitalHouses`.
3. Проверить Online/Offline/Unknown отдельно от наличия retained /sync.
4. Перезапустить только DH Sync, убедиться, что source metadata остаётся (retained + /data).
5. Убедиться, что в UI нет кнопок изменения, HTTP POST возвращает 405, и не меняются `/config`, `.storage`, Recorder, YAML views и рабочие агенты.
6. Только после подтверждения пилота планировать следующую версию с управляемыми YAML.

## 4. Release gate

- Реестр релизов: `digitalhouses_sync_app` release `title: DigitalHouses Sync App`, `version_source: haos_config`, baseline `0.0.0`.
- Версия `0.1.0` в `config.yaml` и заголовке changelog.
- `telemetry_allowed: false` не меняется.
- PR отмечен Ready после проверки read-only HTTP surface, исключения HA API/config mount и полного 14/14 CI.
- Автоматический workflow после Merge создаст `digitalhouses_sync_app-v0.1.0`, GHCR image + digest; ручные теги и floating `latest` запрещены.

## 5. Поздняя фаза — YAML доставка

Только после merge PVE PR #502 и отдельного продукта Plex compatibility review: обновить точные диапазоны совместимости до протестированных Agent versions, закрепить immutable Git commit каждого YAML, проверить права и Core API, затем разрешить отдельный opt-in Apply/Rollback flow. **Это не относится к доступному runtime v0.1.0.**
