# DH Zigbee Monitor — план работ (UI-first)

Статус: проектирование. Этапы не подразумевают готовность App к установке.

## Этап 1 · UI и договор о данных

- Создать визуальный Dashboard `sections` с **явно демонстрационными данными**.
- Утвердить русские заголовки, карточки, навигацию, диапазоны ТОП.
- Утвердить каждый `unique_id`, state/attributes/topics, срок жизни данных и Recorder ON/OFF.
- Протестировать по образцу унифицированной статусной карточки DH (шапка обязательна).
- Никакой аналитики в Lovelace или HA Jinja.

## Этап 2 · Каркас HAOS App и репозиторный контракт

- Продукт `digitalhouses_zigbee_monitor_app`, `type = haos_addon`.
- Регистрация продукта в `digitalhouses-stats/digitalhouses_stats/product_registry.json`,
  расширение валидаторов и выделенный CI job.
- `config.yaml`, `Dockerfile`, `rootfs/run.sh`, `rootfs/app/`,
  `translations/ru.yaml`, `translations/en.yaml`, `icon.png`, `logo.png`,
  `CHANGELOG.md`, `DOCS.md`, `tests/`, `examples/lovelace/`, `examples/packages/`.
- Release-версия из `config.yaml`, стандартная статусная карточка, MQTT
  Discovery, runtime `Version` и `Started at`.
- Supervisor MQTT Service; согласие на телеметрию и выпуск по действующим
  стандартам, без обхода политики.
- До приёмки не заявлять, что App готов к установке.

## Этап 3 · Сбор и идентичность

- Поддержка нескольких `base_topic` с устойчивыми `network_id`.
- Инвентаризация `bridge/devices`, IEEE, обновление связей с topic/friendly_name.
- Тесты переименований, перемещения между сетями, дублированных topic,
  исчезновения/возвращения устройства.
- Корректность обработки MQTT retained/reconnect, ограничения очередей.

## Этап 4 · Offline и инциденты

- Проверка Zigbee2MQTT availability; отдельное состояние источника.
- Сохранённые переходы, подтверждение offline/recovery, массовые сбои,
  отсутствие ложных инцидентов в startup grace.
- Машинные события, локальный пакет уведомлений; без паспорта и auto-healing.
- Тесты длительных отказов и восстановления после рестартов.

## Этап 5 · Хит-парад и SQLite

- Счётчики реальных MQTT-публикаций и агрегация без хранения сырого потока.
- ТОП за 1ч/24ч/7д, сеть/модель/производитель.
- Определение аномальности относительно baseline с состоянием insufficient_data.
- SQLite `/data`, retention/backup/restore acceptance.

## Этап 6 · Recorder и HAOS acceptance

- Исторические scalar sensors отдельно от non-Recorder JSON details.
- Реальная проверка HA Recorder (24ч): обновления, объём БД, exclude.
- Проверка MQTT Discovery, availability и отсутствие orphan entities.
- Тесты schema, restart, source loss, dedup, events, immutable release;
  CI green до merge, производственная поставка только immutable GHCR.
