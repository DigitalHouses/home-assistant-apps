# Готовое сообщение для чатов разработчиков Apps/Agents

**Задача: подготовить свой продукт к DH Sync v1.**

Прочитай единый контракт:
https://github.com/DigitalHouses/home-assistant-apps/blob/feature/digitalhouses-sync-app-contract/digitalhouses_sync_app/docs/PRODUCT_REQUIREMENTS.md

И обязательные стандарты в `docs/standards/`, особенно `DIGITALHOUSES_APP_STANDARD.md`, `PRODUCT_NAMING_STANDARD.md`, `HA_PACKAGE_VERSIONING_STANDARD.md`, `REPOSITORY_GOVERNANCE.md`.

Сначала сделай аудит **своего** продукта в `DigitalHouses/home-assistant-apps`:
- Реальный canonical product ID; существующие availability, MQTT Discovery, Version/Started-at sensors и uninstall semantics.
- Какие dashboards/packages реально существуют и в какой версии; какие локальные пользовательские изменения/уведомления критичны.
- Какие resources можно сделать каноническими без изменения `entity_id`, Recorder, управления и UX.
- Какие диапазоны совместимости реально подтверждены, где пока нет доказательств.

Затем в отдельном PR своего продукта:
1. Размести canonical `dashboards/<locale>/*.yaml` и `packages/common/`, `packages/locales/<locale>/` по применимости;
2. Приведи headers, версии, метаданные совместимости и документацию к контракту;
3. Исправь **только реальные gaps** MQTT availability/diagnostics, сохраняя выпущенные публичные идентификаторы;
4. Добавь/обнови regression tests и запусти CI;
5. Не меняй другие продукты, DH Sync, Ansible, рабочие HA, и не запускай массовые обновления.

Верни итог: PR/commit, YAML paths/versions, MQTT availability и diagnostic entity IDs, протестированные версии, тесты, gaps.

**Пилот PVE:** брать только подтверждённые YAML v3, не старые `examples/`. Два views Proxmox + Электропитание должны сохраниться даже без настроенного UPS.

