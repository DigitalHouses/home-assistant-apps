# Presence App — current MQTT contract (0.1.27 experimental)

Shared device: **DH Presence** (stable identifier `dh_presence_app`).
Canonical product: `digitalhouses_presence_app`.
Entity prefix: `dh_presence_app`.
MQTT base: `DigitalHouses/Global/dh_presence_app`.
Mode command: `DigitalHouses/Global/dh_presence_app/mode/set`, non-retained.
Mode state: `DigitalHouses/Global/dh_presence_app/mode/state`, retained.
Discovery: `homeassistant/device/dh_presence_app/config` (one device config).

| Kind | HA entity | Meaning |
| --- | --- | --- |
| Binary sensor | `binary_sensor.dh_presence_app_residents_home` | ON if at least one included resident is confirmed home, OFF only when every included resident is confirmed not_home; unknown if no safe aggregate determination |
| Binary sensor | `binary_sensor.dh_presence_app_<stable_resident_key>_gps_home` | GPS source only, independent of final Hybrid decision |
| Binary sensor | `binary_sensor.dh_presence_app_<stable_resident_key>_wifi_home` | Wi-Fi source only; unavailable until a verified Wi-Fi engine publishes evidence |
| Sensor | `sensor.dh_presence_app_<stable_resident_key>_distance` | GPS great-circle distance in km, without extra attributes |
| Event | `event.dh_presence_app_event` | Machine-readable resident/source transitions |
| Select | `select.dh_presence_app_mode` | GPS / Wi-Fi / Hybrid; MQTT command + retained state |
| Diagnostic sensors | `sensor.dh_presence_app_version`, `sensor.dh_presence_app_started_at` | Common DigitalHouses runtime diagnostics |
| Controls | `button.dh_presence_app_refresh`, `button.dh_presence_app_check_updates`, `sensor.dh_presence_app_card` | Actual runtime Refresh and stable-release check |
| Control diagnostics | `sensor.dh_presence_app_refresh_state`, `sensor.dh_presence_app_last_refresh`, `sensor.dh_presence_app_latest_version`, `binary_sensor.dh_presence_app_update_available` | Standard runtime operations and version reporting |

Use stable resident keys based on the explicitly registered `device_tracker` entity ID, **not HA user IDs or mutable display names**, for entity unique IDs. Dynamic removal/exclusion requires MQTT Discovery cleanup (tombstones) as well as entity removal on first synchronization.

The App's MQTT Select provides the operator's runtime mode; its retained state is derived from an independently persisted selection. When App Configuration mode changes, it overrides the previous UI selection at the next App restart.

The aggregate entity exposes `mode`, `residents`, `residents_total`, `residents_home`, and the informational `gps_freshness_seconds` threshold. Each resident also has the actual source `gps_reported_at` timestamp (or null); individual GPS binary sensors expose it as an attribute. A resident includes the source tracker's `name` (device label), App-configured `user_name` (optional/null), and each confirmed status. No GPS coordinates are exposed. Public attributes should be deliberately bounded and should not update on every probe tick.

Events: `arrival`, `departure`, `wifi_in`, `wifi_out`, `gps_in`, `gps_out`, legacy `wifi_lost` (not emitted since 0.1.25), and `zone_enter`, `zone_leave` (since 0.1.27).
Pilot payload fields: `schema_version: 2`, `event_type`, stable `resident_id`, `resident_name` (legacy tracker-friendly label), `device_name` (same HA tracker-friendly label), `user_name` (App-configured name or JSON null), `device_tracker` (configured source entity ID), `source`, `mode`, and ISO-8601 `observed_at`. Names are mapped once in Supervisor App `resident_names` settings and reused in Events; local packages do not resolve Person at delivery. **Arrival/departure** events additionally include `first_arrival`, `last_departure` (booleans), and `residents_home_after` (non-negative integer). A first arrival is **only** asserted when the known overall household status transitions `not_home → home`; a last departure only when it transitions `home → not_home`. Unknown residents preclude claiming an empty household. With multiple residents changing in one poll, these flags are calculated by the engine for each transition, so there is exactly one first and one last transition. No flags are fabricated on GPS/Wi-Fi source-only events.
Payloads are facts, not translated messages. Events: QoS 1, `retain=false`. Discovery configuration and authoritative current state may be retained. On a transition, retained state must be synchronized **before** publishing the transient event. No startup or MQTT reconnect event replay.

In GPS mode, Wi-Fi source events do not alter aggregate presence. In Wi-Fi mode, source events must not duplicate an arrival/departure notification; presentation policy belongs to the local HA package.

MQTT Discovery, retained state, and transient event publishing are implemented in the experimental pilot. Tests currently validate pure logic and payload shape; real HA / MQTT integration acceptance remains pending.

Version 0.1.9 adds Wi-Fi placeholder availability topics and the runtime controls above. Existing identifiers, GPS distance, aggregate and MQTT event topics stay unchanged. No Wi-Fi transition events are emitted before verified Wi-Fi observations.

Version 0.1.10 trusts HA's last valid GPS status and coordinates irrespective of age. The configured GPS freshness interval controls a **display-only** old-data label, not MQTT GPS availability. Refresh reads/republishes last-known observations without implying new phone GPS data. Unknown/unavailable source states remain unavailable and cannot generate an absence. The original source timestamp is preserved; repeat polls of the same report do not emit events.

## Уведомления по зонам (0.1.27)

Зоны читаются из Home Assistant `zone.*`; штатное GPS-состояние зарегистрированного `device_tracker` определяет индивидуальный переход. Собственный ZoneMonitor нужен для применения реестра жильцов и `exclude_users` до публикации события: стандартные HA zone triggers могут включать администраторов, не участвующих в DH Presence. Геофенсинг самостоятельно не рассчитывается. Числовое состояние `zone.*` не используется для идентификации жильца.

Каждая зона получает MQTT switch в общем устройстве `dh_presence_app`: `switch.dh_presence_app_notify_zone_<zone_key>`, где `zone_key` — первые 16 hex символов SHA-256 полного `zone.entity_id`. Topic команд `DigitalHouses/Global/dh_presence_app/notifications/zones/<zone_key>/set`, topic состояния — `.../state`; команды без retain, состояние приложения хранится в JSON, новые зоны выключены. Переименование friendly_name не меняет идентификатор, а переименование самого `entity_id` является изменением идентичности и создаёт новый выключенный переключатель. Удалённые зоны удаляются через Discovery cleanup.

Новые не-retained MQTT events: `zone_enter`, `zone_leave`. Сохранённые поля события v2 расширяются `zone_entity_id`, `zone_name`, `zone_key`. События производятся независимо от состояния переключателя и `presence_mode`. HA-пакет фильтрует разрешённые уведомления через `script.write2log`; для домашней зоны при активном переключателе подавляется дублирующий текст GPS. IP/MAC в событиях отсутствуют.


## Local home Wi-Fi and protected diagnostics (0.1.27)

Wi-Fi indicates only presence in the local home network of the HA installation (`zone.home`). A mobile device reaching HA through Cloudflare from an office does not establish local Wi-Fi presence. Runtime Wi-Fi evidence comes from the uniquely MAC-bound HA router `device_tracker`, not periodic active ARP/PING. Zone events for other `zone.*` entities rely on the native GPS tracker zone result.

Registration IP/MAC are retained in the App's private registry and available to authenticated administrators through its Ingress diagnostic card. They are intentionally **not** MQTT sensor attributes or event fields; normal HA MQTT Recorder history does not duplicate this private registration data. The ability to view IP/MAC in a protected administrative HA UI is an accepted requirement, not a violation of the event data contract.

The removal of the former general notification switch and the 0.1.27 zone event extension are already released compatibility changes. This documentation alignment does not alter their MQTT behavior.

## Recent event display state (0.1.28)

The App's own `events_history_limit` App Configuration option (integer 1–20, default 5) sets the maximum number of recent acknowledged machine Events kept in `/data/presence_event_history.json`. This persisted file is an App-owned bounded cache and contains only approved summary fields. When the allowed resident roster changes, history rows for nonparticipating or excluded users are removed. A missing history file starts empty; malformed persisted history is an explicit error, not a silent reset.

The new **diagnostic sensor** `sensor.dh_presence_app_recent_events` shares the existing MQTT Device; state is the bounded event count. It has a single retained state/attributes topic `DigitalHouses/Global/dh_presence_app/events/history` with `{count, limit, items}`. Each item has App-prepared `title`, escaped `details`, and timezone-aware `timestamp` (App publish time). It is **display state**, not a second transient Event/notification-envelope protocol, and does not create additional notification actions. The original `event.dh_presence_app_event` payloads remain machine-readable, non-retained and unchanged.

This history sensor updates on actual machine-event publication or resident/limit change, not on polling ticks. **Exclude the diagnostic sensor from HA Recorder**, because its repeated array attributes are UI data, not history measurements; the original machine Event remains eligible for Recorder according to the home's policy. Registered phone IP/MAC stays private in the administrator Ingress and never enters this MQTT UI history.

## Registered phone roster UI (0.1.29)

The pre-existing retained aggregate `binary_sensor.dh_presence_app_residents_home` `residents` attribute gains two per-resident metadata fields: `registered` (boolean; true only with an authenticated Ingress registration) and `registration_label` (App-prepared user/device label or null for legacy-only entries). The standalone Markdown list renders only registered entries. This does not create an additional MQTT sensor or append state attributes per scan. Excluded users and deleted/tombstoned trackers never appear in this public roster.

Phone deletion is an admin-authorized Ingress API operation, **not** an MQTT command/event; it cannot be invoked by a generic Lovelace card. It atomically updates the App's private registration registry, then the runtime removes the resident's old MQTT Discovery components via the existing cleanup and republishes the current retained aggregate state. A delete action must **not** emit physical `departure`, `gps_out`, `wifi_out` or `zone_leave` machine Events. The existing Event and notification schemas stay unchanged.

## Private phone tree and MQTT boundary (0.1.30)

The compact registration tree showing `IP (рег.)` and `MAC (рег.)` is generated **only** in the authorized administrator Ingress UI using the existing private `/api/admin/debug` response. It is intentionally **not** another sensor or a newly exposed attribute in `binary_sensor.dh_presence_app_residents_home`. The normal HA Markdown phone list continues to show non-private GPS/Wi-Fi tracker IDs only. Registration IP/MAC are snapshots at time of verification and are not current reachability readings. MQTT Events, Recorder and notification contracts do not change.


## Dashboard registered phones diagnostic entity (0.1.31)

- `sensor.dh_presence_app_registered_phones` joins the **existing one** DH
  Presence MQTT Device as a diagnostic sensor, not an additional App or MQTT
  Discovery Device. The state is the integer registered count.
- Its single retained state and attributes topic is
  `DigitalHouses/Global/dh_presence_app/registrations/tree`, JSON object
  `{count, tree}`. The `tree` string is completely prepared by App and
  includes registration-time IP/MAC. HA only escapes and displays it.
- Only registered active/non-excluded phones are included. Removing a phone
  publishes a new tree without its saved IP/MAC, including after an App restart.
  Unchanged snapshot payloads are suppressed by the App MQTT cache during
  ordinary polling.
- **Security change relative to 0.1.30:** this network registration metadata
  is now present in the MQTT broker and readable through the diagnostic HA
  sensor. This is *not* an HA-admin-only interface; use the original Ingress
  when backend-admin-only secrecy is required. Never claim that hiding the
  Lovelace card enforces access control.
- **Recorder exclusion is mandatory:** do not persist this diagnostic sensor
  or its mutable `tree` attribute. Merge with existing exclusion of
  `sensor.dh_presence_app_recent_events`. The normal
  `binary_sensor.dh_presence_app_residents_home` aggregate retains exactly
  its previous registration-safe attribute schema, events remain unchanged.

## Phone removal controls (0.1.33)

The same device `dh_presence_app` now discovers:

| Entity | Topic | Description |
| --- | --- | --- |
| `select.dh_presence_app_remove_phone` | `registrations/remove/select/set` | Exact current phone selection, **non-retained command**, dynamic options `Имя (телефон) · device_tracker...` plus `— Выберите телефон —` |
| Same select state | `registrations/remove/select/state` | Selected option retained by App; resets after successful/attempted delete or restart |
| `button.dh_presence_app_delete_registration` | `registrations/remove/press` | `DELETE` payload, **non-retained command**; App deletes only a current valid selected registration |

Prefix all relative topics with
`DigitalHouses/Global/dh_presence_app/`. App validates that the selected
value is among the currently active/non-excluded registrations, re-reads the
private registry under the shared Ingress lock, tombstones removed trackers,
updates dynamic MQTT Discovery and removes the phone from
`sensor.dh_presence_app_registered_phones`. Retained, malformed and stale
commands are ignored. App does not emit arrival/departure/zone-leave for
administrative deletion. No new sensor and no Recorder exclusion required
beyond existing diagnostic history/tree exclusions.

**Threat model:** MQTT command topics do not carry authenticated Home
Assistant user identity. Lovelace admin visibility is *not* an authorization
boundary. Users with permitted HA/MQTT service access can issue commands;
broker ACL and trusted HA users are necessary. Use existing authenticated
Ingress API for true per-user HA admin authorization.

## Live source labels in phone tree (0.1.34)

`sensor.dh_presence_app_registered_phones` and topic
`registrations/tree` are **unchanged**. The `tree` attribute now contains
each phone's live GPS and router Wi-Fi status, read directly from the App
Engine's independent source fields: `home` → `🟢 Дома`,
`not_home` → `🟠 Не дома`, `unavailable` → `⚪ Недоступно`.
A phone without a registered Wi-Fi association displays
`⚪ Не привязан`; it must not claim `not_home` without evidence.
Device labels use the 📲 emoji. The App still includes tracker IDs,
registration IP and MAC. HA only displays the prepared multiline string.

Tree updates may now occur after GPS/Wi-Fi transitions, without changes
to the registry or the existing sensor's numeric `count` state.
Identical retained state payloads are suppressed by MQTT cache.
`sensor.dh_presence_app_registered_phones` must remain excluded from
Recorder, along with `sensor.dh_presence_app_recent_events`.

## Status transition times in existing registered-phone tree (0.1.35)

The same retained `DigitalHouses/Global/dh_presence_app/registrations/tree`
JSON payload continues to expose `{count, tree}`; no extra MQTT
entities or topics are introduced. For each GPS/Wi-Fi source branch, App
adds one indented child, `└─ Статус с · dd.mm.yyyy hh:mm TZ`, derived
from the existing `Resident.gps_changed_at` or
`Resident.wifi_changed_at` at actual source state transitions,
**not** last-reported GPS observation or App polling time. Both branches
use the HA Core `time_zone` configuration (including DST); unavailable
timezone falls back to explicitly labeled UTC. Initial unknown
timestamps are `нет данных`, and unbound Wi-Fi `не применимо`.

The App now records GPS source transition to unavailable when Core data
cannot be read, keeping durable confirmed household presence distinct
from source diagnostic state (no synthetic departure). Router link
replacements similarly timestamp unavailable source transition.
Identical retained payloads are still deduplicated. Continue excluding
`sensor.dh_presence_app_registered_phones` from Recorder.

## HA-local display timestamps without timezone suffix (0.1.36)

The existing `sensor.dh_presence_app_registered_phones` diagnostic
`tree` strings keep nested GPS/Wi-Fi `Статус с` rows. Each status
transition instant is converted in App using the **HA Core-configured
timezone** and rendered strictly `dd.mm.yyyy hh:mm`, with no
`+05`, `UTC`, `CET` or other timezone suffixes.

The prior explicit UTC fallback (0.1.35) is **superseded**: until the
App has a valid HA timezone, timestamps are replaced with
`местное время недоступно` rather than misleading UTC wall times.
The runtime retries missing timezone configuration periodically.
Missing source transition timestamps remain `нет данных`; Wi-Fi
without a registered link remains `не применимо`. HA display
templates, MQTT topics and payload shape, Recorder exclusion, and
registered IP/MAC behavior are unchanged.
