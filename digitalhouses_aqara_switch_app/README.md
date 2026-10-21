# DigitalHouses Aqara Switch App

**v0.1.2 — experimental Scan/Adopt + Mode Keeper + one-light toggle MVP.**

This Home Assistant App supports the commissioning flow for Aqara wired switches,
battery buttons and key panels. It is not a general automation engine. This MVP scans and adopts Aqara
inputs, preserves saved writable switch configuration, and dispatches an
explicitly bound Aqara action to a single Home Assistant light.toggle target.
It never switches physical Aqara relay output states itself.

## Installation and prerequisites

- Home Assistant OS with Supervisor and MQTT service (e.g. Mosquitto).
- Zigbee2MQTT on the same broker, publishing retained `bridge/info` and `bridge/devices`.
- Home Assistant Device Registry + Area Registry for accurate room membership.
- This is an **experimental source-built version** with **manual boot**; no
  immutable released GHCR image yet. Keep AQPM2 as the only active controller.

## Configure and scan

The **only editable source of truth** is the App's Supervisor Options.
`configuration_yaml` contains the nested tree `rooms → switches` in one
YAML text field because Supervisor does not support deeper structured fields.
Initially it is:

```yaml
rooms: []
```

The runtime only listens to MQTT upon startup. It does not import any device
until `button.dh_aqara_switch_app_scan` is pressed in Home Assistant.
Scan requires a verified coordinator and Zigbee2MQTT inventory and captures
*confirmed* MQTT settings. Missing physical parameters cause a visible scan
problem; this release does **not** ask Zigbee devices to change or report state.

Only new logical devices are appended to Supervisor Options. Existing entries,
bindings, room allocation and mode snapshots are **never overwritten** by Scan.
A registered logical device is identified by coordinator IEEE and its configured
Zigbee2MQTT friendly_name. New physical IEEE with the same name is compared
against the saved structural fingerprint and flagged when incompatible.
**No automatic relay restoration occurs in this pilot.**

## First working scenario (0.1.2 MVP)

1. Start the experimental local App, wait until Zigbee2MQTT inventory arrives.
2. Press `button.dh_aqara_switch_app_scan` **once**. This is the initial
   Adopt: only newly discovered Aqara inputs are appended to the App Options
   `configuration_yaml`; captured physical setting values become the baseline.
3. In Supervisor App Options edit the existing switch's `bindings`. Example
   under the already imported room/switch (do not replace IEEE/fingerprint):

```yaml
bindings:
  single:
    action: toggle
    targets:
      - light.bedroom_spots
```

The `single` key must exactly match this device's observed `action`
from Zigbee2MQTT. For other models use their real action names (e.g.
`single_left`); do not guess. The only executable action in this MVP is
one explicitly configured `light.toggle` target in HA (one `light.*`
entity, which may itself represent a Zigbee group in HA). Restart App after
editing Options to load changes.

4. Press the physical Aqara key. On a fresh non-retained MQTT `action`
from exactly the adopted model/IEEE/coordinator, the App calls
`POST /api/services/light/toggle` via Supervisor Core proxy. An
`accepted` event confirms HA accepted the service call, **not** that
the bulbs physically turned on. Observe
`sensor.dh_aqara_switch_app_last_action` for success/error.

**Mode Keeper:** if fresh MQTT telemetry explicitly reports one of the
writable physical settings as different from its adopted value, the App
requests restoration through Zigbee2MQTT `.../set`, no more than once
per 60 seconds per key. Relay `state` / `state_left` etc. are
**never** captured as adopted modes or written back. At present this is
best-effort settings restoration: a request is not a proven hardware
acknowledgement. If the device doesn't report a setting, the App will
not infer its value or issue a blind command.

**Critical:** disable any legacy automation or old AQPM2 handler
for exactly the same physical key before enabling a binding, or pressing
once could toggle twice. Do not remove any unrelated legacy controls.
If this device is connected to live electrical loads, commissioning its
operation mode needs a physical safety check; this MVP does not change
unknown relays during adoption.

## Home Assistant UI

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
See the [LAB Lovelace controls](examples/lovelace/dh_aqara_switch_app_lab_lights_ru.yaml).
The LAB package contains no physical relay control and is independent of this App.

## Safety and release

Product telemetry remains unadmitted (`telemetry_allowed=false`) while this is
an experimental, source-only pilot. No release is claimed, and this is not
installed in the user's home automatically. The live Aqara button and MQTT
configuration must be inspected during on-site testing.

Future milestones: reliable HA device binding, delete-with-confirmation in HA,
binding assignment, safe Dispatcher on virtual lights, then Mode Keeper and
Maintenance Mode with physically separate acceptance.

### Lessons learned on real installations

**Do not lose field commissioning requirements.** The [field lessons and recovery design backlog](docs/field-lessons-and-recovery.md) records the user-agreed onboarding, device replacement, HA UI, physical load topology, hardware vs cascade power recovery and per-member smart-light startup requirements, including unresolved design decisions. These are **not yet implemented** in v0.1.1.

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
