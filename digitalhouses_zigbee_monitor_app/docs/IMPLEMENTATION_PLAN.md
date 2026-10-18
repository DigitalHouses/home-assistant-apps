# DH Zigbee Monitor — план работ (UI-first)

Статус: реализация начата. Модуль `rootfs/app/zigbee_monitor` реализует
первое независимое ядро: конфигурации нескольких сетей, inventory по IEEE,
сопоставление MQTT device topics, сбор минутных счётчиков и SQLite store.
Этот этап **ещё не запускается как Home Assistant App**: runtime MQTT,
Supervisor config, Discovery и релизные файлы будут в следующем этапе.

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

## Выполнено · старт ядра (feature/zigbee-monitor-multi-network-core)

- `rootfs/app/zigbee_monitor/core.py`: чистый Z2M MQTT классификатор,
  явные immutable `network_id`, без зависимости от HA entity IDs.
- `rootfs/app/zigbee_monitor/storage.py`: SQLite под `/data` в будущем runtime.
  Сохраняет текущую идентичность устройства и счётчики по UTC минутам,
  допускает rename/перенос без потери накопленной истории.
- `tests/test_core.py`, `tests/test_storage.py`: регрессии на идентичность,
  retained replay, bridge/devices, availability, неверные payload и SQLite.
- `Validate repository` запускает тесты ядра в CI.

Ограничения текущего этапа: в репозитории нет HAOS запуска, MQTT transport,
MQTT Discovery и подсистем инцидентов/spam classification. Счётчики сообщения
не означают реального Zigbee RF packet count. Ни один существующий HA
Recorder-показатель пока не публикуется.

## Реализовано · MQTT transport и read-only HA publisher (следующий PR)

- `rootfs/app/app.py`: MQTT-клиент с Supervisor-provided credentials из
  переменных среды, LWT, подписка на конфигурируемые Zigbee2MQTT base topics,
  переподключение, сигнал завершения и read-only release-check.
- `rootfs/app/zigbee_monitor/discovery.py`: MQTT Device Discovery с постоянными
  `unique_id`, отдельными состояниями validity для каждого результата,
  историческими скалярными сенсорами без динамических атрибутов и отдельными
  сущностями UI details.
- `rootfs/app/zigbee_monitor/service.py`: сохранение inventory, счетчики
  offline только при полной достоверной availability, минутный SQLite flush,
  ТОП 1ч/24ч/7д, guarded 5m rate и управление read-only refresh.
- `tests/test_service.py`: интеграционные тесты на reconnect, retained,
  невыдуманный ноль, разделение Recorder, 5m-счетчики, rename и refresh.

**Внимание:** пока продукт остаётся **не устанавливаемым через Supervisor**.
Нет `config.yaml`, `digitalhouses.app`, упакованного контейнера,
финальной telemetry v2 и production GHCR образа. Первые runtime-компоненты
являются проверяемой основой HAOS App, а не выпуском 0.1.0.

**Следующий gate:** оформить Supervisor config, безопасный consent/telemetry
контракт, release registry, Dockerfile, translations/icons, полный CI и
installable release после проверки на реальном Zigbee2MQTT.
