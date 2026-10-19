# DigitalHouses Presence App

**Status: GPS + HA router device_tracker Wi-Fi pilot, version 0.1.36.** Observe router tracker stability before safety-critical automations.

This application belongs to `DigitalHouses/home-assistant-apps/digitalhouses_presence_app` and is installed via **Settings → Apps → App Store**.

## DH Presence · уведомления о жильцах без дублирования

Штатные HA-пакеты отправляют **один** `script.write2log` на реальное логическое прибытие или уход жильца, а не по одному на каждый источник обнаружения. Уведомления о доме управляются `switch.dh_presence_app_notify_zone_<zone_key(zone.home)>`: при `ON` событие `arrival` даёт **«🏠✅ Serzhan прибыл домой»**, `departure` — **«🏠🚪 Serzhan покинул дом»**. Если переход первый/последний для всего дома, в сообщении добавляется **«Статус дома: ПРИСУТСТВИЕ»** / **«Статус дома: ОТСУТСТВИЕ»**; иначе кратко **«Дома: N»**. Эти поля рассчитывает сам App (`first_arrival`, `last_departure`, `residents_home_after`), включая защиту при неизвестном статусе жильца. Изменение режима `gps`/`wifi`/`hybrid` не создаёт ложных событий.

Остальные `zone.*` — только информационные уведомления, включаемые **отдельным переключателем каждой зоны**: **«📍✅ Serzhan прибыл в Urban coffee»** или **«📍🚪 Serzhan покинул Urban coffee»**. События `zone_enter`/`zone_leave` для `zone.home` не создают второго сообщения: дома используется именно агрегированное решение App. Имя берётся из `user_name`, а `device_name` — запасное значение при отсутствии имени.

**Wi-Fi уведомления сохранены**: `switch.dh_presence_app_notify_wifi=ON` разрешает сообщения `wifi_in`, `wifi_out` (и совместимый `wifi_lost`, если когда-либо встретится); `OFF` запрещает их независимо от режимов и переключателей зон. В Wi-Fi уведомлении остаётся устройство в скобках для диагностики. Включённый Wi-Fi канал может осознанно добавить отдельное сетевое уведомление к сообщению о жильце. Источниковые события `gps_in`/`gps_out` продолжают публиковаться App, но **не создают пользовательских уведомлений**. Существующий MQTT-переключатель GPS пока сохраняется для совместимости; этот упрощённый пакет его не использует, изменение MQTT Discovery — отдельный вопрос.

Обновление касается **только пакета автоматизации HA**. Его необходимо заменить в `/config/packages` и применить перезагрузкой автоматизаций или Core (после `ha core check`), без изменения версии DH Presence App. `write2log` и исходный MQTT Event-контракт не меняются.

## HA package: каноническое имя автоматизации уведомлений

Оба поддерживаемых варианта пакета (`examples/packages/dh_presence_app_notification_merge_named_ru.yaml` и `examples/packages/dh_presence_app_notification_local_package_ru.yaml`) задают один и тот же стандарт:

- **Технический `entity_id`:** `automation.dh_presence_notifications` (английский).
- **`id` автоматизации:** `dh_presence_notifications` (английский, уникальный).
- **`alias` в YAML:** `DH Presence Notifications` (английский, определяет исходный `entity_id` новой сущности).
- **Имя для пользователей:** `DH Presence · Уведомления` через штатный `homeassistant.customize` внутри пакета (русский).

Автоматизации Home Assistant не поддерживают декларативный `entity_id` как поле YAML; при первоначальном создании используется `alias`, а зарегистрированный `entity_id` закрепляется за уникальным `id`. Поэтому для миграции со старого `automation.dh_presence_uvedomleniia` изменён именно `id` пакета: прежняя автоматизация снимается с загрузки, новая получает английский `entity_id` после проверки конфигурации и перезапуска HA. **Это осознанная разовая смена уникального идентификатора только автоматизации HA**; MQTT-контракт, события, скрипт `write2log` и версия App не меняются.

Уже существовавшая запись старого `entity_id` может оставаться неактивной в HA Entity Registry. Не редактируйте файлы `.storage` вручную и не создавайте вторую автоматизацию для «исправления» имени. После миграции проверьте, что новый `automation.dh_presence_notifications` имеет состояние `on` и прежний `automation.dh_presence_uvedomleniia` отсутствует среди **активных** автоматизаций; при необходимости историческую запись отдельно очищают через поддерживаемый механизм Entity Registry. Иные сайты получают тот же канонический ID с нуля. Если канонический ID уже занят чужой сущностью, устраните конфликт до миграции.

## Lovelace: относительное время статуса жильцов

Отдельная карточка жильцов `examples/lovelace/presence_residents_auto_entities_ru.yaml` и поддерживаемый `examples/lovelace/dh_presence_app_dashboard.yaml` показывают `Итог`, `GPS` и `Wi-Fi` вместе с **возрастом текущего состояния**, например `1 минуту назад`, `2 часа назад`, `1 день назад`. Точная дата/время из карты жильцов убрана; исходные поля `status_changed_at`, `gps_changed_at` и `wifi_changed_at` продолжают поступать из App.

Вычисление выполняет сам шаблон Mushroom через `as_timestamp(now())`, поэтому текст естественно обновляется при каждом минутном обновлении шаблонов HA. Русские формы для минут, часов и дней реализованы прямо в Jinja; при отсутствии времени выводится `—`, при возрасте меньше минуты — `только что`. Упоминание старого ARP-режима удалено: состояние Wi-Fi определяется интеграцией роутера.

**Это только изменение Lovelace YAML.** Версию DH Presence App менять не нужно; уже настроенную карточку в пользовательском дашборде следует заменить YAML из репозитория. Не требуется новое MQTT-состояние, запись в Recorder или дополнительная автоматизация.

## Локальное время без смещения (0.1.36)

Под GPS и Wi-Fi `Статус с` теперь отображает **только локальные дату и время HA**: `19.10.2026 01:12`. Часовой пояс берётся из настройки `time_zone` Home Assistant и применяется **внутри App** до формирования MQTT `tree`. Ни `+05`, ни `UTC`, ни другие текстовые обозначения зон не добавляются. На летнем/зимнем времени HA применяется корректное смещение, но не выводится в дереве.

Если App временно не может определить часовой пояс HA, он пишет `местное время недоступно` вместо потенциально неправильного UTC и перепроверяет конфигурацию примерно раз в пять минут. Отсутствующий timestamp самого источника по-прежнему `нет данных`, отсутствие привязанного Wi-Fi — `не применимо`.

Обновить App до **0.1.36**. YAML карточки не требуется менять: App продолжает публиковать тот же диагностический `sensor.dh_presence_app_registered_phones`. Сохраняйте исключение этого сенсора из Recorder.

## Время текущего статуса в дереве (0.1.35)

Дерево `sensor.dh_presence_app_registered_phones` под каждой веткой GPS и Wi-Fi содержит ещё одну вложенную строку, например `│  └─ Статус с · 19.10.2026 01:12 +05`. Это **время последнего изменения состояния данного источника**, взятое из уже существующих App `Resident.gps_changed_at` и `Resident.wifi_changed_at`. Ни Recorder, ни HA Markdown/Jinja не вычисляют его, время последнего GPS/Wi-Fi-пакета не подменяет время смены статуса.

App конвертирует время в `time_zone` из HA Core config (обычно Asia/Almaty для домашних объектов). Если часовой пояс отсутствует/ошибочен — используется явная отметка `UTC`. При неизвестном timestamp — `нет данных`; если Wi-Fi не привязан — `не применимо`. В момент первого достоверного наблюдения статус получает отметку; переход в `Недоступно` тоже отмечается, без выдуманного физического ухода.

**Обновление:** установить App **0.1.35**. YAML стандартного дашборда / отдельной Markdown-карточки не меняется. Кеш MQTT подавляет неизменённое дерево; его `tree` атрибут меняется только при реальных переходах/изменениях регистрации, а не каждую секунду. Существующее исключение `sensor.dh_presence_app_registered_phones` из Recorder обязательно сохранить.

## Состояния GPS и Wi-Fi в дереве (0.1.34)

Дерево `sensor.dh_presence_app_registered_phones` теперь показывает подтверждённое состояние **каждого источника отдельно**, сохраняя названия трекеров: `🟢 Дома` (`home`), `🟠 Не дома` (`not_home`), `⚪ Недоступно` (`unavailable`). Если Wi-Fi-трекер не привязан, выводится `⚪ Не привязан`, даже если остальной телефон дома. Иконка телефона изменена с `📱` на `📲`.

Источник статусов — существующий `Resident.gps` и `Resident.wifi` в App Engine; состояние GPS и Wi-Fi **не подменяется итоговым присутствием**. Дерево пересобирается при штатной публикации MQTT snapshot, поэтому статусы обновляются после очередного опроса источников (обычно раз в 30 с) без повторной регистрации. MQTT-кеш подавляет одинаковые сообщения.

Новых сенсоров, шаблонной логики HA и сущностей Recorder нет. **Сохранить исключение `sensor.dh_presence_app_registered_phones` из Recorder:** его атрибут `tree` теперь дополнительно меняется при переходах GPS/Wi-Fi. YAML существующей Markdown-карточки менять не нужно; обновить App до **0.1.34**, а отображение останется через тот же компактный HTML `<pre style="line-height:1">`.

## MQTT select + button: удаление телефона (0.1.33)

В **том же MQTT Device DH Presence** добавлены две управляющие сущности:

- `select.dh_presence_app_remove_phone` — динамический список регистраций «Имя (телефон) · GPS device_tracker». Начальное и сброшенное значение — «— Выберите телефон —».
- `button.dh_presence_app_delete_registration` — команда App удалить **выбранный** телефон.

**App полностью владеет логикой:** принимает `select`, проверяет его наличие в реестре и исключениях, по отдельному нажатию кнопки атомарно удаляет регистрацию и записывает tombstone в прежний `/data/presence_registrations.json`. Затем синхронизирует состав жильцов и MQTT Discovery, убирает устройство из дерева и выпадающего списка и сбрасывает выбор. Никакого ложного ухода или входа в зоны. Дублированное, некорректное и retained MQTT-нажатие не удаляет следующий телефон. После перезапуска App выбор пустой. Дополнительных датчиков, HA helpers, автоматизаций и Recorder-записей нет.

[Администраторская Lovelace-карточка](examples/lovelace/presence_admin_remove_phone_card_ru.yaml) и поддерживаемый дашборд отображают **обычные HA select и button** и запрашивают подтверждение перед нажатием. Уже используемый `custom:button-card` скрывает карточку от не-администраторов; **Ingress iframe / HACS addon-iframe-card больше не нужны**. Установить App 0.1.33 и обновить YAML вручную. Предыдущая iframe-форма из 0.1.32 удалена. Старый независимый административный Ingress для просмотра/удаления регистраций остаётся доступен через Apps.

**Граница безопасности:** стандартный MQTT не удостоверяет роль пользователя Home Assistant, отправившего команду. Скрытие карточки `hass.user.is_admin` ограничивает *видимость*, **не запрещает** пользователю с доступом к MQTT или разрешённым HA services отправить `button.press` и команды select. Использовать только с доверенными пользователями/настроенными ACL брокера. Для удаления с реальной серверной проверкой роли администратора использовать существующий native Supervisor Ingress. Не утверждать, что MQTT-удаление защищено per-user HA authorization.

## IP/MAC in the Home Assistant dashboard tree (0.1.31)

The previous 0.1.30 feature put enrollment IP/MAC **only inside administrator Ingress**, which did not change the **Lovelace Markdown card**. Version 0.1.31 addresses the actual dashboard request. The App, not HA, generates a fully formatted `├─/└─` phone tree with GPS, Wi-Fi, **IP (рег.)**, and **MAC (рег.)** branches. It publishes this display-only read model through one MQTT diagnostic sensor, `sensor.dh_presence_app_registered_phones`, state = registered count, attribute `tree`. The maintained dashboard and [standalone Markdown card](examples/lovelace/presence_registered_phones_markdown_ru.yaml) only show this text in a compact PVE-style `<pre>`, with HTML escaping. Deleted/excluded phones are omitted. The addresses describe the moment of enrollment, not current network attachment.

**Security tradeoff:** the dashboard is backed by MQTT. Unlike the private admin-only Ingress, registration IP/MAC in this diagnostic topic are readable by authorized MQTT subscribers and HA users who can access entity state; hiding the Markdown card from non-admins would not enforce backend access control. On deployments where private IP/MAC must stay admin-only, do not deploy this public tree; use the verified private Ingress view instead. The existing aggregate `binary_sensor.dh_presence_app_residents_home` and machine events continue to exclude IP/MAC.

**Recorder hygiene — required per home:** merge the following with existing Recorder settings; do **not** replace other excludes:

```yaml
recorder:
  exclude:
    entities:
      - sensor.dh_presence_app_recent_events
      - sensor.dh_presence_app_registered_phones
```

This prevents diagnostic strings containing IP/MAC from being repeatedly stored in HA Recorder. The new retained MQTT topic `DigitalHouses/Global/dh_presence_app/registrations/tree` changes only when the registration roster, associated tracker or device name changes (or on a new App publish session); normal GPS polling does not republish unchanged tree text. The App does not modify HA Recorder configuration.

To apply: install App `0.1.31`, update the manually installed phone Markdown YAML from the repository, and apply the Recorder exclusion. An App update does **not** automatically replace manually pasted Lovelace YAML.

## Private administrator phone tree (0.1.30)

The App's **existing administrator-only Ingress view** (the `Управление телефонами · администратор` dashboard launcher or **Open Web UI**) now includes a compact PVE-style native `<pre>` phone tree. Every enrolled phone shows its registered name/device, GPS tracker, Wi-Fi tracker, **IP (рег.)** and **MAC (рег.)** as separate child branches. Network addresses are verified **registration-time snapshots**, not proof of current IP or Wi-Fi connectivity. The existing per-device copy controls, diagnostic states and delete-registration actions remain available below the tree.

**Access boundary:** the personal IP/MAC tree lives only in the authenticated Ingress page; the backend verifies current HA administrator role on every `/api/admin/debug` request. It is not possible to safely put these private values in the ordinary Home Assistant MQTT Markdown tree without publishing them to other HA/MQTT users and potentially Recorder. Therefore the public registered-phones Lovelace tree stays GPS/Wi-Fi-only. No additional entities, helper sensors, MQTT state fields, Recorder history or extra privileges are introduced. The private tree uses `textContent` and a fixed single-line `line-height:1` layout.

## Registered phones and administrator deletion (0.1.29)

The existing MQTT resident roster exposes only the enrolled, eligible phone's stable source tracker IDs and two new **non-secret** fields: `registered` and the App-prepared `registration_label`. An App-configured legacy GPS tracker **without** a verified Ingress enrollment is not misrepresented as registered. The maintained dashboard contains a portable [registered phones Markdown card](examples/lovelace/presence_registered_phones_markdown_ru.yaml), which simply reads those fields. This does not create new entities or counters; no registration IP/MAC is published via MQTT or Recorder. Phones excluded through `exclude_users` are absent from the public roster.

**To delete a phone:** open **DH Presence → Open Web UI** or use the dashboard's admin launcher **Управление телефонами · администратор**. The existing administrator-only Ingress section now lists all registrations (including private enrollment IP/MAC) and provides a per-phone **Удалить регистрацию** button. Confirm the exact user/device/GPS tracker. The backend independently checks authenticated Supervisor Ingress identity, live HA administrator membership and the action-specific request header; non-admins cannot delete. Unlike phone registration, administrative removal is allowed through an existing remote Cloudflare HA session. No direct ARP probe is attempted for deletion.

Deleting a registration immediately persists its GPS tracker as disabled in the **same** registration file (`/data/presence_registrations.json`, schema v2; old v1 files migrate on write). This prevents a legacy manually configured `residents:` option from re-enrolling the phone on App restart. The running App reconciles its roster (normally within its five-second registration check), removes the resident from MQTT Discovery/current-state, zone baseline and local recent-event history, and **does not synthesize a departure event**. Re-registration from the physical phone on direct home LAN, with fresh MAC verification, explicitly clears the disabled marker and starts a new UNKNOWN baseline. No second deletion registry, HA helper or automation is introduced.

Admin-only IP/MAC remain in the private native Ingress diagnostics; the public Lovelace card is intentionally read-only. This product continues to use the Home Assistant App's standard single MQTT Device and privileges.

## Latest events (0.1.28, App-owned)

The App maintains a private durable **bounded ring of MQTT machine Events confirmed published** (all source, overall and GPS zone transitions) at `/data/presence_event_history.json`. Set `events_history_limit: 5` under **Settings → Apps → DigitalHouses Presence App → Configuration**. Accepted range: 1–20; changing the option and restarting the App trims the ring to the new limit. Restart and MQTT reconnection do not fabricate or replay machine events. Excluded/unregistered residents are removed from stored history when the App processes its eligible roster.

The App publishes the display snapshot via the existing MQTT Device's diagnostic `sensor.dh_presence_app_recent_events`, retained topic `DigitalHouses/Global/dh_presence_app/events/history`. Its state is the number of stored entries; attributes contain `count`, `limit` and **already prepared** `items` (`title`, `details`, `timestamp`). The timestamp denotes when App acknowledged publication of the machine Event; GPS source observation timestamps are preserved in the original machine Events and the private durable journal. Names and zone labels in the UI summary are bounded to 120 characters; IP/MAC/token and unlisted machine-event fields are never copied into this history.

The [recent-events Markdown card](examples/lovelace/presence_recent_events_markdown_ru.yaml) only iterates the supplied items and formats timestamps in the browser's Home Assistant timezone; it does **not** collect, process, classify or store events. The maintained four-column dashboard includes the same card in the Notifications column. No HA helper, template sensor, history automation or extra notifications are required. Installation of a new App release does not automatically replace previously pasted dashboard YAML.

**Recorder requirement:** exclude the UI history sensor from Recorder, since every new Event changes its attributes. Merge this entity into your existing Recorder exclusion list, for example:

```yaml
recorder:
  exclude:
    entities:
      - sensor.dh_presence_app_recent_events
```

Do not replace or overwrite unrelated Recorder include/exclude settings. The original `event.dh_presence_app_event` retains its existing independent Recorder policy.

## Dynamic source tracker cards (0.1.26)

The existing MQTT roster attribute `residents` on `binary_sensor.dh_presence_app_residents_home` includes two source entity IDs for each participating resident: `gps_tracker` (the selected Companion `device_tracker`) and `wifi_tracker` (the router's `device_tracker` linked at registration, if present). These are **entity references**, not extra sensors. Excluded HA users do not appear. IP/MAC registration data is not published to MQTT or Recorder, but is available in the private administrator-only Ingress diagnostics card inside Home Assistant.

Two portable Lovelace **Auto Entities** YAML cards automatically display only active DH Presence source trackers:

- [GPS trackers](examples/lovelace/presence_gps_trackers_auto_entities_ru.yaml)
- [Wi-Fi router trackers](examples/lovelace/presence_wifi_trackers_auto_entities_ru.yaml)

Paste each into a separate **Manual YAML** Lovelace card. Both work unchanged on every DigitalHouses site with DH Presence 0.1.26+ and HACS `custom:auto-entities` installed. Newly registered residents and new router bindings appear without manually editing entity IDs. Wi-Fi unlinked residents are omitted from the Wi-Fi card, but still appear in the GPS card. Entity states `home`, `not_home`, and `unavailable` are not filtered, so the list tracks registration membership, not current connection.

## Zone person count card (dashboard-only)

The portable [zone count Auto Entities card](examples/lovelace/presence_zones_auto_entities_ru.yaml) lists all Home Assistant `zone.*` entities in the **Жильцы** column of the maintained dashboard, with their native numeric states (persons in each zone, including zones with **0** persons). There are no per-house zone names, filters for only occupied zones, extra helpers, or new DH Presence MQTT entities.

**Scope:** Home Assistant computes each `zone.*` state from its `person` entities. This is *not* a count of DH Presence registrations or raw GPS/Wi-Fi `device_tracker` entities. For the displayed number to include a DH Presence resident, Home Assistant must have a corresponding `person` entity correctly associated with that resident's tracker. This card does not change tracking, registration, or the Presence App version.

## Stored router Wi-Fi tracker (0.1.24)

From the local Ingress phone registration UI, selecting a GPS tracker previews a matching HA router `device_tracker` by the phone's actively ARP-verified MAC. Pressing **Зарегистрировать** now persists the matched `wifi_tracker` on the same resident registry record. On an existing registered GPS tracker (same authenticated user, same verified MAC), only the Wi-Fi link is updated; registration fields are preserved. If no unique router tracker is available, GPS registration still works and a previously stored Wi-Fi link is retained. Admin debug displays the linked entity and its current HA state. Older registry files load without changes.

**Since 0.1.25:** The stored association directly drives Wi-Fi presence through the HA router tracker; GPS remains independent.

## HA router tracker Wi-Fi presence (0.1.25)

After phone registration has saved a unique `wifi_tracker`, DH Presence uses **only** the current HA router `device_tracker` state for Wi-Fi presence. It verifies source `router`, registered MAC and unique association, then maps `home` / `not_home` to the original per-resident MQTT Wi-Fi binary sensor and `wifi_in` / `wifi_out` events. In Wi-Fi/Hybrid modes, those observations drive the existing overall presence logic. An unknown, unavailable, missing, duplicated or mismatching router tracker always yields Wi-Fi UNAVAILABLE, **not** an absence. GPS processing is unchanged. HA router trackers, not IP/hostname/ICMP/ARP, are the Wi-Fi evidence.

Periodic PING and ARP presence polling and their MQTT control switches have been removed. Existing switches are removed using MQTT Discovery cleanup and must be removed from locally customized dashboards. The existing config key `wifi_absence_minutes` is accepted for compatibility with installed App options but is ignored; router status is not debounced and does not expire due to that key. One-time active ARP registration proof still requires `host_network` and `NET_RAW`.

## Historical PING/ARP behavior (0.1.17–0.1.24; retired)



Every 60 seconds the App probes the enrolled private LAN IP with direct `arping`. A valid reply from the exact registered MAC means Wi-Fi HOME. A *completed* ARP probe with **zero responses** for 15 consecutive minutes (configurable) means the device is not reachable by ARP: Wi-Fi binary sensor **OFF**. This may generate `wifi_out` and in `hybrid` mode an actual departure / last-person-left decision even if the last iOS GPS reading was HOME. A later verified MAC response restores HOME. Default `gps` mode remains independent of Wi-Fi absence.

**Important limitation:** iOS may not answer ARP during sleep while still on Wi-Fi. Wi-Fi OFF here means *not detected by active LAN probe*, not proof of Wi-Fi being switched off. On-link route, execution or permission failures and MAC conflicts produce `unavailable` instead, reset the absence timer and never produce a negative presence transition. No Nmap, router, NetAlertX or extra HA tracking entity is required.

The maintained dashboard dynamically creates a Mushroom card for each configured resident (name + device): final presence status and its transition timestamp; GPS status/transition timestamp; Wi-Fi status/transition timestamp. Unknown timestamps render as a dash. All timestamps originate in the App's existing MQTT resident roster, and are shown in the browser's local timezone. There is no manual per-person YAML configuration and no IP/MAC exposed in MQTT.

## Historical PING/ARP detection switches (0.1.22–0.1.24; retired)

Older versions used two persisted MQTT switches on the DH Presence device; both are removed starting in 0.1.25:

- `switch.dh_presence_app_ping` — ICMP echo to the registered private IP; default OFF.
- `switch.dh_presence_app_arp` — active ARP with exact registered MAC verification; default ON (legacy behavior).

Both ON: **any successful method → Wi-Fi HOME**. Only when **both** enabled checks finish with explicit no-reply does the configured `wifi_absence_minutes` negative debounce run; probe errors or ARP MAC conflicts are inconclusive. If both OFF, Wi-Fi monitoring is disabled and its sensors report UNAVAILABLE (not OFF). GPS mode stays independent; Hybrid falls back to GPS during Wi-Fi uncertainty. Switching either method from HA establishes a new Wi-Fi baseline without creating synthetic events; switches are stored in `/data/presence_probes.json`. PING and ARP are checked every 60 seconds on each enrolled phone. These are **detection** switches, not the separate Notify · Wi-Fi switch.

**Reliability:** An ICMP reply proves that *something* answers at the enrolled IP, not the MAC or phone identity. Keep DHCP reservations for all registered phones, especially PING-only. If ARP detects a MAC mismatch, even a positive PING does not prove the registered phone is present. Failed commands and ambiguous responses are UNKNOWN, not confirmed absence. Phones may ignore both ICMP and ARP while sleeping. A completed no-reply debounce only means LAN reachability was lost; it is **not proof of Wi-Fi disassociation**. Wi-Fi-only/Hybrid absence should not be used for security until field-tested.

In 0.1.25, the maintained Lovelace card and dashboard no longer expose PING/ARP switches. Both notification example packages were updated for explicit router disconnection. **Existing locally installed HA packages must be replaced manually**, since App upgrades do not install HA packages.

## Zone and source notification switches (0.1.27)

The DH Presence MQTT device provides persisted notification switches for each discovered Home Assistant `zone.*` and two independent source switches: `switch.dh_presence_app_notify_gps` and `switch.dh_presence_app_notify_wifi`. Zone switches are generated dynamically, default to OFF, and have stable keys derived from the zone entity ID. The old `switch.dh_presence_app_notify_presence` is retired and removed through MQTT Discovery cleanup. Switching notifications OFF changes only local message delivery; it does not filter events, change presence calculations, or disable Recorder.

**Why the App owns zone transitions:** Native Home Assistant zone triggers can also process non-participating users, including administrators. DH Presence must restrict zone events to its enrolled/eligible resident roster and apply `exclude_users` before zone transition processing. The App reads Home Assistant's already-resolved GPS device-tracker zone state (it does not calculate geofences), maintains a per-resident transition baseline and emits `zone_enter`/`zone_leave` machine events for included residents only. This filtering is part of the App's public zone contract, not a reason to add a second zone location engine.

The local HA notification packages consume `event.dh_presence_app_event` via `event.received → trigger.id → choose → script.write2log`. Only `arrival` / `departure` generate home resident notifications (gated by the `zone.home` switch); `zone_enter` / `zone_leave` generate informational notices for non-home zones only (each gated by its zone switch). The independent Wi-Fi switch gates source notifications regardless of the selected presence mode. `gps_in` / `gps_out` remain App machine events only and do not create a second resident notice. App upgrades do not automatically replace locally installed HA packages or Lovelace YAML.

**Wi-Fi always means the local home's network (`zone.home`).** Router `device_tracker` state is the Wi-Fi evidence for the HA installation site; remote HA access over Cloudflare is not proof of local Wi-Fi presence. GPS alone covers office and other HA zones. Wi-Fi OFF means absent from the tracked local router network, not proof that the resident physically left home.

## Pilot capabilities

- Registers each resident with **one** explicit GPS `device_tracker` from that resident's phone. Names come from HA; multiple Companion devices signed in as the same user are not automatically included.
- The startup mode is configured in the App's Configuration tab and can be switched live in HA via `select.dh_presence_app_mode` (on the same MQTT device). HA selection survives restart, while a changed config default takes priority.
- Logs a confirmed MQTT Discovery publish on `homeassistant/device/dh_presence_app/config`, retries failures, and re-announces on HA birth and periodically. MQTT broker delivery does not prove HA accepted a payload. Version 0.1.6 additionally checks HA Core API for the MQTT integration and expected Presence entities, and logs the result. If none appear, check HA MQTT integration logs for schema errors.
- Publishes one MQTT Device named **DH Presence**, aggregate `binary_sensor.dh_presence_app_residents_home`, individual GPS and Wi-Fi binary sensors and numeric straight-line distance, version/started diagnostics and one MQTT Event.
- Persists last confirmed logical resident states under `/data`; expired/missing sources never become `not_home`. A never-confirmed aggregate remains unavailable.
- Excluded users never create entities.
- MQTT events are non-retained; HA notification packages own human-facing messages.

**Staged single-install pilot in 0.1.11:** Native **Supervisor Ingress**
registration UI is included in the same Home Assistant App. No Core adapter,
custom integration, frontend resource or `configuration.yaml` edit. The
user opens the App's **Open Web UI** button, selects the phone GPS tracker
while using the phone on direct home Wi-Fi, and enrolls. Supervisor supplies
the authenticated user ID and display name; the App validates a directly
connected client IP with a fresh ARP reply and stores the MAC locally.
**Not implemented:** automatic Companion device-to-WebSocket attestation or alarm integration. Continuous Wi-Fi presence now comes from the HA router tracker (0.1.25), while the GPS pipeline remains unchanged.


## Administrator-only network diagnostics (0.1.12)

The native DH Presence interface includes a private **Диагностика регистрации** card. In 0.1.13 the view is compact on phones, status labels are in Russian, the last GPS report uses the HA-configured timezone (explicit UTC fallback), and saved IP/MAC fields have one-tap Copy buttons. Only an authenticated Home Assistant administrator can see all resident registrations, including the name, device, tracker, IP and MAC recorded at registration, current GPS state and last GPS report time. This does not assert current Wi-Fi reachability.

The App authorizes each private request server-side by using its existing Supervisor token to query Home Assistant Core's administrator list and match the Ingress user ID. Ordinary residents get HTTP 403; authorization failures get 503 without any IP/MAC payload. The ordinary `/api/status` response no longer includes addresses. MQTT/Recorder still do not publish them.

An optional [Lovelace administrator debug launcher](examples/lovelace/presence_admin_debug_card_ru.yaml) uses `hass.user.is_admin` to hide itself for non-admins. The full dashboard and canonical Presence card also include this launcher. No separate integration or additional credential is required.

## Presence Lovelace card

The maintained [Russian Presence card](examples/lovelace/presence_app_card_ru.yaml) is a `vertical-stack` that displays the aggregate “Мы дома” state, the actual `select.dh_presence_app_mode` control, and **all** configured residents with their per-phone GPS availability and distance. Residents are resolved dynamically from the shared MQTT binary sensor's `residents` attribute: adding another `device_tracker` to the App configuration does not require editing the card.

The maintained [four-column dashboard YAML](examples/lovelace/dh_presence_app_dashboard.yaml) organizes the status and phone registration, dynamic resident Mushroom cards plus GPS/Wi-Fi source trackers and native HA zone person counts, independent notification switches, and a temporary debug entity list into separate `sections` grids. It shares the canonical status-card JavaScript and action behavior, without embedding the entire standalone vertical-stack card. Both examples require `custom:button-card >= 5.0`, Mushroom and **[Auto Entities](https://github.com/thomasloven/lovelace-auto-entities)** (install through HACS before opening the dashboard). The universal `auto-entities` section matches every entity containing `dh_presence_app_` (including button/select/event entities) plus the optional native Supervisor update entity. New residents appear without editing YAML. Actions remain at the top in the standard chips and are also accessible as native rows in the entity list; the Refresh stamp chip distinguishes no manual refresh from a completed one. Paste the *card* file under a dashboard **Manual YAML card**; paste the *dashboard* file when editing the complete dashboard view in YAML.

**UI update indicator:** The main status header, warning icon, and idle message use both the Supervisor-owned `update.digitalhouses_presence_app_update` state and the App's own release-check binary sensor. The native Supervisor `update` entity is authoritative for the **Новая версия** install chip, which only appears when installation is actually offered; its `latest_version` attribute takes precedence for the version arrow when a native update is available. An ordinary App release check may detect a newer published release before Supervisor makes it installable, and must not activate a nonworking install chip. During installation the Supervisor's real `in_progress` and optional percent drive the progress label. Foreground operations and errors take priority in the status card.

**Card installation is separate from App installation.** Existing manually pasted Lovelace YAML does not update when upgrading DH Presence in the HA App Store. To adopt a UI fix, replace the Manual YAML card with the latest [standalone YAML](examples/lovelace/presence_app_card_ru.yaml), or update the full [dashboard YAML](examples/lovelace/dh_presence_app_dashboard.yaml). No app configuration change or app version bump is needed for dashboard-only fixes.

The mode selector is functional. The status and resident rows are observational. The App exposes genuine operation entities (`sensor.dh_presence_app_card`, `button.dh_presence_app_refresh`, `button.dh_presence_app_check_updates`, refresh-state and version diagnostics) following the [DigitalHouses Unified Status Card](../docs/standards/UNIFIED_PRODUCT_STATUS_CARD_STANDARD.md). Refresh reads currently stored HA tracker states immediately and succeeds when all configured GPS sources have valid last-known evidence and the MQTT state was published. This does not request a new GPS fix from iOS. Version checks query stable product-tagged GitHub Releases. Installation/restart remain Supervisor-owned. GPS last-known `home`/`not_home` and distance remain available even after days without iOS movement; this is **last-known evidence, not live GPS**. Each GPS sensor exposes actual `gps_reported_at`, and the card shows the report time and labels aged results as last-known. An unknown/unavailable/malformed source is still unavailable, and the last confirmed logical state is retained without inventing an arrival/departure. `last_reported` is preferred to `last_updated`; polling HA never fabricates a new report. Distance requires last-known valid coordinates. Each registered phone also gets a Wi-Fi binary sensor sourced exclusively from the linked HA router tracker. If no tracker is linked or HA cannot confirm the source, that Wi-Fi sensor reports unavailable rather than inventing absence.

## Registration launcher card (optional)

The maintained Russian dashboard includes a **Регистрация телефона**
`custom:button-card` launcher. A standalone card is available as
[`presence_registration_card_ru.yaml`](examples/lovelace/presence_registration_card_ru.yaml).
No separate HA frontend resource or adapter is needed.

- On released `0.1.10`, the launcher states registration is unavailable and
  **does not navigate**. It does not claim a mobile registration endpoint exists.
- Once `0.1.11+` has passed network/Ingress acceptance and is installed,
  the launcher opens the native Supervisor Ingress path
  `/app/8133339d_digitalhouses_presence_app`.
- Registration is still performed inside the App's own Ingress page on the
  phone's local Home Assistant connection, not via Lovelace Javascript.

## One-click native phone registration (0.1.11 pilot)

1. Install/update **DigitalHouses Presence App** through the normal HA App
   Store. No extra packages, integration, HACS card or files are needed.
2. On the **phone being enrolled**, connect to home Wi-Fi and open Home
   Assistant through its direct local URL, then open **DH Presence**
   in the HA sidebar (native Ingress). An administrator can also use
   **Settings → Apps → DH Presence → Open Web UI**.
3. Select the phone's existing GPS tracker and press **Зарегистрировать**.
   The HA user name comes from authenticated Supervisor Ingress headers;
   IP comes from the verified HA Core transport hop, and MAC from a fresh
   on-link active ARP response, **not** from manually typed fields.
4. The App stores the binding under `/data/presence_registrations.json`,
   enrolls the resident automatically, and the MQTT roster shows
   `Имя жильца (Устройство)`. Registered residents remain across restarts.
5. A second phone or iPad under the same HA account must be chosen explicitly
   and is never auto-enrolled. Admin exclusions require verified HA user ID.

The included Ingress UI is sufficient for registration and listing enrolled
phones. The optional Lovelace card uses Mushroom, button-card and Auto
Entities for advanced monitoring; it is **not a prerequisite** to using the
App. No manually filled `resident_names` is required for newly enrolled
phones; that configuration remains only for existing pilot migrations.

**Security boundary:** Home Assistant Ingress asserts user identity, but
does not by itself cryptographically prove which of a user's devices sent
the request. An unexpected proxy/VPN/Cloudflare route, no LAN ARP reply or
a missing selected GPS tracker fails registration. `host_network` and
`NET_RAW` for one-off ARP are now **explicitly approved for the 0.1.11 experimental pilot**, guarded by an exact-capability repo validator and negative tests. Live on-site HAOS Ingress/ARP acceptance still needs to be performed after installation. No alarm control or negative Wi-Fi evidence is
enabled by registration.

## Legacy resident name mapping (migration only; do not configure anew)



Add an optional `resident_names` mapping under **Settings → Apps → Presence App → Configuration**; the original `residents` list remains unchanged. Example:

```yaml
residents:
  - device_tracker.13promax_sky
resident_names:
  - device_tracker: device_tracker.13promax_sky
    user_name: "Имя жильца"
```

Each entry explicitly associates **one registered tracker** with a person's name. Supervisor retains this App configuration across restarts and upgrades; there is no second naming table in HA Packages and no runtime `person` lookup. The device label still comes from the tracker's HA friendly name. Unmapped residents show their device names alone. Invalid/duplicate/unregistered associations fail validation. Stable resident keys, MQTT entities and confirmed presence remain unchanged.

## Recorder and notifications package

[The local Russian HA package](examples/packages/dh_presence_app_notification_local_package_ru.yaml) processes the existing `event.dh_presence_app_event` directly. For enabled `arrival`, `departure`, non-home `zone_enter` / `zone_leave`, `wifi_in`, `wifi_out` and legacy `wifi_lost`, it calls the site's existing `script.write2log` **once** with `title` and `message`; source-only `gps_in` / `gps_out` never send duplicate notices. No duplicate `logbook.log`, `persistent_notification.create` or extra MQTT device is introduced. The MQTT Event entity can be stored by Home Assistant Recorder, subject to the local Recorder filters and retention. Whether `write2log` also logs anything is specific to that local script.

First confirmed arrival (whole-house `not_home → home`) adds `Статус дома: ПРИСУТСТВИЕ`; final confirmed departure (`home → not_home`) adds `Статус дома: ОТСУТСТВИЕ`. On other resident transitions, the same notice only states `Дома: N`. These are messages, not physical alarm/security mode changes.

The App owns a one-time `device_tracker` → `user_name` map through the optional `resident_names` list in Supervisor App Configuration. Existing `residents` entries remain unchanged. The App publishes `user_name` (or JSON null) and the real GPS tracker friendly name `device_name` on machine events. The local package displays `user_name (device_name)`, or the device name alone when unmapped; it does not search `person` or maintain a duplicate name dictionary.

Install the package in `/config/packages/dh_presence_app_notification_local_package_ru.yaml` with `homeassistant: packages: !include_dir_named packages` and check that `script.write2log` accepts `title` and `message`. Since 0.1.25, linked HA router trackers drive Wi-Fi HOME/NOT_HOME, and `wifi_in` / `wifi_out` are emitted after a real transition following initial baseline. `wifi_lost` belongs to retired ARP presence monitoring and is not emitted by the current implementation. `wifi_absence_minutes` remains a legacy, ignored configuration key.

## Install through Home Assistant

1. Add `https://github.com/DigitalHouses/home-assistant-apps` under **Settings → Apps → App Store → Repositories** if not already configured.
2. Refresh App Store metadata and open **DigitalHouses Presence App** (Experimental).
3. Install, then open **Configuration** and add the phone's exact GPS `device_tracker` entity to the `residents` list (one string per phone). Do not add iPads left at home.
4. Leave `presence_mode: gps` for functional tracking. After startup, a `select.dh_presence_app_mode` entity is available in the MQTT device and in the example dashboard. Do not register excluded administrators' trackers. Legacy HA User ID exclusions cannot be derived reliably from a tracker alone; a tracker-only roster with `exclude_users` configured fails visibly instead of silently tracking an excluded user.
5. Save and start the App. Check **Logs** and the `DigitalHouses Presence App` MQTT Device in HA.
6. For update, use the ordinary Home Assistant Apps interface after a new version is published. Do not install ZIP files or run ad-hoc copy commands.

A fresh installation with no registered residents remains unknown and must never display an empty home.

This version is built locally by Supervisor (no `image:` field and no GHCR release). Immutable registry delivery and mandatory consent/telemetry are future production acceptance gates.

Read [DOCS.md](DOCS.md) and [docs/TEST_PLAN.md](docs/TEST_PLAN.md) before using presence outside the laboratory.
