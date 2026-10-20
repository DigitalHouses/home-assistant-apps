# DH Zigbee Monitor — UI-first и Recorder контракт (черновик)

Статус: **draft**, не опубликованный MQTT API. До кода необходимо утвердить
реальный Dashboard и каждую сущность.

## Dashboard

Один Home Assistant `sections` Dashboard, рабочий язык русский.
UI не определяет неисправность, не считает сообщения и не вычисляет baseline.

1. **Статус DH Zigbee Monitor** — стандартная карточка с заголовком и четырьмя
   действиями: Обновить / Версия / Новая версия (при установочном обновлении) /
   Перезапуск (через Supervisor).
2. **Сводка** — сети, устройства, offline, инциденты,
   MQTT-публикации за отчётное окно.
3. **Сети** — состояние каждого Zigbee2MQTT, степень достоверности и количество устройств.
4. **Offline** — список устройств, причины, сеть, время начала, динамика.
5. **Хит-парад** — ТОП-20 по активности без автоматической классификации спама;
   интервалы 1ч/24ч/7д, группировка по сети и модели.
6. **Инциденты/история** — текущие проблемы и восстановление, агрегированные графики.
7. **Настройки** — только осмысленные runtime controls; App отвечает за их валидацию.

## Recorder — безусловное правило

**Каждая HA-сущность помечена в проекте как `ON` либо `OFF`.**

Recorder ON:
- scalar numeric/binary `state`;
- без `json_attributes_topic`, `json_attributes_template` и изменяющихся атрибутов;
- допустимы статические метаданные HA (name, unit, device_class и т.п.);
- по изменению значения либо по выбранному окну агрегации;
- при недостоверных данных `unavailable`, а не ложный ноль;
- отдельные `availability`-флаги для неисправности App/источника.

Recorder OFF:
- таблицы и JSON-атрибуты списка устройств/инцидентов;
- переходные MQTT Event и статусная карточка операций;
- runtime диагностика и управляющие сущности без полезной истории;
- явный `recorder.exclude.entities` в примере локального HA-пакета
  и проверка, что исключения действительно применились к реальному конфигу.

### Предварительные сущности

Ниже перечислены **предлагаемые** `default_entity_id`; они уже используются
в UI-first Dashboard `examples/lovelace/dh_zigbee_monitor_app_dashboard.yaml`.
Стабильность `unique_id` обязательна; пользовательское переименование
собственных HA-сущностей может потребовать обновления ссылок в Dashboard.

| Entity | Значение | Recorder |
| --- | --- | --- |
| `sensor.dh_zigbee_monitor_app_networks` | Количество подтверждённых сетей | ON |
| `sensor.dh_zigbee_monitor_app_devices` | Всего зарегистрированных устройств | ON |
| `sensor.dh_zigbee_monitor_app_offline` | Подтверждённый offline count | ON |
| `sensor.dh_zigbee_monitor_app_incidents` | Активные инциденты (движок ещё не реализован) | OFF до реализации |
| `sensor.dh_zigbee_monitor_app_messages_rate_5m` | Суммарная MQTT-активность за 5-минутное окно | ON |
| `sensor.dh_zigbee_monitor_app_<network_id>_rpm` | RPM по сети, исходный, без сглаживания | ON |
| `sensor.dh_zigbee_monitor_app_<network_id>_rpm_smooth` | EMA(15 минут) только для трендов | ON |
| `sensor.dh_zigbee_monitor_app_<network_id>_rpm_threshold_effective` | Текущий рассчитанный auto или ручной порог | ON |
| `sensor.dh_zigbee_monitor_app_offline_details` | JSON-список offline | OFF |
| `sensor.dh_zigbee_monitor_app_top_1h_details` | ТОП MQTT за 1 час | OFF |
| `sensor.dh_zigbee_monitor_app_top_24h_details` | ТОП MQTT за 24 часа | OFF |
| `sensor.dh_zigbee_monitor_app_top_7d_details` | ТОП MQTT за 7 дней | OFF |
| `sensor.dh_zigbee_monitor_app_inventory_details` | Устройства и группировки (предусмотрено для расширения UI) | OFF |
| `sensor.dh_zigbee_monitor_app_networks_details` | Состояния сетей и качество данных | OFF |
| `sensor.dh_zigbee_monitor_app_incidents_details` | Текущие инциденты | OFF |
| `sensor.dh_zigbee_monitor_app_card` | Операции `idle/running/success/error` | OFF |
| `event.dh_zigbee_monitor_app_event` | Машинные события | OFF |

Дополнительные обязательные контрольные сущности:
`sensor.dh_zigbee_monitor_app_version`,
`sensor.dh_zigbee_monitor_app_started_at`,
`button.dh_zigbee_monitor_app_refresh`,
`button.dh_zigbee_monitor_app_check_updates`.
Применять соответствующие стандарты продукта; диагностические timestamp/version
обычно исключаются из Recorder.

## Контракт отображаемых деталей

- UI читает готовые снимки от App, не анализирует 500 сущностей HA в Jinja.
- Переход в HA Device разрешает App по точному IEEE из MQTT Device Registry;
  UI читает только готовый `ha_device_id` и не сопоставляет названия/Entity ID.
  При неоднозначности ссылка отсутствует.
- Детали не встраиваются в исторический числовой sensor.
- Не публиковать огромный безлимитный JSON; ограничить размер и предоставить
  явное число элементов и информацию об усечении (если потребуется).
- Топы за 1ч/24ч/7д формируются App, не вычисляются шаблонами.
- Отображать `unknown`/неполное покрытие отдельно от достоверного нуля.
- Если часть сетей не отвечает, не выдавать частичный global count за полный.
- Момент обновления UI не становится временем последнего получения данных.

## Приёмочные условия

1. CI подтверждает отсутствие JSON-атрибутов у каждого Recorder ON sensor.
2. 24-часовой тест: проверить количество записей, состояний и атрибутов в Recorder.
3. Изменение имён Zigbee2MQTT и HA не сбрасывает историю IEEE-устройства.
4. Переподключение HA/MQTT не умножает статистику и не повторяет инциденты.
5. Массовый отказ сети выдаёт один агрегированный пользовательский сигнал.
6. Списки устройств в UI отображаются даже без накопленной HA Recorder-истории.
7. Состояние отсутствующих источников не маскируется фиктивным `0`.


## Контракт первой UI-версии: готовые атрибуты

Сведения о подробностях формирует **только App**, в Home Assistant ничего
не сортируется, не группируется и не рассчитывается. Пока App отсутствует,
Dashboard показывает отсутствие данных, а не фиктивные значения.

Для каждой подробной MQTT-сущности:

- state: `ready` лишь после успешного сбора актуальных данных;
- state: `unavailable` через app/source availability при потере достоверности;
- основное содержимое: отдельный атрибут-список;
- `json_attributes_topic` допускается **только** для сущностей Recorder OFF;
- данные bounded: максимальные размеры, состав записей и отсечение записей
  задаёт контракт App, не шаблон отображения;
- при `unknown/unavailable` UI не показывает retained-атрибуты как новые;
- минимальная структура атрибутов на старте:

| Detail sensor | Атрибут | Поля элемента |
| --- | --- | --- |
| `networks_details` | `networks` | `network_id`, `name`, `status`, `devices`, `offline` |
| `offline_details` | `devices` | `ieee_address`, `network_id`, `name`, `network_name`, `offline_since`, опциональный `ha_device_id` |
| `top_1h_details` | `items` | `ieee_address`, `network_id`, `name`, `messages` |
| `top_24h_details` | `items` | как выше |
| `top_7d_details` | `items` | как выше |
| `incidents_details` | `incidents` | `incident_id`, `kind`, `name`, `started_at` |

Поле `name` здесь **отображаемое**. Для offline и top`*_details` постоянным
ключом служит `ieee_address`, контекст сети — `network_id`. Для networks
ключ — `network_id`. Переименования не должны менять статистику.

Времена сейчас выводятся как переданные ISO 8601 строки, без вычисления
длительности в HA. В будущем App может дополнительно передавать готовое
отображаемое значение, если согласуем формат.

## Recorder пакет

Согласованный пример:
`examples/packages/dh_zigbee_monitor_app_global_package.yaml`.

- `recorder.include.entities`: только четыре реально вычисляемых исторических
  показателя: networks, devices, offline и messages_rate_5m, а также
  три числовые динамические семьи RPM/raw, RPM/EMA, effective threshold.
- заглушка `spammers` удалена из Discovery в 0.1.17; `incidents` реализован;
  при внедрении отдельным изменением можно добавить их в Recorder.
- `recorder.exclude.entity_globs`: исключить все `sensor/binary_sensor/button/event`
  с префиксом `dh_zigbee_monitor_app_`; точный allowlist
  `recorder.include.entities` имеет приоритет над этими glob-паттернами
  согласно механизму фильтра Home Assistant.
- Никаких динамических JSON деталей, событий, статуса App, версий и timestamps;
- нельзя заменять уже существующие фильтры `recorder` дома;
- при site-level `include` и переназначениях entity IDs проверять правила
  фактического включения/исключения в работающем HA.
- этот файл сейчас **пример**, а не установленное изменение конфигурации HA.

CI: `scripts/tests/test_zigbee_monitor_ui_design.py`.
Он проверяет разбор YAML, стандартную статусную карточку, использование
детальных сущностей, их исключение из Recorder и отсутствие расчётов HA.

## Принцип UI-first

Dashboard согласовывает **что показывать**. Затем App реализует именно эти
данные; не допускается создание неограниченного количества HA entities
на каждое физическое устройство. Стандарт `Home Assistant Event` используется
для переходов, а Recorder — только для ограниченного списка агрегатов.
