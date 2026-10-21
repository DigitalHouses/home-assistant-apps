# DigitalHouses Aqara Switch App — Design & Pilot Contract

Version `0.1.2` is an **experimental Scan/Adopt + settings keeper + light.toggle MVP**. It observes
Zigbee2MQTT MQTT, reads Home Assistant Device/Area Registry through the
Supervisor WebSocket proxy, and persists new devices into **own Supervisor
App Options** only when Scan is explicitly pressed. Later, validated adopted configuration keys may be restored after observed mismatch; relay ON/OFF is never written by Mode Keeper.

## Sources of truth

- Zigbee2MQTT MQTT retained `bridge/info` and `bridge/devices` + actual
  MQTT state: verified network IEEE, devices, capabilities and actual settings.
- Home Assistant Area and Device Registries: room for new devices only.
- `configuration_yaml` in Supervisor App Options: one editable
  `rooms → switches` tree containing modes, key bindings, logical identity
  and optional `panel_relay` references to entities like
  `switch.tongou_livingroom_lights`. Phases/circuit geometry belong to
  a separate Tongou App.
- Per-site physical entities are never hardcoded in public code.

## Manual Scan and replacement

1. Start App manually. Listening to bridge snapshots is **not** importing.
2. Home Assistant button `button.dh_aqara_switch_app_scan` sends one
   non-retained MQTT SCAN request, never on startup or a timer.
3. Confirm bridge coordinator from both retained `info` and `devices`.
4. Collect device metadata, supported actions, writable physical mode keys
   and only state values actually observed in device MQTT messages.
5. Read HA Device/Area Registries via Supervisor proxy, matching exact Zigbee
   IEEE connections or MQTT identifier. Unknown HA area => Unassigned.
6. Re-read own App Options just before merging; **append only new** devices.
   Do not change existing names, settings, key assignments or rooms.
7. Publish accepted new names/skipped/errors and persist the last scan report
   in `/data/last_scan.json`.

Logical identity is coordinator IEEE + Zigbee2MQTT friendly name.
Physical IEEE may change during replacement. Compatible replacement
requires an exact match of model, actions, exposed settings and relay channels.
An incompatible replacement is a visible problem and blocks restoration.
Runtime snapshots show `unverified`, `incompatible`, `replacement`, or
`settings_mismatch`, not a fabricated OK state.

## HA UI

- `sensor.dh_aqara_switch_app_card` is the foreground operation state.
- `button.dh_aqara_switch_app_scan` is a dedicated command.
- `sensor.dh_aqara_switch_app_scan_state` has `idle|updating|error`.
- `sensor.dh_aqara_switch_app_scan_details` stores the latest report.
- `sensor.dh_aqara_switch_app_devices_details` drives the Lovelace tree.
- `sensor.dh_aqara_switch_app_problems` lists observed identity and
  settings faults.
- The default card is read-only apart from Scan and Supervisor Restart.
  UI never performs device writes by templating.

## Strictly pending

The Dispatcher planning module is pure and does not call HA.
Mode Keeper, Maintenance Mode, user-confirmed deletion links, assign-binding
UI and successful button → virtual-light end-to-end must be implemented later.
Do not enable a second physical controller until QA and explicit cutover.

Telemetry and immutable GHCR release are still blocked by the product
privacy/release contracts. No telemetry is transmitted in this pilot.

## Полевые уроки и аварийное восстановление

[Отдельный обязательный документ требований](docs/field-lessons-and-recovery.md) фиксирует договорённости по UI, логическим и электрическим связям, замене устройств, двум моделям восстановления питания, Zigbee storm и startup-политикам участников Zigbee-групп. Новые фичи не должны противоречить ему без явного пересмотра решения. Каскад и Light Startup Keeper пока не реализованы.

## Решение: светильники и подтверждения — в этом App

Светильники, их назначение клавишам, Z2M-группы и проверка состояния каждого участника остаются ответственностью `dh_aqara_switch_app`. Отдельный Light Startup Keeper App не планируется. `bridge/groups` — источник состава группы, не дублировать его вручную; `power_on_behavior` проверяется/применяется **на индивидуальных устройствах** после аппаратной приёмки.

Ключевой контракт: различать «получили нажатие», «команда передана», «наблюдаемое состояние (возможно optimistic)», «аппаратно подтверждено», «частично / unknown / error». В Markdown-дереве показывать последнюю команду и поимённый результат участников группы. Полный контракт и ограничения прямого Binding — в [field lessons](docs/field-lessons-and-recovery.md). В v0.1.2 подтверждения исполнения команды светильником ещё нет.

## Текущая мощность и раскрытие Zigbee-групп (будущий функционал)

На уровне **выключателя** в HA-дереве всегда показывать текущую мощность (Вт), свежесть и источник измерения — если модель Aqara имеет `power` в Z2M либо привязан конкретный HA sensor мощности щитовой цепи. Нет измерения — `unknown`, не `0 W`. Не путать мощность питающей общей DIN-линии и индивидуальную нагрузку Aqara. Изменение `ΔW` подтверждает изменение нагрузки **измеряемой цепи**, но не каждую Zigbee-лампу в группе, которой управляет `decoupled` клавиша.

**Группу и её участников показывать одновременно**: назначенная клавиша → группа → динамически обнаруженные участники из `bridge/groups` → отдельные состояния, подтверждения и ошибки каждой лампы; `5/5 observed` может быть оптимистическим, не `5/5 confirmed`. Конфигурация хранит только ссылку на группу/светильник, а не их дублированный список. Детальная спецификация в [field lessons](docs/field-lessons-and-recovery.md). Пока это договорённость, не готовый runtime.

## Протокол подтверждения Zigbee-светильников (будущий Verification Engine)

**Группа не подтверждает состояние своих членов автоматически.** `optimistic` Z2M может синтетически менять группу и состояния участников. Для диагностируемых групп/ламп сначала протестировать `optimistic: false`; по `bridge/groups` получить всех участников и endpoint, ждать свежих отчётов, неподтверждённых опрашивать точечным `/get` (если `exposes.access & 4`), с лимитами на всю сеть. Только реальный новый отчёт или доказанный ответ Zigbee Read Attributes даёт `state_confirmed`. Простое MQTT-сообщение после GET может содержать кешированные значения, а стандартный MQTT не гарантирует корреляцию запрос/ответ; в таком случае статус `observed_unverified` или `unknown`. Групповое `confirmed` только если каждый из N участников подтвердил ожидаемое состояние; отдельно отображать mismatch, timeout и электрическую мощность. Не путать подтверждённый onOff с фактическим световым потоком. Подробнее [полевые уроки §6.4](docs/field-lessons-and-recovery.md). Пока не реализовано.
