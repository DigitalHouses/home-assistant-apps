# DigitalHouses Aqara Switch App

**v0.1.13 — synchronized Z2M direct-MQTT lighting with offline exclusion.**

This Home Assistant App supports the commissioning flow for Aqara wired switches,
battery buttons and key panels. It is not a general automation engine. This MVP scans and adopts Aqara
inputs, preserves saved writable switch configuration, and dispatches an
explicitly bound Aqara action to one or more Home Assistant light.toggle targets.
It never switches physical Aqara relay output states itself.

## v0.1.13 — virtual AQARA LAB compatibility

Exactly six known `light.dh_aqara_lab_*` template lights are routed through
Home Assistant Core REST as **virtual test lights only**, with state lookup,
unavailable filtering, per-light attributes and synchronized grouped ON/OFF.
They do not have Zigbee2MQTT device routes and cannot work during HA Core
downtime. All real Zigbee2MQTT lamps retain the v0.1.12 MQTT-only transport,
including offline guards; there is no HA fallback for unverified physical
devices. Mixed virtual/physical `toggle` actions are not supported, to prevent
lights from getting out of sync. This fixes skipped virtual LAB actions such as
`double_plus` -> `light.dh_aqara_lab_night_light`. No new settings or Scan
are required for these virtual test lights.

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

Immutable image: `ghcr.io/digitalhouses/digitalhouses_aqara_switch_app:0.1.13`.

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

## Direct Zigbee2MQTT light output (v0.1.12)

Aqara key presses and outgoing lamp commands both use the existing MQTT
connection. **HA Core is not called on a key press.** The public config
continues using the same `switch.*` keys and `light.*` targets, with
optional light-specific attributes.

After installing, run **Scan once while HA Core is available**: the Scan
reads the HA Device/Entity Registry and Z2M `bridge/devices` to store
verified `light.* -> coordinator, IEEE, friendly_name` routes in the
private Adopt profile. No additional YAML or user-managed routing map.
A later HA Core restart does not block already mapped lights.

For each light, **Zigbee2MQTT device availability must be enabled** and
report `online` on `base/friendly_name/availability`. An offline,
unknown, ambiguous or unmapped light is skipped. App also requires the
bridge to report `online`. A plain multi-light assignment is no longer
an individual `light.toggle`: one shared group decision uses the states
of *available, freshly observed* lamps. Any OFF -> send ON to all;
all ON -> send OFF to all. No blind TOGGLE, no replay to devices after
they reconnect.

Quick repeat presses use the last in-flight intended ON/OFF state to
avoid toggling out of phase while Z2M is reporting. After 5 seconds
without a fresh post-command report, the lamp is excluded from
ambiguous toggles. Commands are published non-retained; a successful
MQTT publication is **not** proof a lamp actually obeyed.

For individual light parameters, App converts `brightness_pct` to Z2M
brightness, Kelvin to mired, RGB to XY/HS, and checks the device exposes.
Devices lacking the requested capability are skipped with diagnostic
reasons instead of receiving an invalid request.

**Limitations:** exact light route discovery currently supports one
Z2M light channel and exactly one enabled HA MQTT `light.*` entity
per physical device. Z2M light **groups**, multi-endpoint controllers,
and HA-only virtual lights (including the six `dh_aqara_lab_*` entities)
are not automatically bound. Configure the group's individual physical
light entities instead. Unsupported targets remain untouched.
Retained Z2M state after reconnect alone does not authorize an
ambiguous toggle; this can require a fresh device report or an explicit
Z2M `/get` before the first group toggle. The App proactively\nqueries known readable lamps (at most 2 per Zigbee network per second),\nwithout trusting old retained data.

## Per-key Mode Keeper and Maintenance (v0.1.10)

Aqara **wired** switches expose writable `operation_mode_left`,
`operation_mode_right` or `operation_mode` for `decoupled/control_relay`.
At explicit first Scan, the App captures only keys that are reported
`decoupled` **and** have a confirmed writable ON/OFF relay field. For
example, `left: decoupled/ON`. An ordinary `control_relay` key is left
out of YAML entirely.

Battery buttons (and other Aqara action devices without an operation mode)
need no `keep_mode`: their normal MQTT action handling remains available.

Supervisor App options (YAML view):

```yaml
log_level: info
maintenance_mode: false
restore_delay: 0.6
switches: |-
  - switch.aqara_switch_livingroom:
      enabled: true
      maintenance_mode: false
      keep_mode:
        left: decoupled/ON
      actions:
        single_left:
          - light.livingroom_chandelier
          - light.livingroom_spots
  - switch.aqara_battery_button:
      enabled: true
      actions: {}
```

`maintenance_mode` is a boolean at App level and an optional boolean per
switch. Effective Maintenance is `global OR local`. Enabling Maintenance
blocks actions for all affected keys and requests only `control_relay` for
wired keys included in `keep_mode`; it never forces a relay ON or OFF.
For battery buttons it only suppresses software actions.

In normal mode, App checks the Zigbee2MQTT-reported mode and relay state.
If they drift from `decoupled/ON`, after `restore_delay` seconds
(default 0.6) it requests mode `decoupled`, then physical relay `ON` after
a reported mode confirmation. Every command is followed by observation; a
publish return code does not prove a physical state. Retries are throttled
to one per key/value per 60 seconds. After reconnect App requests fresh
readable state via Z2M `/get`; retained-only messages cannot trigger
physical writes. Non-reporting and unsupported hardware fail closed.

Wired `*_left` actions require left managed and confirmed decoupled/ON;
`*_right` requires right; `*_both` requires both. Unmanaged relay-mode
keys do not have App bindings. Devices without mode support (battery
buttons) do not inherit these restrictions. The App validates these rules\nwhen loading the YAML configuration as well as when executing queued actions.

First Scan and later rescans do not change relays or modes. A later Scan
does NOT overwrite a recorded `keep_mode`, and manually deleting a
keep_mode is respected. App configuration changes normally require an
App restart to apply new Maintenance settings. Remember that returning
the relay to ON may restore power to smart bulbs; separately set their
power-on behavior to avoid unexpected illumination.

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
prior requests cannot be undone. As of v0.1.12, the light executor uses direct verified Zigbee2MQTT MQTT, not HA REST.

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
