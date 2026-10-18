# Changelog

## Lovelace · относительная длительность состояний (без изменения версии App)

- Карточка жильцов Mushroom в standalone-примере и штатном дашборде показывает `Итог`, `GPS` и `Wi-Fi` с длительностью текущего статуса: `только что`, `1 минуту назад`, `2 часа назад`, `1 день назад` и правильными русскими окончаниями.
- Шаблон использует уже существующие времена смены статусов App, а `now()` обеспечивает обновление показаний каждую минуту. Неизвестный timestamp — `—`. Не создаёт новых сущностей или Recorder-данных.
- В standalone-примере убрано устаревшее указание `ARP`; используется `Не подключён (роутер)`. Версия App 0.1.36 остаётся прежней — необходима только ручная замена карточки в HA.
- Добавлены тесты рендеринга Jinja, проверки русских форм и идентичности standalone/dashboard YAML.


## 0.1.36 — Локальное время без суффикса часового пояса

- В подветках `GPS → Статус с` и `Wi-Fi → Статус с` оставлено **только местное время** Home Assistant в формате `ДД.ММ.ГГГГ ЧЧ:ММ`. Суффиксы `+05`, `UTC`, `CET` и аналогичные удалены.
- Источник часового пояса остаётся прежним: `time_zone` из HA Core `/api/config`, с корректной обработкой переходов DST. Если часовой пояс не удалось получить, App **не показывает UTC под видом местного**: вместо времени пишет `местное время недоступно` и повторяет чтение конфигурации через пять минут.
- Для настоящего отсутствия времени изменения статуса остаётся `нет данных`, для непривязанного Wi-Fi — `не применимо`. Тimestamps и внутренняя логика GPS/Wi-Fi не изменены.
- Версия App 0.1.36. Нет изменений YAML, MQTT Discovery, контракта сенсора, Recorder и привилегий. Тесты: Алматы, зоны с DST, неизвестный часовой пояс и точное отсутствие смещений.


## 0.1.35 — Время текущего статуса GPS и Wi-Fi в дереве

- Добавлена отдельная вложенная ветка `Статус с · ДД.ММ.ГГГГ ЧЧ:ММ TZ` **под каждой** веткой GPS и Wi-Fi в существующем компактном дереве зарегистрированных телефонов. Это уже существующие `gps_changed_at` и `wifi_changed_at` из App Engine — не время очередного опроса и не `last_reported`.
- Приложение переводит времена в `time_zone` из конфигурации Home Assistant (`/api/config`); при недоступной зоне явно используется `UTC`. Если момент перехода ещё неизвестен, показано `нет данных`; для непривязанного Wi-Fi — `не применимо`.
- Исправлено отслеживание момента перехода GPS в `unavailable` при недоступных данных или ошибке Core API, а также при замене Wi-Fi-привязки: нельзя показывать старое время статуса «Дома». Повторные недоступные опросы не сбрасывают время, не создают ложных событий ухода.
- Формат `<pre style="line-height:1">`, emoji 📲 / 🟢 / 🟠 / ⚪, IP/MAC, MQTT-сенсор и его `count`, свойства Recorder и версии HA-карточек не изменены. Регистрировать телефоны заново или менять YAML не нужно.
- Добавлены тесты точной структуры вложенных веток, часового пояса Asia/Almaty/UTC, отсутствующих timestamp, отсутствия повторной записи статуса и публикации дерева через существующий MQTT snapshot.


## 0.1.34 — Живые состояния GPS/Wi-Fi в дереве телефонов

- На ветках GPS и Wi-Fi теперь показывается собственное состояние источника: **🟢 Дома** (`home`), **🟠 Не дома** (`not_home`) или **⚪ Недоступно** (`unavailable`). Непривязанный Wi-Fi показан как **⚪ Не привязан**, без ложной отметки отсутствия.
- Названия GPS/Wi-Fi `device_tracker` остаются видны; значок телефона заменён с 📱 на 📲. Корень, ветки IP/MAC и проверенный компактный `<pre style="line-height:1">` не изменены.
- App подставляет статусы из уже существующих `Resident.gps`/`Resident.wifi` на каждой штатной MQTT-публикации. Изменения регистраций не требуются; одинаковые payload остаются подавленными существующим MQTT кешем. Режим `gps/wifi/hybrid` не изменяет смысл отдельных веток.
- Новых MQTT-сущностей, HA-темплейтов и записываемых метрик нет. Сохранять исключение диагностического сенсора `sensor.dh_presence_app_registered_phones` из Recorder, поскольку его дерево обновляется при изменении статуса. Тесты проверяют все состояния, отсутствие ложного `away`, обновление без изменения реестра и отсутствие IP/MAC в обычном presence snapshot.


## 0.1.33 — MQTT select + button для удаления телефона

- Упрощена администраторская карточка: удалена дополнительная Ingress iframe-форма и зависимость от HACS `custom:addon-iframe-card`. В дашборде только стандартные сущности `select.dh_presence_app_remove_phone` и `button.dh_presence_app_delete_registration`, видимость карточки ограничена `hass.user.is_admin`, подтверждение — обычный Lovelace `confirmation`.
- App генерирует динамические опции выбора из активных регистраций. Select + отдельная не-retained MQTT-кнопка удаляют **строго выбранную запись** через существующий приватный реестр с общей блокировкой Ingress/MQTT. Выбор очищается до записи; дубли кнопки, retained-команды, неправильные/удалённые устройства не приводят к другому удалению. Tombstones предотвращают повторную регистрацию из legacy-конфига, событие физического ухода не создаётся.
- После удаления App автоматически обновляет Discovery (включая выпадающий список), MQTT-дерево, историю и резидентов. Без дополнительных датчиков, HA helpers, автоматизаций, Recorder-записей, HACS или привилегий.
- **Компромисс:** MQTT не удостоверяет роль пользователя HA. Скрытие Lovelace-карточки — только UI; любой клиент с разрешённой публикацией в нужные MQTT topics может инициировать действие. Для серверной admin-аутентификации сохранена исходная Ingress-страница. Отражено в документации, добавлены тесты retained/duplicate/stale и CI.


## 0.1.32 — Администраторская карточка удаления через select

- Добавлена компактная страница `/admin/delete-phone` в существующем Supervisor Ingress: выбор зарегистрированного телефона из `select`, действие «Удалить регистрацию», явный второй шаг подтверждения и обновление списка после удаления. По умолчанию ничего не выбрано.
- И HTML-страница, и `/api/admin/debug`, и конечный `POST /api/admin/delete-registration` независимо проверяют настоящие права администратора HA. Никаких MQTT-команд для удаления — они не несут удостоверение пользователя.
- В стандартный dashboard и standalone пример добавлена скрытая для не-админов Lovelace-карточка с Ingress select. Для встраивания в дашборд требуется HACS `custom:addon-iframe-card` (ingress-aware); прежняя кнопка «Управление телефонами · администратор» сохранена как альтернатива без этого компонента. На существующей Ingress-странице также доступна та же форма.
- Операции удаления используют уже существующий проверенный backend с атомарным удалением, tombstone и очисткой MQTT Discovery/истории без ложного события ухода. Дополнительные устройства, MQTT entity, Recorder-данные, права или публичный порт не нужны.
- Добавлены тесты серверного ограничения доступа, корректной процедуры select → подтверждение → POST → обновление списка и контракта YAML. Версия App 0.1.32.


## 0.1.31 — IP/MAC в дереве дашборда Home Assistant

- Исправлено место отображения: IP и MAC теперь действительно видны в существующей Markdown-карточке «Зарегистрированные телефоны» на дашборде HA, а не только в Ingress администратора.
- App собирает готовое дерево GPS/Wi-Fi/IP/MAC по зарегистрированным устройствам, отфильтровывает удалённых и исключённых пользователей. IP/MAC явно подписаны как адреса на момент регистрации; HA лишь экранирует и отображает готовый `tree` внутри компактного `<pre style="line-height:1">`.
- Для сохранения Recorder-гигиены добавлен **один** диагностический MQTT-сенсор `sensor.dh_presence_app_registered_phones` (state — число телефонов, attribute `tree`), отдельный retained topic `registrations/tree`. Неизменившееся дерево не публикуется повторно на каждом GPS-опросе; агрегатный бинарный сенсор присутствия не затронут.
- **Изменение разграничения доступа:** IP/MAC в этом MQTT diagnostic state доступны подписчикам MQTT и пользователям HA, имеющим доступ к состояниям. Это не admin-only-содержимое. В системах с более жёстким ограничением данных используйте приватный Ingress; публичную карточку из YAML не устанавливайте.
- Обязательно исключить `sensor.dh_presence_app_registered_phones` из Recorder, объединив настройки с существующим исключением `sensor.dh_presence_app_recent_events`. Настройку Recorder дом задаёт самостоятельно; App не перезаписывает её.
- Тесты миграции визуального контракта, MQTT state, безопасности HTML, отсутствия IP/MAC в обычных сенсорах присутствия и удаления устройства.


## 0.1.30 — Приватное дерево телефонов с IP/MAC

- На существующей административной странице Ingress список зарегистрированных телефонов дополнен моноширинным деревом в стиле PVE (`line-height:1`), с отдельными дочерними ветками GPS, Wi-Fi, IP (рег.) и MAC (рег.).
- Используются уже сохранённые App адреса на момент регистрации, без новых HA-сенсоров и повторного сканирования/ARP. IP/MAC доступны только после серверной проверки реального администратора HA через Ingress `/api/admin/debug`.
- Публичная Markdown-карточка, агрегатные MQTT-атрибуты, события, Recorder и права приложения не меняются. Кнопки удаления и существующая подробная диагностика работают как прежде.
- Дерево формируется из единого ответа App и выводится через DOM `textContent` (никакого `innerHTML`); при ошибке авторизации приватное содержимое очищается. Добавлен тест точных веток, компактной вёрстки и сохранения приватности.


## 0.1.29 — Реестр зарегистрированных телефонов и удаление администратором

- В действующем агрегатном MQTT `residents` добавлены признаки `registered` и подготовленная подпись `registration_label`, без новых HA-сенсоров и передачи IP/MAC в MQTT. Карточка показывает только действительно зарегистрированные и участвующие устройства, исключённых пользователей не раскрывает.
- На странице Ingress администратор HA видит список всех зарегистрированных телефонов с прежней диагностикой IP/MAC и явной кнопкой «Удалить регистрацию» на каждой записи. Действие подтверждается в UI; сервер повторно проверяет подлинного HA-администратора и X-Presence-Request, принимает точный GPS tracker и блокирует неавторизованные запросы. Через Cloudflare администратор может удалить регистрацию; локальный ARP нужен только при регистрации.
- Администраторское удаление удаляет запись и сохраняет tombstone `disabled_trackers` **в существующем** `/data/presence_registrations.json` (schema v2, чтение старого v1 поддержано), чтобы устаревший параметр `residents` не включил удалённый телефон снова после перезапуска. Повторная физическая регистрация с проверкой LAN/MAC снимает tombstone.
- Основной App оперативно синхронизирует реестр, удаляет жильца из Engine/сохранённого состояния, MQTT Discovery, зонного baseline и истории последних событий. Удаление не создаёт ложного события ухода.
- Новая standalone Markdown-карточка и обновлённый стандартный dashboard. Управление телефонами доступно только через проверенный App Ingress, HA-карточка не выполняет команд удаления.
- Регрессионные тесты на права администратора, сохранение удаления после перезапуска, исключение конфигурируемых старых трекеров, отмену ложных переходов и защиту приватных IP/MAC.


## 0.1.28 — Ограниченная история событий в App

- Новая опция Configuration `events_history_limit` (по умолчанию 5; диапазон 1–20). Количество событий задаётся только в App, а не в HA или Markdown.
- App записывает только успешно опубликованные MQTT-события в ограниченный файловый список `/data/presence_event_history.json`. Порядок — по факту публикации, новые первыми; после перезапуска список восстанавливается, при уменьшении лимита обрезается.
- Новая диагностическая MQTT-сущность `sensor.dh_presence_app_recent_events` публикует удерживаемый UI-снимок на `DigitalHouses/Global/dh_presence_app/events/history`. Он содержит `count`, `limit` и готовые к отображению строки `items`; IP/MAC и скрытые поля не публикуются, исключённые жильцы удаляются из истории.
- Home Assistant лишь отображает заранее подготовленные App заголовки и детали через Markdown; новых автоматизаций, шаблонных сенсоров и вызовов `write2log` нет.
- Диагностический сенсор необходимо исключить из HA Recorder (`recorder.exclude.entities`): события уже хранятся App и отдельно доступны как MQTT Event.
- Добавлены отдельная Markdown-карточка, интеграция в дашборд и регрессионные тесты. Версия и файлы конфигурации согласованы.


## 0.1.27 — Уведомления по зонам HA

- Динамические переключатели уведомлений для всех `zone.*` в существующем MQTT-устройстве DH Presence, по умолчанию OFF.
- Машиночитаемые события `zone_enter` / `zone_leave`, полученные по индивидуальному GPS `device_tracker` и штатному разрешению зон Home Assistant; без собственного геофенсинга.
- Сохранение зонного baseline, подавление повторов/ложных событий после рестарта, пропуск неизвестных и недоступных GPS-состояний.
- Миграция настроек уведомлений с v1 на v2, GPS/Wi-Fi сохранены. Старый общий `notify_presence` удалён через MQTT Discovery cleanup.
- Обновлены оба HA-пакета и примеры Lovelace; домашние зонные уведомления подавляют дублирующий GPS-текст.


## 0.1.26 — Portable source tracker cards for all DigitalHouses sites

- The existing `binary_sensor.dh_presence_app_residents_home` MQTT `residents` roster now publishes `gps_tracker` and optional `wifi_tracker` entity IDs from each active registered resident (and configured GPS-only resident); no new HA entities or per-site configuration.
- Read-only, standalone Auto Entities cards select **only** the source GPS and router Wi-Fi trackers currently linked to residents, dynamically for every house.
- The Wi-Fi source link is initialized from the persisted registration even before HA's first successful API poll, then synchronized by the router tracker engine as before.
- Excluded users remain outside the roster. No IP, MAC or registration secrets are published. GPS, Wi-Fi presence decisions, notifications and privileges are unchanged.
- Repository CI parses both YAML cards and evaluates their Jinja templates against multiple unrelated house inventories.

## 0.1.25 — Switch Wi-Fi presence entirely to registered HA router trackers

- All actual Wi-Fi presence is driven by the `wifi_tracker` linked to each resident: HA Core `/api/states` returns the tracker entity, its `source_type: router`, registered matching MAC, and authoritative `home` / `not_home` status.
- Source entity missing, missing binding, invalid MAC, ambiguous duplicate router trackers, HA API failure, or `unknown` / `unavailable` → Wi-Fi UNAVAILABLE, never a verified negative. No fallback to IP, name, ICMP or ARP.
- Normal `home -> not_home` and `not_home -> home` transitions drive existing per-resident MQTT binary sensors, `wifi_in/out` and optional `arrival/departure` in Wi-Fi/Hybrid modes. Baseline on startup does not fabricate events, temporary unknown does not duplicate an arrival.
- No PING/ARP polling at runtime; no detection switches or command subscriptions. Retire switches through existing MQTT Discovery cleanup; remove them from standard dashboard and Lovelace cards.
- The previous `wifi_absence_minutes` option remains accepted for compatibility but **has no effect** on router states. Router `home` never expires due to it.
- GPS pipeline, MQTT topics, notification switches and private registration remain unchanged. One-time local ARP during phone registration is retained, hence same narrowly approved `host_network + NET_RAW` privileges.

## 0.1.24 — Save router Wi-Fi association on Register

- On local Ingress `Register`, look up exactly one HA router `device_tracker` by freshly confirmed phone MAC and save its entity ID as the optional `wifi_tracker` field in the existing private resident registration.
- For already registered GPS devices, re-registration with the same authenticated HA user and verified MAC updates the Wi-Fi link in place without creating another resident or overwriting their original enrollment identity, device name or IP. Another user or a conflicting MAC is rejected.
- Legacy registration schema v1 files migrate transparently without re-enrollment; new optional Wi-Fi field survives atomic writes and restart. If HA or the router tracker is temporarily unavailable, retain the existing Wi-Fi binding without erasing it. Reject multiple HA tracker matches.
- Show stored Wi-Fi tracker and live state in admin diagnostics, and return the associated entity to the registering user. This version only **stores** the association; GPS and running Wi-Fi PING/ARP presence decision, MQTT, notification switches, and network privileges remain unchanged.

## 0.1.23 — Preview router Wi-Fi tracker when selecting a registration device

- On an explicit GPS phone choice in the Ingress registration select, perform a read-only lookup for a router `device_tracker` using the current local phone's freshly verified ARP MAC.
- Match normalized MAC and `source_type: router`, not IP or friendly name. Reject explicitly wired LAN trackers, tolerate absent WLAN metadata while `not_home`; reject ambiguous duplicate MAC matches.
- Show the found entity ID and current state, not-found, ambiguous, or verification error before registration. The MAC belongs to the phone opening the page; choosing a GPS tracker never automatically proves its ownership.
- Preserve the existing registration proof and persistence, GPS, Wi-Fi PING/ARP detection, MQTT, notifications, privacy constraints and privileges. Preview does not change the configured presence source or persist bindings.

## 0.1.22 — Global household PING and ARP detection switches

- Two persisted MQTT switches in the existing DH Presence device: `switch.dh_presence_app_ping` (OFF by default) and `switch.dh_presence_app_arp` (ON by default). Both apply to all registered phones; not separate switches per resident, no additional MQTT device.
- Probe the enrolled private IPv4 address with ICMP PING and/or on-link ARP MAC verification once per minute. With both enabled, either successful check means HOME; only all completed negative checks start the configured `wifi_absence_minutes` absence debounce. Operational failures and ARP MAC conflicts yield UNAVAILABLE rather than a false departure.
- Both OFF disables network monitoring, leaves Wi-Fi sensor UNAVAILABLE, and GPS remains independent. Switching methods immediately re-baselines Wi-Fi without synthetic arrival/departure or duplicate `wifi_in`; settings survive App restarts and MQTT reconnects.
- Preserve the original presence modes, per-resident GPS/Wi-Fi sensors, MQTT event topics, Recorder contract and notification switches. Preserve `host_network` + `NET_RAW` access; add the `iputils-ping` binary without additional permissions.
- Add PING/ARP switches to maintained dashboards and make Wi-Fi source diagnostics and example notification wording method-neutral. No separate HA helpers.
- **Pilot limitation:** PING identifies an IP responder, not an authenticated phone. Keep DHCP address reservations; neither PING nor ARP silence proves radio disassociation (iOS and Android power saving). The selected negative debounce may still produce false absences; do not use for safety-critical automation.


## 0.1.21 — Prevent duplicate Wi-Fi arrival notifications

- Keep the most recent decisive Wi-Fi evidence (verified registered-MAC HOME or completed debounced ARP NOT_HOME) separately from temporary `unavailable` source status.
- Do not emit another `wifi_in` when ARP recovers after a probe error, MAC mismatch or temporary freshness timeout if the previous decisive state was already HOME.
- Preserve a real `wifi_out` followed by `wifi_in` when consecutive valid negative probes establish NOT_HOME, including transitions interrupted by technical probe errors; no fictitious departure is emitted solely because ARP fails.
- Add regression tests for unknown/recovery and real out/in sequences. MQTT event names/topics, Recorder, Home Assistant notification package and owner notification switches are unchanged.


## 0.1.20 — DigitalHouses branding alignment

- Replace `icon.png` (128 × 128) and `logo.png` (250 × 100) with the approved dark-navy neon-blue house + resident + red magnifier design, matching Internet and Recorder Apps.
- Preserve image aspect ratios and the canonical Supervisor App asset paths. Presence runtime behavior, MQTT entity/event contracts, GPS/Wi-Fi logic, notifications and privileges are unchanged.


## 0.1.19 — Cleaner operational logging

- Move scheduled five-minute MQTT Discovery re-announcement messages from INFO to DEBUG, keeping initial synchronization, reconnection and recovery visible at INFO. MQTT payloads, retained QoS1 delivery, and resynchronization cadence are unchanged.
- Log successfully published transient presence events (arrival/departure, GPS, Wi-Fi) at INFO, without publishing extra MQTT events or altering source decisions.
- Classify intermittent HA Core API gateway errors (HTTP 502/503/504) as WARNING rather than ERROR, retain a deduplicated message and log tracker recovery at INFO. Other API failures remain ERROR.
- Report the configured Wi-Fi absence period in startup/mode logs instead of assuming 15 minutes. Startup warnings about experimental ARP and unsupported telemetry remain visible.


## 0.1.18 — MQTT notification switches per household

- Add three independent persistent MQTT switches in the existing DH Presence device: Notify · Presence, Notify · GPS, Notify · Wi-Fi. Defaults ON/OFF/OFF respectively to preserve core arrival/departure notices without duplicating notifications.
- Route `arrival`/`departure`, `gps_in`/`gps_out`, and `wifi_in`/`wifi_out`/`wifi_lost` through HA package `script.write2log` only when their corresponding MQTT switch is ON. MQTT events, source checks, mode decision engine and Recorder are never filtered.
- Persist switches under `/data/presence_notifications.json`, reject stale retained and invalid MQTT commands, publish authoritative retained ON/OFF states and restore on restart.
- Provide updated packages for both `!include_dir_named` and `!include_dir_merge_named`. No additional HA helpers or security privileges.


## 0.1.17 — Hybrid Wi-Fi network-reachability pilot and Mushroom residents

- Interpret only successfully completed local `arping` probes with explicit zero-reply summary as negative observations; route/interface/permission/command errors and conflicting MACs yield `unavailable` and restart the negative streak.
- After 15 minutes of consecutive negative ARP probes (60s poll), publish resident Wi-Fi OFF, `wifi_out`, and in `hybrid` mode override stale GPS HOME with NOT_HOME / `departure`; matching-MAC ARP reply restores HOME / `wifi_in` / `arrival`. Pure GPS mode does not use network absence.
- Publish per-resident status transition timestamps for final decision, GPS, and Wi-Fi in the existing retained MQTT roster (no extra entities). Preserve final decision timestamp across restarts when available; never claim old timestamps are current observations.
- Display dynamically generated per-resident Mushroom cards with localized timestamps. Update administrator diagnostics and truthful `script.write2log` Wi-Fi wording for ARP reachability rather than confirmed radio disconnection.
- **Pilot warning:** an iPhone may sleep through ARP while still associated with Wi-Fi. `off` is network unreachability, not proof that the Wi-Fi toggle is off. Observe behavior for several days before approving this method for presence/alarm control.


## 0.1.16 — MQTT unknown-state fix

- Preserve UNKNOWN/UNAVAILABLE as a distinct state in GPS, Wi-Fi and aggregate MQTT binary sensor value templates. A sleeping iPhone must not be temporarily displayed as a confirmed OFF before HA applies source availability.
- Publish per-source and aggregate availability before each retained snapshot so Home Assistant Recorder does not see a false OFF edge before a true unavailable transition.
- Keep stable SHA-256 resident IDs, person labels, Recorder entity IDs, event contracts, Wi-Fi positive-only evidence, 15-minute grace and the exact approved network privileges unchanged.
- Wi-Fi notifications are driven by the independent MQTT Event entity and the HA notification package, not by every `binary_sensor` state transition. Verify the automation is active before diagnosing a missed notification.

## 0.1.15 — Wi-Fi notifications through write2log

- Emit `wifi_in` on a **real** matching-MAC Wi-Fi reappearance after a startup baseline; never emit a synthetic connection solely because the App restarted.
- Emit `wifi_lost` once when positive Wi-Fi evidence expires after the configured 15-minute window. Preserve UNKNOWN/UNAVAILABLE semantics: no fake `wifi_out`, resident departure or security-mode action.
- Update the native HA notification package to send `script.write2log` for both events with user/device labels from the app and truthful Russian text.
- Extend MQTT Event Discovery with `wifi_lost`; retain `wifi_out` only for future independently verified disconnection. No new HA entities or notification services.
- Add tests for startup suppression, repeated ARP misses, single lost/reconnect notification and lack of false departure.

## 0.1.14 — Wi-Fi positive-evidence pilot

- Use the existing one-time Ingress registration IP/MAC to verify a resident phone locally via fresh active ARP every 60 seconds; no Nmap, NetAlertX, router API or additional integration.
- Matching MAC sets the resident's existing Wi-Fi MQTT binary sensor to HOME and may correct a GPS away observation in hybrid mode. IP mismatch, ARP silence, failed probe or missing registration never produce NOT_HOME.
- After 15 minutes without another positive Wi-Fi reply, stop asserting Wi-Fi HOME and report unavailable, preserving the last confirmed household state. This is **not** verified absence; no wifi_out or last-departure event from silent iPhones.
- Expose non-identifying last successful Wi-Fi observation and probe reason on the existing MQTT resident state and show them in administrator Ingress diagnostics; keep IP/MAC private.
- Fix hybrid decision-time calculations when an iOS GPS tracker reports an old but valid timestamp: current Wi-Fi evidence must not be ignored by time-travelling to GPS report time.
- Preserve GPS as default mode and maintain exact previously approved host_network/NET_RAW privileges. Wi-Fi-only can confirm HOME; absence remains unavailable until independent negative evidence is designed and field-tested.

## 0.1.13

- Compact the native registration and administrator diagnostic interfaces for mobile screens.
- Translate admin GPS, Wi-Fi and registration state labels to Russian status chips.
- Read HA Core configured time zone and show the last GPS report in it; fall back explicitly to UTC.
- Add per-device Copy actions for IP and MAC captured at enrollment, without exporting addresses through MQTT or the normal resident API.
- Keep admin-only server authorization, registration, GPS states and previously reviewed narrow network rights unchanged.

## 0.1.12
- Add administrator-only registration diagnostics in the native Ingress UI: resident, device, GPS tracker, enrollment IP/MAC, GPS state and last reported timestamp.
- Require a verified active Home Assistant administrator group via the existing authenticated Supervisor-to-Core WebSocket for every private debug request. Deny ordinary users and fail closed on errors.
- Remove IP/MAC from the regular resident status endpoint; retain addresses only in the private on-disk registry and secure admin debug API.
- Add an optional admin-only Lovelace launcher and preserve the previously approved narrow LAN/NET_RAW permission scope.
- This is enrollment debugging only: Wi-Fi presence and absence remain unavailable.

## 0.1.11 (draft — single-install acceptance pending)

- Add a native **Supervisor Ingress** interface to the DH Presence Home Assistant App. Installation is through the App Store alone; no `custom_components`, frontend resource, HACS dependency or manual HA configuration is required for registration.
- Use Supervisor-authenticated Ingress user headers to obtain authoritative HA user ID and display name. Extract the actual Core transport peer from the appended proxy chain; require a direct local HA URL.
- Let the phone user explicitly choose their GPS `device_tracker`; do **not** infer user ownership or phone authenticity from a shared HA login. Require a fresh on-link active ARP reply for IP→MAC, never a stale neighbour-cache entry or browser-supplied identity.
- Save the private user/device/IP/MAC binding atomically in the App's own `/data` and auto-enroll its resident with the original stable MQTT identity; the card shows `Имя жильца (Устройство)` without `resident_names`.
- Preserve legacy pilot configuration and prevent excluded HA users from registering. No Wi-Fi absence handling or alarm integration is enabled.
- Host LAN network + only `NET_RAW` are explicitly authorized for this 0.1.11 experimental pilot and guarded by restrictive validator tests; live HAOS client-IP and ARP acceptance is still pending.


## 0.1.10

- Use the last valid HA GPS state and coordinates for a stationary iPhone even after days without new GPS reports; age alone no longer marks the GPS and distance sensors unavailable.
- Publish the genuine source observation timestamp as `gps_reported_at` and the configured age-warning threshold as diagnostic metadata.
- Label aged readings as last-known and show their original report date on both dashboards.
- Manual Refresh succeeds on valid last-known HA observations and acknowledged MQTT publication; it never asserts that the phone acquired a fresh location.
- Keep invalid/unknown source handling and the no-fabricated-events guarantee; leave the Wi-Fi engine unimplemented.
- Cover two-day GPS silence, retained distance, timestamp provenance and repeated observations in regression tests.


## 0.1.9

- Rename the existing MQTT device display name to **DH Presence** without changing its stable identifier, unique IDs or topic base.
- Prefer fresh Home Assistant `last_reported` when available over `last_updated`, which stays unchanged for identical state reports. Stale data remains unavailable and distance still requires coordinates.
- Discover an individual Wi-Fi binary sensor for each registered phone, with source-specific availability deliberately offline until the independently verified Wi-Fi engine exists.
- Add actual runtime Refresh/Check Version controls, runtime-owned operation card, last-refresh and latest-release diagnostics; retain Supervisor installation/restart ownership.
- Bring standalone and full dashboard cards into parity with the unified DigitalHouses control standard.
- Expand regression tests and clarify feature gates.


## 0.1.8

- Use the site's `script.write2log(title, message)` as the only notification action for arrival, departure, verified Wi-Fi connection and disconnection. Remove duplicate `logbook.log` and `persistent_notification.create`; Recorder may retain the original MQTT Event state.
- Allow an optional once-only `resident_names` App Configuration mapping from a registered GPS tracker to a person's name. Persistent Supervisor settings preserve names across App updates; invalid/unregistered/duplicate bindings are rejected.
- Add `user_name` (nullable) and `device_name` to machine events and `user_name` to aggregate resident attributes, retaining legacy `resident_name` and all existing MQTT entity identities.
- Update dynamic Lovelace residents list to show user/device labels; add migration, mapping and notification regression tests.
- No new MQTT devices, independent name service, Wi-Fi engine, or alarm integration.

## 0.1.7

- Arrival/departure machine events now include authoritative `first_arrival`, `last_departure`, `residents_home_after` and `device_tracker` identity, without changing event types, QoS1 or retained-state ordering.
- Strict first/last flags are determined by whole-house transitions in the engine, including multiple resident changes during a single poll and uncertainty-safe handling.
- Update native Russian local HA Package for Recorder-backed Logbook recording and notifications on arrival/departure, and future verified Wi-Fi connection/disconnection.
- Remove the older example's extra invalid top-level package wrapper. No new MQTT Device, entity or invented local notification protocol.

## 0.1.6

- Compare the MQTT Device Discovery envelope and publication sequence with functioning DigitalHouses Internet App and Recorder App.
- After MQTT broker acknowledgment, perform a read-only, rate-limited check through HA Core API for the MQTT integration and Presence entity IDs; report discrepancies in App logs.
- Preserve the native MQTT Device Discovery contract, single MQTT device, resident sensors and non-destructive workflow. An absent entity ID does not conclusively prove discovery rejection when users can rename entities.

## 0.1.5

- Install the owner-approved rectangular glossy blue Presence App banner as `logo.png` (250×100).
- Preserve the already approved square GPS icon and all runtime MQTT/presence behavior unchanged.
- Bump the App metadata version so existing HA installations can apply the artwork through the normal App update workflow.

## 0.1.4

- Instrument MQTT Device Discovery and first state publication with broker QoS1 acknowledgment logging, including the exact topic and component count.
- Retry failed MQTT Discovery automatically and republish on Home Assistant MQTT birth and at bounded five-minute intervals.
- Clarify in diagnostics: broker acknowledgment is distinct from HA MQTT integration accepting a Discovery payload.
- Refresh 3D blue GPS-location icon and catalog banner consistent with other DigitalHouses Apps.
- Add regression tests for topic shape, HA birth triggers and unchanged stable component identifiers.

## 0.1.3

- Remove the unnecessary Supervisor timezone API lookup that can log `Unable to access the API, forbidden` during App startup. Preserve least-privilege `homeassistant_api: true` access to the Core GPS API.
- Use the DigitalHouses local `Asia/Almaty` timezone for startup logs without a privileged Supervisor call.
- Diagnose Home Assistant Core API authorization/status failures separately from MQTT connectivity and report tracker freshness/status changes without revealing coordinates.
- Disclose that experimental telemetry is not implemented even when `telemetry_enabled` is set to true.
- Add regression tests for startup permissions, Core API HTTP error detail and safe telemetry disclosure.

## 0.1.2

- Apply HA MQTT Select mode commands immediately instead of waiting for the next GPS polling interval.
- Ignore retained MQTT commands so reconnecting to the broker cannot overwrite a persisted operator choice.
- Keep one-field tracker registration and App Configuration → MQTT Select precedence unchanged.

## 0.1.1

- Register each resident using a single GPS `device_tracker` entity ID in App Configuration; names are read from Home Assistant tracker attributes.
- Keep one selected phone tracker per resident: logging in on an iPad under the same Home Assistant account does not automatically enroll the tablet.
- Add native MQTT Select `select.dh_presence_app_mode` for immediate `gps` / `wifi` / `hybrid` mode changes via HA Devices/UI.
- Configuration mode is the initial/default choice. HA UI choice persists across App restarts; changing the configuration value explicitly resets the UI override.
- Wi-Fi-only remains unavailable until trusted Wi-Fi evidence is implemented; Hybrid continues with GPS-only measurements. Switching mode never fabricates arrival/departure.
- Retained confirmed state uses tracker-based identity and persistent schema v2. Existing legacy user-ID state is not guessed into a new tracker (safe re-baseline).
- `exclude_users` remains honored for legacy mapped four-field configuration; a tracker-only roster with nonempty `exclude_users` is rejected until an authoritative user-device binding exists.
- Extend unit tests for mode persistence, invalid commands and tracker isolation.

## 0.1.0

- First installable **experimental** Home Assistant App for development and pilot use.
- Supervisor configuration, local Docker build, MQTT broker discovery, version and started-at diagnostics.
- GPS input through Home Assistant Core REST API for explicitly configured Companion trackers.
- Retained per-resident and aggregate logical presence. Unknown/expired GPS data is not interpreted as absent.
- Individual GPS binary sensors and straight-line distance sensors, structured non-retained machine events.
- Durable last-confirmed presence across App restart, safe source freshness handling and MQTT resynchronization.
- Wi-Fi presence, trusted automatic Mobile Companion registration and App UI remain **unimplemented**, and are not used for absence decisions.
- Initial runtime does not connect to DigitalHouses telemetry (unreleased experimental pilot).
