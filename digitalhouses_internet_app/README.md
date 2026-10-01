# DigitalHouses Internet App

Home Assistant App для мониторинга доступности Интернета, Ookla Speedtest, истории отключений за текущий месяц и автоматического восстановления ONT/роутера.

Это отдельный продукт. Он не мигрирует и не переиспользует стабильные MQTT-идентификаторы или историю Recorder продукта `digitalhouses_speedtest`.

> Документация DigitalHouses Internet App в репозитории ведётся на русском языке. Технические идентификаторы, имена сущностей, MQTT-топики, значения протоколов и код сохраняются в исходном виде.

## Канонические идентификаторы

- каталог в репозитории: `digitalhouses_internet_app`
- slug HA App: `digitalhouses_internet_app`
- публичное имя продукта: **DigitalHouses Internet App**
- идентификатор релиза: `digitalhouses_internet_app`
- production-образ: `ghcr.io/digitalhouses/digitalhouses_internet_app:<version>`
- базовый MQTT-топик: `DigitalHouses/Global/dh_internet_app`
- префикс сущностей / unique ID Home Assistant: `dh_internet_app_`

## Восстановление

Восстановление намеренно ограничено двумя пользовательскими режимами:

- `smart` — если роутер доступен локально, но Интернет недоступен, перезагружается ONT; если сам роутер недоступен, перезагружается роутер.
- `both` — в каждом цикле восстановления последовательно перезагружаются ONT и затем роутер.

Действия восстановления намеренно ограничены двумя типами:

- `button` — нажатие существующей кнопки перезагрузки Home Assistant;
- `switch` — цикл выключения/включения существующего switch/реле Home Assistant.

Произвольные scripts и shell-команды не входят в контракт восстановления.

Все временные параметры восстановления принадлежат конфигурации App: максимальное количество циклов, интервал повторной попытки, ожидание загрузки, cooldown и длительность отключения питания switch. `router_ip` — сетевой параметр верхнего уровня, который используется и мониторингом, и smart-восстановлением.

`Stop recovery` останавливает дальнейшие попытки для текущего отключения. Состояние Stop, количество уже выполненных циклов и активный cooldown сохраняются при перезапуске App, поэтому перезапуск не позволяет обойти ограничения восстановления. Если switch уже был выключен, App всегда пытается вернуть питание до завершения Stop. Таймаут остановки HAOS App увеличен до 45 секунд, чтобы обычные Stop/Restart могли завершить этот защитный путь восстановления питания.

## Текущее состояние продукта

Версия `0.1.20` сохраняет immutable-доставку через GHCR и добавляет устойчивое подавление кратковременных ошибок автоматического Speedtest. Каноническая Supervisor-идентичность постоянна, временный runtime миграции удалён, App остаётся в стабильном канале Home Assistant. Продукт предоставляет:

- доступность Интернета и роутера;
- состояние отключений текущего месяца с хранением под `/data`;
- state machine восстановления `smart | both`;
- действия восстановления `button | switch` через Home Assistant Core API;
- countdown восстановления и кнопку Stop;
- структурированную MQTT Event-сущность;
- диагностические Version и Started at;
- измерения Ookla Download, Upload, Ping, Jitter и Packet loss;
- ручной и периодический Speedtest со статусом выполнения `idle | running` и метаданными последнего результата;
- предпочтительные Ookla server IDs с опциональным automatic fallback и каталогом серверов по запросу;
- Recent Results как одну диагностическую сущность с последними 20 успешными тестами и порогами, действовавшими на момент каждого теста.

Реализованы пороги качества и App-owned оценка проблем производительности. Интеграция с роутером использует не более пяти опциональных HA bindings: накопительные Download/Upload, WAN state и текущие Download/Upload rates. Вместе с двумя recovery entities App остаётся в пределах семи внешних HA bindings. История трафика хранит текущий месяц и 11 предыдущих. В продукт входят reusable package, presentation уведомлений и reference dashboard.

Семантика конфигурации описана в [DOCS.md](DOCS.md), а последовательность проверки реальной установки — в [HAOS_TEST_PLAN.md](HAOS_TEST_PLAN.md).

## Неизменяемая production-доставка

Production-релизы доставляются через репозиторий DigitalHouses App с использованием канонического image repository `ghcr.io/digitalhouses/digitalhouses_internet_app`. Версия App package, канонический release tag, точный release commit, GHCR version tag и зафиксированный image digest должны описывать один и тот же релиз. Плавающие теги вроде `latest` не входят в production-контракт.

Backup Home Assistant должен содержать установочную конфигурацию и persistent-состояние `/data`, включая telemetry identity и App-owned runtime state, без дублирования локально собранного application image. Restore acceptance выполняется для текущего поддерживаемого production-релиза; восстановление старого релиза поверх нового не является общим требованием immutable-доставки.

## Завершённая миграция slug App

Миграция Home Assistant App slug с legacy `digitalhouses_internet` на канонический `digitalhouses_internet_app` завершена.

Релизы `0.1.12`–`0.1.15` содержали временный bridge/import-механизм для контролируемой переустановки. Версия `0.1.16` удалила этот механизм из обычного runtime: отсутствуют writable mapping `/share`, migration environment mode и migration module в image.

MQTT/device/entity identities под `dh_internet_app` не изменились.

Завершённая процедура и история релизов сохранены в [документе миграции slug](../docs/digitalhouses_internet_app/slug-migration.md).

## Поведение runtime-контрактов

Связность считается **неизвестной**, пока не завершится реальная ICMP-проверка. Во время запуска либо при невозможности выполнить сам механизм probe четыре connectivity entities показываются как unavailable, а не как недоступные. Ошибка выполнения probe не увеличивает подтверждение outage и не может запустить автоматическое восстановление.

Persistent App-owned state под `/data` является контрактными данными. Действительно отсутствующий state file рассматривается как первый запуск и получает документированные значения по умолчанию там, где это предусмотрено. Уже существующий повреждённый файл молча не заменяется: запуск завершается явной ошибкой contract data, чтобы ограничения восстановления, история отключений, traffic totals или telemetry installation identity не могли незаметно сброситься.

Machine events проверяются producer-ом по event-specific контракту schema v2 до транспорта. Для потери/восстановления связи authoritative retained state синхронизируется до отправки transient event. Существующие MQTT/device/entity identities не меняются.

## Телеметрия продукта

Телеметрия использования является явным opt-in и по умолчанию отключена:

```yaml
telemetry_enabled: false
```

При переходе telemetry из disabled в enabled App выполняет одну best-effort heartbeat-попытку сразу при следующем запуске. Свежая установка и изменение released App version также дают право на немедленный heartbeat. После успешного heartbeat обычная отправка происходит примерно раз в 24 часа с детерминированным jitter ±30 минут. Обычные рестарты не обходят сохранённое расписание, а неудачная попытка сохраняет часовой backoff между рестартами. Endpoint: `https://telemetry.digitalhouses.vip`. Payload содержит только protocol version, telemetry policy version, случайный installation UUID, канонический product identifier `digitalhouses_internet_app` и App version. Страна определяется на стороне сервера. Hostname, Home Assistant UUID, LAN/WAN addresses, данные роутера, результаты Speedtest, outages, entity IDs и конфигурация не отправляются.

Telemetry identity и состояние расписания хранятся в `/data/telemetry.json`, поэтому переживают restart/update App и обычный HA backup/restore. Ошибки телеметрии никогда не влияют на мониторинг Интернета или восстановление. `button.dh_internet_app_delete_telemetry` выполняет authenticated deletion серверной telemetry-записи этой установки.

См. [политику телеметрии продуктов DigitalHouses](../docs/standards/PRODUCT_TELEMETRY_POLICY.md).

## Presentation в Home Assistant

Home Assistant слой намеренно разделён по ответственности:

- `examples/packages/dh_internet_app_global_package.yaml` — только Recorder whitelist;
- `examples/packages/dh_internet_app_notification_local_package.yaml` — английский пример прямой доставки;
- `examples/packages/locales/ru/dh_internet_app_notification_local_package.yaml` — русский публичный пример прямой доставки;
- `examples/lovelace/dh_internet_app_dashboard.yaml` — reference Sections dashboard.

Устанавливается один local notification package. Он напрямую потребляет `event.dh_internet_app_event`, назначает каждому user-visible machine event собственный `trigger.id`, маршрутизирует через `choose` и напрямую вызывает конечный delivery action. Notification Envelope, вторичного события `dh_internet_app_notification`, adapter layer и повторной machine-schema validation в Home Assistant нет. Контракт machine event принадлежит producer-у.

Reference dashboard использует Mushroom, mini-graph-card и auto-entities. Опциональные Router и traffic entities скрываются, если их mappings не настроены либо mapped source в данный момент unavailable.

Recorder-facing диагностика намеренно low-noise: `sensor.dh_internet_app_problems` меняется только при фактическом изменении списка проблем, а `sensor.dh_internet_app_availability_month` публикует state с двумя знаками и стабильный атрибут календарного месяца, тогда как точные outage timings остаются App-owned.
