# DigitalHouses Internet App — конфигурация

## Сеть

`router_ip` — LAN-адрес роутера. App использует его, чтобы отличать локальную недоступность роутера от upstream-проблемы Интернета/ONT.

`connectivity_check.interval_seconds` задаёт обычный интервал проверки. `attempts` — количество последовательных наблюдаемых неудачных Internet probes, необходимое для начала outage incident. `timeout_seconds` — таймаут одной проверки. Связность остаётся unknown/unavailable до завершения реального probe. Невозможность выполнить сам механизм probe является диагностической ошибкой, а не наблюдаемым outage, поэтому она не увеличивает подтверждение outage и не запускает recovery.

## Восстановление

По умолчанию recovery отключён.

`recovery.mode` поддерживает только:

- `smart`: Internet down + Router up → ONT; Router down → Router.
- `both`: ONT → Router при каждой попытке recovery.

Каждая цель поддерживает только `button` или `switch`. Цель типа button должна ссылаться на сущность `button.*` и вызывается через `button.press`. Цель типа switch должна ссылаться на `switch.*`; App выключает её на `power_off_seconds` и всегда пытается вернуть питание до завершения action либо передачи Stop request. App объявляет 45-секундный Supervisor shutdown timeout, чтобы обычный App Stop/Restart оставлял достаточно времени для защитного восстановления питания.

Когда recovery включён, должны быть настроены обе цели — ONT и Router. Все временные параметры recovery принадлежат App configuration:

- `max_cycles`: количество recovery attempts до cooldown.
- `boot_wait_minutes`: время стабилизации после цикла действий.
- `retry_interval_minutes`: задержка перед следующим циклом, если Интернет всё ещё недоступен.
- `cooldown_minutes`: пауза после `max_cycles`; если тот же outage продолжается, после неё может начаться новая серия.

MQTT-кнопка Stop подавляет дальнейшие попытки для текущего incident, включая перезапуск App. Бюджет уже выполненных recovery cycles и активный cooldown также сохраняются, поэтому рестарт App не позволяет обойти заданные ограничения. Рестарт между обычными циклами повторно применяет retry guard до следующего power action. Новый outage очищает предыдущее recovery runtime state.

## Speedtest

App запускает официальный Ookla CLI. Периодический запуск управляется App configuration, поддерживает интервал 5..720 минут и может быть отключён. MQTT Discovery-кнопка Run speed test использует тот же backend path.

Графические сущности: Download, Upload, Ping, Jitter и Packet loss. Provider, external IP, выбранный server, result URL, timestamp последнего успешного теста, last result и last error являются атрибутами компактной Speedtest status entity, а не отдельными сущностями.

Speedtest status — это execution-state sensor: обычно он находится в `idle`, во время выполнения Ookla переходит в `running`, затем возвращается в `idle`. Атрибут `last_result` хранит `success`, `error` или `no_connectivity`. Неудачный или пропущенный тест не перезаписывает последние успешные измерения — они остаются сохранены под `/data/runtime`.

Перед каждым ручным или периодическим Speedtest App выполняет свежую connectivity probe. Если Интернет недоступен, Ookla не запускается, а skip не увеличивает streak автоматических ошибок. Ошибки автоматического запуска считаются с сохранением между рестартами App; любой успешный ручной или автоматический Speedtest сбрасывает streak в ноль. Каждая ошибка остаётся доступной как machine event/log record, но reference notification packages уведомляют только на пятой последовательной автоматической ошибке и не повторяют уведомление на 6-й, 7-й и последующих ошибках. Ошибка ручного Speedtest уведомляется немедленно.

### Выбор сервера

`speedtest.server_ids` — упорядоченный список предпочтительных Ookla server IDs. Пустой список означает automatic selection. Настроенные IDs пробуются по порядку; если включён `automatic_server_fallback`, после них выполняется одна финальная попытка automatic selection.

Каталог серверов работает по запросу: `button.dh_internet_app_refresh_servers` обновляет одну диагностическую сущность `sensor.dh_internet_app_available_servers`. Фонового polling каталога серверов нет.

## Пороги качества

Три редактируемые пользователем MQTT Number entities: Minimum download speed, Minimum upload speed и Maximum ping. Их значения хранятся под `/data/runtime` и немедленно пересчитывают последний успешный Speedtest result.

App владеет состояниями low-download, low-upload, high-ping и aggregate performance-problem. Home Assistant отвечает только за presentation и не пересчитывает пороги шаблонами. Schema-v2 Events отправляются при значимых переходах состояния проблемы.

## Последние результаты

App хранит последние 20 успешных Speedtest records под `/data/runtime`. Home Assistant получает их через одну диагностическую Recent results sensor, state которой содержит количество сохранённых тестов, а атрибут `results` — сами записи.

Каждая запись хранит измеренные значения вместе с порогами и problem flags, действовавшими на момент завершения теста. Последующее изменение порогов пересчитывает текущее problem state, но не переписывает исторические Recent Results snapshots.

## Отключения и доступность за месяц

App хранит каждое отключение текущего локального календарного месяца, включая активное; список за месяц не обрезается. Каждая запись содержит From, To и duration; у текущего outage поле To отсутствует до восстановления. Presentation может показывать только последние строки, не изменяя сохранённую месячную историю.

Доступность текущего месяца рассчитывается App как прошедшее время локального календарного месяца минус накопленное время outages. Активный outage сохраняется между рестартами App; если он пересекает границу месяца, новый месяц привязывается к локальному началу месяца. Home Assistant только отображает результат и не владеет расчётом.

## Телеметрия роутера и трафик

Все Home Assistant bindings роутера опциональны. Публичный контракт содержит не более пяти:

- `traffic.traffic_download_total`
- `traffic.traffic_upload_total`
- `traffic.router_wan_status`
- `traffic.router_download_rate`
- `traffic.router_upload_rate`

Вместе с двумя опциональными recovery target entities это ограничивает поверхность внешних Home Assistant bindings максимум семью. Ни один Home Assistant entity binding не является обязательным.

Два накопительных счётчика образуют пару: настраиваются либо оба, либо ни один. Они включают App-owned месячный учёт трафика. WAN state и текущие Download/Upload rates — независимые опциональные bindings и не влияют на recovery decisions.

App опрашивает настроенные Router sources каждые 60 секунд через Home Assistant Core API. Каждый mapped numeric traffic/rate source обязан публиковать явный поддерживаемый `unit_of_measurement`; отсутствие unit означает unavailable contract data, и единица никогда не угадывается. Единицы data size Home Assistant нормализуются в bytes, а data rate — в Mbit/s с сохранением различия между bit (`bit/s`, `Mbit/s`) и byte (`B/s`, `MB/s`). Также принимаются распространённые aliases `Mbps/Gbps`.

Первый cumulative sample устанавливает baseline и не считается потреблением. Нормальный рост добавляет только delta. Reset исходного счётчика не создаёт отрицательный трафик. При изменении cumulative source IDs история сохраняется, но устанавливается новый baseline. На границе календарного месяца первая observation также становится новым baseline, потому что cumulative counters не позволяют точно разделить delta по сторонам границы месяца.

Traffic history хранит текущий месяц и до 11 предыдущих наблюдаемых месяцев под `/data/runtime`. Traffic entities создаются только при настроенной cumulative pair. WAN state и current rate entities создаются только при наличии собственных mappings. Если опциональный mapped source отсутствует, имеет `unknown` или `unavailable`, соответствующая MQTT entity помечается unavailable до возврата источника; reference dashboard скрывает такую entity. При удалении mapping из App configuration App явно удаляет ранее обнаруженный optional MQTT component до публикации уменьшенной конфигурации устройства.

Temperature, connected-client count, uptime и last-boot bindings намеренно находятся вне нового App contract.

## Телеметрия продукта

`telemetry_enabled` — явный opt-in, по умолчанию `false`. В disabled состоянии App не выполняет telemetry heartbeat requests.

При включении App отправляет protocol-v1 heartbeat на `https://telemetry.digitalhouses.vip` ровно с такими данными:

- protocol schema version;
- telemetry policy version;
- persistent random installation UUID;
- product `digitalhouses_internet_app`;
- App version.

Per-installation token используется только как Bearer credential. Страна определяется на стороне сервера; Internet measurements, outage history, router telemetry, entity IDs, Home Assistant identity и configuration не отправляются.

Identity и состояние heartbeat scheduling сохраняются в `/data/telemetry.json`. Отсутствующий файл создаёт новую installation identity; существующий malformed file приводит к явной ошибке и никогда не заменяется новым UUID/token, чтобы одна установка не могла незаметно превратиться во вторую telemetry installation. Persistent state также хранит, была ли telemetry disabled или enabled. Переход configuration `false -> true` планирует ровно один немедленный best-effort heartbeat при следующем запуске App, даже если предыдущий успешный heartbeat ещё находится внутри обычного 24-часового интервала. После первой попытки переход считается обработанным: обычный restart не создаёт ещё один немедленный heartbeat. После успешного heartbeat следующий обычно отправляется через 24 часа ±30 минут. Если немедленная или плановая попытка неудачна, timestamp ошибки сохраняется, а restart не позволяет обойти часовой backoff. Ошибки telemetry никогда не влияют на основной monitoring/recovery path.

`button.dh_internet_app_delete_telemetry` выполняет authenticated deletion сохранённой серверной telemetry record установки. Отключение telemetry прекращает будущие heartbeat, но не удаляет уже сохранённые серверные данные.

Общая политика: [DigitalHouses Product Telemetry Policy](../docs/standards/PRODUCT_TELEMETRY_POLICY.md).

## Контракты persistent state и конфигурации

Отсутствующие опциональные configuration keys используют defaults, объявленные App schema. Явно заданные invalid values отклоняются; integers не clamp-ятся, strings не преобразуются в booleans/numbers, а invalid log level не откатывается к `info`.

App-owned persistent runtime files различают первый запуск и corruption. Если файл ещё не существует, могут быть созданы документированные fresh-state defaults. Если существующий recovery, outage, threshold, traffic, Speedtest, recent-results, server-catalog, discovery или telemetry state file не читается либо нарушает контракт, App сообщает явную contract-data failure вместо подстановки zero/false/empty state.

## Events и уведомления

App публикует machine-readable MQTT Event entities по schema version 2. Каждый event проверяется producer-ом по event-specific required fields и types до MQTT transport. Event payloads содержат семантику вроде event type, target, cycle, reason, values и timestamps. Для `connection_lost` и `connection_restored` authoritative retained state публикуется первым, transient event — после него.

Human-readable notification text и конечная доставка принадлежат local Home Assistant package. App публикует только machine events и не зависит от `script.write2log`, Telegram, mobile notifications или другого delivery service.

## Presentation-слой Home Assistant

Reusable Home Assistant layer не рассчитывает Internet state, recovery decisions, quality thresholds, outages или traffic. Всё это остаётся App-owned.

`dh_internet_app_global_package.yaml` содержит только Recorder whitelist для полезных time-series entities. Он записывает connectivity, Speedtest measurements/status, quality thresholds/problem flags, recovery state/cycle и опциональные Router WAN/rates плюс cumulative/current-month traffic. Rich list/history entities, такие как месячные outage rows, Recent Results, server catalogs и traffic-history aggregates, намеренно не пишутся в Recorder, поскольку их attributes сохраняются App и могут быть крупными.

`dh_internet_app_notification_local_package.yaml` и `locales/ru/dh_internet_app_notification_local_package.yaml` напрямую потребляют schema-v2 machine Events из `event.dh_internet_app_event`. Каждый user-visible `event_type` имеет читаемый `trigger.id` и одну соответствующую ветку `choose`. Оба публичных locale examples напрямую вызывают `persistent_notification.create`; установка может заменить только этот final action собственным local delivery service.

Notification Envelope, secondary notification event, adapter и duplicated schema-validation layer в Home Assistant отсутствуют. Если producer нарушает required event contract, исправляется producer и его tests, а не создаются fallback notification data.
