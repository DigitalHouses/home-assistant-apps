# DigitalHouses Aqara Switch App

**v0.1.9 — individual optional smart-light parameters per target.**

This Home Assistant App supports the commissioning flow for Aqara wired switches,
battery buttons and key panels. It is not a general automation engine. This MVP scans and adopts Aqara
inputs, preserves saved writable switch configuration, and dispatches an
explicitly bound Aqara action to one or more Home Assistant light.toggle targets.
It never switches physical Aqara relay output states itself.

## Installation and prerequisites

- Home Assistant OS with Supervisor and MQTT service (e.g. Mosquitto).
- Zigbee2MQTT on the same broker, publishing retained `bridge/info` and `bridge/devices`.
- Home Assistant Device Registry + Area Registry for accurate room membership.
- `homeassistant_api: true` is now declared in the App manifest for authorized
  Supervisor proxy WebSocket registry reads and HA `light.toggle` calls.
- This is an **experimental App Store installable release** using immutable GHCR
  images. App boot remains manual for controlled commissioning. Do not assign
  a button already controlled by AQPM2 or another automation until the legacy
  handler for that exact action has been disabled.

## Install through Home Assistant Apps

1. Open **Settings → Apps → App Store → Repositories**.
2. Add `https://github.com/DigitalHouses/home-assistant-apps` if absent.
3. Refresh the store, open **DigitalHouses Aqara Switch App** and install.
4. App is set to **manual boot**. Start it manually and inspect the logs
   before attempting Scan or setting any bindings.
5. Initially, the `switches` YAML list is empty.
   Installation alone cannot toggle any light or change any adopted Aqara
   settings, because no devices have yet been adopted.

Immutable image: `ghcr.io/digitalhouses/digitalhouses_aqara_switch_app:0.1.9`.

## Configure and Scan (fresh install only)

**Version 0.1.6 intentionally has no migration.** Uninstall v0.1.5 and
reinstall this App if you want a clean Adopt. Do not restore a previous
version's App backup into 0.1.6. This does not remove physical Zigbee2MQTT
devices or unrelated Home Assistant lights.

App Options has `log_level` plus **one short multiline YAML option
`switches`** (initially `[]`). The Home Assistant Supervisor editor does
not support arbitrary nested dynamic keys as native form controls.

After pressing **Сканировать**, the App detects all supported Aqara
devices that advertise Zigbee2MQTT `action` values, including battery
remotes and Aqara climate sensors with buttons. All are configured under a
`switch.*` key, regardless of their Home Assistant entity domain:

- When HA associates the Zigbee device with **exactly one existing**
  `switch.*` entity, its actual entity_id is reused as config key.
- Otherwise, Scan generates a unique **logical-only** `switch.*` YAML key
  based on the device's Zigbee2MQTT friendly name (e.g.
  `switch.aqara_battery_button`). This is **not** a new or existing
  Home Assistant entity; the App does not publish it through MQTT Discovery.
  Colliding names use a network-qualified stable key instead.
- Scan stores the physical coordinator, IEEE, Zigbee2MQTT topic, model and
  writable settings baseline privately in `/data`. These facts are not
  editable through the switch YAML.

The App's `switches` YAML option then looks like (example only;
Scan determines the exact keys):

```yaml
- switch.aqara_battery_button:
    enabled: true
    actions:
      single:
        - light.dh_aqara_lab_chandelier
        - light.dh_aqara_lab_spots
      double:
        - light.dh_aqara_lab_sconce
- switch.ths_livingroom:
    enabled: true
    actions: {}
```

In the Supervisor YAML options view this is stored inside the multiline
`switches: |` field. Edit only actions and light targets; keys are
generated or resolved by Scan. Scan is manual, not periodic.

## Smart-light action configuration (v0.1.9)

Plain light lists remain valid and toggle the listed lamps:

```yaml
single:
  - light.dh_aqara_lab_chandelier
  - light.dh_aqara_lab_spots
```

Each individual lamp may have **its own optional brightness, Kelvin/RGB
color or fade**. Service belongs to the button action, parameters to
the lamp, not to the group:

```yaml
double:
  service: light.turn_on
  targets:
    - light.dh_aqara_lab_led_strip:
        brightness_pct: 70
        color_temp_kelvin: 3000
        transition: 2
    - light.dh_aqara_lab_sconce:
        brightness_pct: 40
        rgb_color: [255, 80, 30]
    - light.dh_aqara_lab_spots
```

The third light receives **no explicit brightness/color** attributes;
Home Assistant applies its normal turn_on behavior. Optional attributes:
`brightness_pct` 0..100, `brightness_step_pct` -100..-1 or 1..100,
`color_temp_kelvin` 1000..12000, `rgb_color` [r,g,b] each 0..255,
`transition` 0..60 sec. Conflicting color modes, conflicting
absolute/relative brightness and unsupported services are rejected.
Only scanned Z2M actions in the device fingerprint may trigger a command.
Do not assume a lamp supports dimming, RGB or Kelvin: verify the actual
model before configuring these capabilities.

If every target has identical parameters, the app sends a single
`light.turn_on` request with all of those lights. With different per-light
options, it sends multiple requests (one for each distinct parameter set),
serially in one queued action batch. Failure midway reports an error;
prior requests cannot be undone. This release **still uses HA REST for
light commands**, not direct Z2M MQTT output.

Compatibility: original short target lists and v0.1.8 shared attributes
still parse, but shared attributes cannot be mixed with per-light options
within the same action. For new configs use per-light options.

All physical metadata (IEEE, coordinator, Zigbee2MQTT base topic,
fingerprint, adopted writable settings) lives inside
`/data/adopted_switches.json`. No new Home Assistant entities are
registered. The existing or generated `switch.*` key is used only as a **logical key**;
the App never calls `switch.toggle` on it.

A fresh, non-retained, non-duplicated Aqara MQTT press matching an adopted
action calls **one** `light.toggle` service with its configured list of
1–16 existing light entities. Each target toggles its own previous state.
An empty `actions: {}` is inert. The `enabled: false` setting also
disables Mode Keeper for that switch. HA accepting a call is not proof
of physical light operation.

Explicit Scan can update a replaced physical IEEE when the Zigbee2MQTT
friendly name and coordinator remain the same and its hardware capability
fingerprint is compatible. The stable logical key retains action bindings.
An incompatible replacement is rejected; no action is sent.

## Home Assistant UI

**Единый Dashboard (MVP):** [Aqara Switch — полная панель](examples/lovelace/dh_aqara_switch_app_dashboard_ru.yaml).
Добавьте в Home Assistant новую панель (ручная конфигурация), откройте
**Редактировать панель → Редактор конфигурации (Raw configuration)** и
вставьте YAML целиком. Для строки состояния/чипов нужны установленные
`custom:button-card` и Mushroom. Панель использует только реально
опубликованные сущности `v0.1.3`: Scan, состояние и версия App,
дерево устройств, результат последнего Scan, проблемы и последнее
`light.toggle`-действие. Привязки клавиш редактируются в **параметрах App**,
не в Lovelace. Панель не исполняет световые команды и не доказывает
физическое переключение светильника.



Examples under [examples/lovelace](examples/lovelace/):
- [Status / Scan / Supervisor restart card](examples/lovelace/dh_aqara_switch_app_card_ru.yaml)
- [Room → switch → actions/settings tree](examples/lovelace/dh_aqara_switch_app_tree_ru.yaml)
- [Last Scan report](examples/lovelace/dh_aqara_switch_app_last_scan_ru.yaml)
- [Device problem overview](examples/lovelace/dh_aqara_switch_app_problems_ru.yaml)

## Aqara button → light/group outcome contract (planned)

Light targets and group-aware **per-member** startup configuration belong in
**this Aqara Switch App**, not a separate lights App. A key may target one light
or a Zigbee group; group members are discovered from Zigbee2MQTT `bridge/groups`
rather than copied into each switch's config.

The HA tree also needs **current W at switch level** with a truthful meter
source and physical measurement scope (Aqara device power when exposed, or a
selected external power sensor, e.g. Tongou). A fresh before/after ΔW can
corroborate a load change on that circuit, but it cannot prove that every
member of a decoupled Zigbee group responded. An unknown meter is not 0 W.
Group targets must be expanded into every current Z2M member for individual
status/confirmation, with no static member list in App Options.

The product must report the dispatched command, target, current group members,
and individually observed/confirmed states with `partial` / `unknown`
where appropriate. **Zigbee2MQTT optimistic group or member state is not proof**
that all physical lamps switched; direct Zigbee Binding can bypass this App.
See [field lessons: light ownership and command verification](docs/field-lessons-and-recovery.md).
Group/individual confirmation remains future work beyond 0.1.2.

The status card has working Scan and Supervisor Restart controls. Full
DigitalHouses release check, Refresh and Install chips are deferred until
their backends are available; no fake buttons are presented. The tree is
currently read-only; click-through editing and confirmed deletion are not yet
implemented.

## Passive occupied-site logging (experimental)

A standalone [one-group MQTT observer](examples/tests/passive_group_observer_ru.md)
is available for collecting logs without changing live illumination. It is
not a published or installed HA App and all states remain unverified.

## Virtual home LAB

Install [the optional HA template lights package](examples/packages/dh_aqara_switch_app_lab.yaml)
in the site's **actual loaded packages directory**, run `ha core check` and
restart HA to register the virtual lights. The package creates three
`light.dh_aqara_lab_*` fixtures backed by independent input_booleans.
The LAB now provides **six independent virtual `template` lights**,
backed by `input_boolean` (no Zigbee or physical relays). The three
pre-existing light IDs are preserved; three more were added.
See the [LAB Lovelace controls](examples/lovelace/dh_aqara_switch_app_lab_lights_ru.yaml).
For a `type: sections` Lovelace view, add the
[LAB six-light section](examples/lovelace/dh_aqara_switch_app_lab_section_ru.yaml).
The canonical package example is
[dh_aqara_switch_app_lab.yaml](examples/packages/dh_aqara_switch_app_lab.yaml).
Install it in the **actual loaded HA packages directory**, validate with
`ha core check`, and restart HA Core to load the new template entities.
Do not create a second copy of the package. `input_boolean` state
is restored by Home Assistant when no `initial` is set.
The LAB package contains no physical relay control and is independent of this App.

## Safety and release

Product telemetry remains unadmitted (`telemetry_allowed=false`). This
release provides an immutable GHCR image for installation through the
DigitalHouses Home Assistant App Store. Installation/Scan does not imply
physical actuator acceptance. The live Aqara button and MQTT
configuration must be inspected during on-site testing.

Future milestones: confirmed physical button-to-light E2E, HA binding editor,
delete-with-confirmation, group member readback, safe startup/cascade recovery
and Maintenance Mode after separate acceptance.

### Lessons learned on real installations

**Do not lose field commissioning requirements.** The [field lessons and recovery design backlog](docs/field-lessons-and-recovery.md) records the user-agreed onboarding, device replacement, HA UI, physical load topology, hardware vs cascade power recovery and per-member smart-light startup requirements, including unresolved design decisions. These advanced field requirements remain pending beyond v0.1.3.

For a minimal read-only pilot of real Z2M group and member states, follow [Zigbee group confirmation smoke test (RU)](examples/tests/z2m_group_state_smoke_ru.md). It deliberately avoids bulk readback or any automatic control.

See [DOCS.md](DOCS.md) for contract and [DigitalHouses standards](../docs/README.md).

## Local verification

```sh
PYTHONPATH=digitalhouses_aqara_switch_app/rootfs/app \
python -m unittest discover -s digitalhouses_aqara_switch_app/tests -v
python -m compileall -q digitalhouses_aqara_switch_app/rootfs/app
bash -n digitalhouses_aqara_switch_app/rootfs/run.sh
python scripts/validate_repository.py
```
