# DigitalHouses Presence App

**Status: architecture bootstrap — not yet installable.**

This is the development directory of the new Home Assistant App **DigitalHouses Presence App** inside the canonical `DigitalHouses/home-assistant-apps` repository. The source of truth is this repository, **not** a separate GitHub repository.

## Identifiers

| Surface | Identity |
| --- | --- |
| Product ID, future directory and HA App slug | `digitalhouses_presence_app` |
| Home Assistant entity / unique ID prefix | `dh_presence_app` |
| MQTT Device | `DigitalHouses Presence App` |
| Proposed MQTT base | `DigitalHouses/Global/dh_presence_app` |
| Future GHCR repository | `ghcr.io/digitalhouses/digitalhouses_presence_app` |

The abbreviated entity prefix is not an alternative product identifier.

## Purpose

Detect residents' presence using Home Assistant Mobile Companion GPS, a self-contained local Wi-Fi detection engine, or hybrid GPS + Wi-Fi rules. Maintain safe last-confirmed presence on source loss: **UNAVAILABLE is not NOT_HOME**. Never assume an empty home from missing observations.

Supported modes:

- **GPS**: the selected Mobile Companion GPS tracker controls presence; Wi-Fi source events remain diagnostic.
- **Wi-Fi**: local network evidence controls presence; GPS still supplies straight-line distance.
- **Hybrid**: GPS primary; verified Wi-Fi HOME may correct GPS NOT_HOME; verified Wi-Fi absence may override GPS HOME only after a configurable (initially 15-minute) continuous interval of trustworthy negative evidence. Ordinary ARP timeouts do not prove absence.

## Planned public contract

- Exactly one MQTT Device, one aggregate `binary_sensor.dh_presence_app_residents_home`, one `event.dh_presence_app_event`.
- Per registered resident: one source-specific GPS binary sensor and one GPS distance sensor in km; no additional attributes on distance sensors.
- HA-user-ID-based registration; optionally exclude configured users entirely from tracking and discovery. An HA administrator is *not* excluded automatically.
- Machine-only MQTT Events; Russian/other human-facing notifications belong to Home Assistant packages.
- Persistent confirmed state survives App/HA restart without fabricating arrivals, departures, or initial OFF state.
- No required Nmap, NetAlertX, router, or DHCP integration.

## Development status and gates

A Home Assistant App manifest (`config.yaml`), `digitalhouses.app` marker, container image, installer and release have **not** been added intentionally: this is an initial design directory, not a runnable or Store-discoverable product. Before activating the product, add its registry entry, product validator, common/type-specific files, CI job, actual runtime and acceptance tests **together** according to the repository standards.

The 14 October 2026 experiments proved a Home Assistant Core WebSocket handler can resolve the authenticated user and direct-LAN peer IP/MAC, and that active ARP can probe an iPhone. They did not establish long-sleep reliability, safe negative Wi-Fi evidence, App-container raw-socket feasibility or reliable Companion device binding.

Development and integration tests must target the owner's home HA pilot (`192.168.11.33:80`), **never the Amir production installation**. Existing experimental Home Assistant Core integration must be audited before replacement. Do not connect this prototype to security alarm automation.

## Engineering documents

- [Requirements](docs/REQUIREMENTS.md)
- [Architecture and boundaries](docs/ARCHITECTURE.md)
- [MQTT contract](docs/MQTT_CONTRACT.md)
- [Implementation and validation plan](docs/TEST_PLAN.md)

Shared normative standards: [Application](../docs/standards/DIGITALHOUSES_APP_STANDARD.md), [Naming](../docs/standards/PRODUCT_NAMING_STANDARD.md), [Contract data](../docs/standards/CONTRACT_DATA_POLICY.md), [Events and notifications](../docs/standards/EVENTS_AND_NOTIFICATIONS_STANDARD.md), [Unified status card](../docs/standards/UNIFIED_PRODUCT_STATUS_CARD_STANDARD.md).
