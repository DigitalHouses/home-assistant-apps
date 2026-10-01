# Журнал изменений

## 0.1.20

- Сохранять между перезапусками App серию последовательных ошибок автоматического Speedtest и сбрасывать её после любого успешного ручного или автоматического Speedtest.
- Сохранить обязательную проверку связности перед Speedtest: подтверждённая недоступность Интернета полностью пропускает запуск Ookla и не увеличивает серию автоматических ошибок.
- Добавить в machine events ошибок Speedtest источник запуска и текущую длину серии автоматических ошибок.
- Сохранять каждую ошибку Speedtest в machine event/log path, но подавлять пользовательское уведомление для автоматических ошибок 1–4 и 6+; reference notification packages уведомляют ровно на пятой последовательной автоматической ошибке.
- Сохранять немедленное уведомление об ошибке ручного Speedtest.

## 0.1.19

- Сделать released App version обязательными runtime contract data; убрать fallback `unknown` и устаревшие локальные fallback version.
- Держать connectivity entities unavailable до успешного реального probe и отделять ошибку выполнения probe от наблюдаемого outage Интернета/роутера, чтобы недоступный механизм проверки не мог запустить recovery.
- Валидировать каждый schema-v2 machine event на стороне producer и публиковать authoritative retained incident state до transient events `connection_lost` / `connection_restored`.
- При malformed persistence recovery, outage, traffic, thresholds, Speedtest, recent-results, server-catalog, discovery или telemetry завершаться явной ошибкой вместо тихой подстановки healthy defaults.
- Сохранять telemetry installation identity при повреждении state: отклонять невалидные persistent UUID/token вместо генерации новой установки.
- Требовать явные units у mapped traffic/rate sources, отклонять невалидную явно заданную App configuration вместо coercion/clamping и представлять отсутствующие optional Speedtest metadata как `null`.
- Не менять Supervisor slug, MQTT namespace/device identity, Home Assistant entity IDs, recovery modes и cadence публикации в Recorder.

## 0.1.18

- Перевести production-доставку Home Assistant на канонический versioned GHCR image repository `ghcr.io/digitalhouses/digitalhouses_internet_app`.
- Не менять канонический Supervisor slug, MQTT namespace/device identity, Home Assistant entity identities, App options и persistent state `/data`.
- Добавить repository validation immutable image metadata и документировать acceptance backup/restore текущего production без требования downgrade на более старый App release.

## 0.1.17

- Перевести DigitalHouses Internet App со стадии Home Assistant `experimental` в `stable`.
- Сохранить канонический App slug `digitalhouses_internet_app` и все существующие MQTT, device, unique-id и Home Assistant entity identities.
- Добавить repository validation, запрещающую Internet App незаметно вернуться на experimental stage.

## 0.1.16

- Удалить временный runtime миграции HA App slug после успешной migration и rollback acceptance.
- Удалить writable mapping `/share` и `DH_SLUG_MIGRATION_MODE` из канонической App configuration.
- Удалить `slug_migration.py`, migration-only tests и shutdown/export hooks из production image.
- Оставить только канонический Supervisor slug `digitalhouses_internet_app`; repository validation теперь запрещает регрессию migration runtime/config.
- Канонизировать имя внутреннего Python logger как `digitalhouses_internet_app` без изменения MQTT, device, unique-id и Home Assistant entity identities.

## 0.1.15

- Сделать marker завершённой canonical slug migration authoritative относительно любых последующих обновлений bridge bundle.
- Исправить rollback verification: start/stop legacy bridge App `0.1.12` пересоздаёт shared bundle с новым timestamp/hash, но это не должно ломать уже мигрированный canonical App или повторно импортировать старое state.
- Проверять schema/product/source/target identity completed marker до игнорирования shared bridge bundle.
- Сохранять более новое canonical runtime state при legacy rollback tests и последующих canonical restarts.

## 0.1.14

- Исправить import canonical slug под реальный lifecycle Supervisor options: persistent App options становятся видимы в `/data/options.json` только после следующего запуска canonical container.
- Если migrated options ещё не активны, применять их через `/addons/self/options`, записывать pending migration marker и корректно останавливаться вместо перехода в `state: error`.
- При следующем запуске проверять, что ожидаемые options смонтированы, до восстановления telemetry identity и всего явного App-owned runtime state.
- Обработать реальный field-case `0.1.13`, когда Supervisor уже принял migrated options до сбоя старого importer в ожидании невозможного hot-update.
- Сделать completed imports idempotent, чтобы bridge snapshot не мог перезаписать более новое canonical state.

## 0.1.13

- Завершить контролируемую миграцию Home Assistant App slug на канонический `digitalhouses_internet_app`.
- При первом запуске canonical slug импортировать проверенный bridge bundle из `/share/digitalhouses_internet_app/slug-migration-v1/bundle.tar.gz` до старта обычного runtime.
- Восстанавливать прежние App options через собственный Supervisor API App, затем атомарно восстанавливать telemetry identity и всё явное App-owned runtime state.
- Сохранить MQTT/device/unique-id/Home Assistant identities под `dh_internet_app`; legacy установка `digitalhouses_internet` остаётся остановленной rollback target до migration acceptance.
- Сохранять migration bundle и import marker, чтобы повторные запуски не могли снова наложить bridge snapshot поверх более нового canonical state.

## 0.1.12

- Добавить контролируемую bridge phase миграции Home Assistant App slug с `digitalhouses_internet` на `digitalhouses_internet_app`.
- Экспортировать текущие App options, telemetry identity/schedule и явное state `/data/runtime` в один атомарный migration bundle с проверкой SHA-256 под `/share/digitalhouses_internet_app/slug-migration-v1/`.
- Обновлять bridge bundle при старте App и graceful shutdown; ошибка export изолирована от обычного monitoring/recovery Интернета.
- Добавить canonical-side importer заранее, но не активировать до следующего релиза с canonical slug. Importer применяет options через собственный Supervisor API App до восстановления state и является idempotent.
- Сохранить MQTT, device, unique ID и Home Assistant entity identities под `dh_internet_app`.

## 0.1.11

- Отправлять один немедленный best-effort telemetry heartbeat при изменении persistent App setting `telemetry_enabled: false` → `true`, даже если предыдущий успешный heartbeat ещё находится внутри обычного 24-часового интервала.
- После первой попытки считать enable transition обработанным, чтобы обычные restarts не создавали heartbeat storm; failed opt-in heartbeat сохраняет существующий часовой backoff между рестартами.
- Логировать успешные telemetry heartbeats на уровне INFO без installation identity или token data.
- Добавить regression coverage для re-enable, подавления restart и persistence failure-backoff.

## 0.1.10

- Добавить явную opt-in поддержку DigitalHouses Telemetry Protocol v1 с `telemetry_enabled: false` по умолчанию.
- Хранить random per-installation UUID/token и heartbeat schedule в `/data/telemetry.json`; отправлять только protocol version, policy version, `digitalhouses_internet_app`, App version и installation UUID.
- Отправлять обычные heartbeat каждые 24 часа ±30 минут с часовым failure backoff в изолированном worker, чтобы telemetry не могла влиять на monitoring/recovery Интернета.
- Добавить authenticated telemetry deletion через `button.dh_internet_app_delete_telemetry`.
- Добавить `digitalhouses_internet_app` в shared telemetry protocol/stats-server allowlist и отличать его от legacy продукта `digitalhouses_speedtest_app` в Stats dashboard.
- Запретить встроенной development version `*-local` отправлять production telemetry.

## 0.1.9

- Снизить churn Home Assistant Recorder от `sensor.dh_internet_app_problems`: удалить per-publish атрибут `updated_at`; теперь entity меняется только при изменении количества/списка проблем.
- Снизить churn Recorder от `sensor.dh_internet_app_availability_month`: публиковать только стабильный атрибут `month` и округлять state HA entity до двух знаков.
- Сохранить полный outage payload и точные `elapsed_seconds`, `online_seconds`, `offline_seconds` и outage durations в App-owned outage MQTT payload; low-noise сделать только Recorder-facing availability entity.

## 0.1.8

- Упростить уведомления Home Assistant до той же прямой модели, что используется в `dh_pve_app`: machine event → `trigger.id` → `choose` → direct local action.
- Заменить Notification Envelope / secondary layer `dh_internet_app_notification` на `dh_internet_app_notification_local_package.yaml`.
- Английский пример напрямую вызывает `persistent_notification.create`; русский site-local package напрямую вызывает `script.write2log`.
- Удалить duplicated machine-event schema validation и presentation logic `contract_error` из Home Assistant. Корректность обязательного machine-event контракта остаётся ответственностью producer.
- Не менять machine-event schema Internet App и MQTT Event entity.

## 0.1.7

- Защитить MQTT templates Router Download/Upload с одним знаком после запятой от optional значений `null`, чтобы unavailable mapped source корректно становился unavailable вместо формирования невалидного numeric template.

## 0.1.6

- Упростить runtime status Speedtest до `idle | running`; результат последней попытки теперь отдельно публикуется как `last_result=success|error|no_connectivity`, при этом успешные measurements остаются persistent.
- Округлять states сущностей Router Download/Upload rate до одного знака.
- Расширить Recorder whitelist метаданными Speedtest status, quality thresholds, recovery state/cycle, aggregate Problems и Router WAN state, оставив rich list/history entities вне Recorder.
- Добавить явный regression test, подтверждающий, что sensor outages текущего месяца публикует полный список месячных outages без truncation.
- Восстановить устойчивый Markdown pattern «одна строка на результат» для reference table Recent Speedtests.

## 0.1.5

- Мигрировать уведомления Internet App на repository Events and Multilingual Notifications Standard и DigitalHouses Notification Envelope v1.
- Добавить строгую event-specific schema validation до localization; malformed machine events теперь генерируют явные уведомления `contract_error` вместо silent fallback values.
- Сделать английский и русский locale packages contract-identical, перенести русскую presentation в канонический путь `examples/packages/locales/ru/` и удалить forwarding raw machine payload.
- Оставить notification delivery в ответственности установки: reusable locale packages завершаются на transport-neutral Home Assistant event `dh_internet_app_notification`.

## 0.1.4

- Сохранять pending detection Internet outage с первой неудачной connectivity check, включая debounce attempt count, чтобы рестарты App не теряли реальный start time outage и не начинали подтверждение снова с нуля.
- Подтверждённые outages теперь начинаются с первой неудачной проверки; transient failures, восстановившиеся до подтверждения, отбрасываются.

## 0.1.3

- При обновлении legacy runtime state, созданного до 0.1.2, backfill `updated_at` Recent Results из самого нового persistent `tested_at`.

## 0.1.2

- Исправить `updated_at` Recent Results: теперь он меняется только при изменении persistent Speedtest history, а не при каждой MQTT state publication.

## 0.1.1

- Исправить startup на base images Home Assistant с paho-mqtt 1.x, добавив runtime compatibility одновременно с callback APIs paho-mqtt 1.x и 2.x.
- Сохранять MQTT v2 callback API, когда он доступен, при этом принимать legacy четырёхаргументный callback `on_connect` в paho-mqtt 1.x.

## 0.1.0

- Переименовать каталог репозитория в `dh_internet_app`, сохранив HA App slug `digitalhouses_internet`.
- Исправить MQTT Event Discovery, чтобы schema-v2 JSON events передавались напрямую в Home Assistant.
- Сохранять active outage state между рестартами App и переходом календарного месяца.
- Расширить EN/RU описания App configuration для всех user-facing options с использованием официального nested `fields` translation format.
- Усилить MQTT v2 connection callback handling и документировать все зависимости dashboard cards.
- Сохранять Stop Recovery, завершённые recovery cycles и active cooldown между рестартами App для одного outage.
- Усилить switch recovery: попытка restore power выполняется даже при ошибке API response на выключение.
- Помечать optional Router telemetry unavailable, когда её mapped HA source отсутствует/unavailable, и скрывать её в reference dashboard.
- Увеличить HAOS shutdown timeout для защиты восстановления питания switch при обычном App Stop/Restart.
- Добавить явный cleanup MQTT Device Discovery при удалении optional Router/Traffic mappings.
- Исправить normalization единиц Router traffic, чтобы bit/s и byte/s не схлопывались в одинаковый lowercase key.

- Создать DigitalHouses Internet App как новый Home Assistant App product с канонической MQTT/Home Assistant identity `dh_internet_app_`.
- Добавить reachability Интернета/роутера, history отключений текущего месяца и App-owned расчёт monthly availability.
- Добавить recovery modes `smart` и `both` с защищёнными actions `button` / `switch`, countdown, Stop control и structured events.
- Добавить runtime diagnostics Version и Started at.
- Добавить официальный Ookla Speedtest с periodic/manual execution, Download, Upload, Ping, Jitter, Packet loss и компактными status metadata.
- Добавить persistent quality thresholds, оценку low download/upload/high ping, aggregate Problems diagnostics и schema-v2 performance events.
- Добавить persistence Recent Results с последними 20 успешными тестами и per-test quality thresholds.
- Добавить optional cumulative router traffic accounting с totals текущего месяца и историей за 12 месяцев.
- Добавить optional bindings WAN state и текущих Router Download/Upload rate, сохраняя общий контракт внешних HA bindings в пределах семи вместе с recovery.
- Добавить preferred Ookla server IDs, automatic fallback и on-demand refresh списка серверов.
- Добавить reusable examples Home Assistant Recorder, notifications и dashboard presentation.
