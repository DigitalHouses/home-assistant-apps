# DigitalHouses Sync App — v0.1.0

**Первый активный кандидат (исходники в Draft PR #499; образ GHCR ещё не опубликован).**

DH Sync — локальное HAOS App для доставки утверждённых YAML в единую панель DigitalHouses. App не обновляет исполняемый код продуктов и не требует CORE сервера, Ansible или нового MQTT namespace.

## Сейчас доступно в коде

- Штатное MQTT inventory существующих Apps/Agents: offline не удаляет установленный продукт.
- Discovery Contract v1: получает из MQTT сведения о версии и GitHub-репозитории продукта, принимает **только** организацию DigitalHouses и показывает найденные источники без права установки.
- Admin-only Ingress (внутренний порт 8099) с просмотром текущих версий и трёх канонических русских views.
- Три закреплённых ресурса: Proxmox и Электропитание из PR #502, Plex из merged PR #500.
- Строгое определение уже установленного файла, конфликта, несовместимого агента и дублирующего view path.
- Только по согласованному Apply: SHA-checked backup, атомарная замена существующего YAML, HA config check, сверка загруженного dashboard и доступный откат.
- App configuration **allow_changes: false по умолчанию**. Даже при включении требуется подтверждение в панели.
- Доступ к HA API через Supervisor token; не надо создавать пользовательские long-lived tokens.

## Ограничения

На пилоте CORE панель digital-houses и views/ должны существовать заранее. Файлы PVE/UPS обновляются в своих путях; Plex 12_plex.yaml уже установлен и не переписывается, если содержимое совпадает.
Recorder, HA packages, Storage dashboards, configuration.yaml, HACS и исполняемые агенты v0.1 не меняет. Автоматического фонового применения и HA restart нет.
Если пользователь редактировал исходный YAML, обновление блокируется без silent overwrite.

Исходник PVE остаётся Draft PR #502; перед публикацией стабильного App нужно принять PVE PR и заменить SHA на подтверждённый merge commit.

Подробности: [контракт MQTT-репозиториев](docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md), [версия и пилот](docs/FIRST_VERSION.md), [контракт продуктов](docs/PRODUCT_REQUIREMENTS.md), [архитектура](docs/ARCHITECTURE.md), [Plex Storage prototype](docs/STORAGE_MIGRATION.md), [передача разработчикам](docs/DEVELOPER_HANDOFF_RU.md).
