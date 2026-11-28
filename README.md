# DigitalHouses Home Assistant Apps

[![CI](https://github.com/DigitalHouses/home-assistant-apps/actions/workflows/validate.yml/badge.svg)](https://github.com/DigitalHouses/home-assistant-apps/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Open-source Home Assistant apps and Linux agents for smart-home infrastructure, local network discovery, presence, device control, databases, connectivity, media and backup monitoring.

DigitalHouses products are designed to work with Home Assistant while keeping their individual configuration, runtime and release lifecycle independent.

## Home Assistant Apps

Install these apps through Home Assistant Supervisor. Select a product to read its documentation, configuration requirements and limitations.

| Product | Stage | What it does |
| --- | --- | --- |
| [Internet App](digitalhouses_internet_app/README.md) | Stable | Internet availability, outage history, Ookla Speedtest, traffic accounting and automatic ONT/router recovery. |
| [Network App](digitalhouses_network_app/README.md) · [Screenshot](digitalhouses_network_app/README.md#screenshots) | Stable | Local device inventory, ARP and router discovery, mDNS/SSDP enrichment, persistent notes, discovery history and source-verified device availability. English and Russian Ingress UI. |
| [Recorder App](digitalhouses_recorder_app/README.md) | Stable | Recorder database health, size, history depth, disk usage, write activity and the entities producing the most records. |
| [Backblaze App](digitalhouses_backblaze_app/README.md) | Stable | Backblaze B2 account and per-bucket storage monitoring through MQTT Discovery. |
| [Presence App](digitalhouses_presence_app/README.md) | Experimental | Resident presence using GPS and registered Wi-Fi device trackers from Home Assistant router integrations, with conservative hybrid presence logic. |
| [Actions App](digitalhouses_actions_app/README.md) | Experimental | Configurable Zigbee2MQTT device actions, logical key bindings, Mode Keeper and verified device control. |
| [System Globals App](digitalhouses_system_globals_app/README.md) | Experimental | Shared day/night modes, profiles and system-readiness gates for other applications. |
| [Zigbee Monitor App](digitalhouses_zigbee_monitor_app/README.md) | Experimental | Automatic Zigbee2MQTT discovery, read-only device inventory, availability and MQTT activity monitoring. |
| [Sync App](digitalhouses_sync_app/README.md) | Experimental | Discovers DigitalHouses products through retained MQTT announcements and synchronizes Home Assistant dashboards and YAML packages from GitHub. |

Stage labels follow each app's Supervisor package metadata. Experimental apps are available for testing but may require additional field acceptance.

## Linux agents

Install these agents directly on the monitored Linux host. They publish monitoring data to Home Assistant through MQTT Discovery.

| Product | What it does |
| --- | --- |
| [PVE Agent](digitalhouses_pve_agent/README.md) | Proxmox VE host and VM/LXC monitoring, CPU, memory, storage, SMART, GPU, fan and optional NUT/UPS diagnostics. |
| [PBS Agent](digitalhouses_pbs_agent/README.md) | Read-only Proxmox Backup Server monitoring: datastores, backup snapshots, push sync, verify, prune and garbage collection jobs. |
| [Plex Agent](digitalhouses_plex_agent/README.md) | Plex Media Server workload, playback, transcoding, library activity and media storage monitoring. |

See each agent's README for installation, permissions, supported platforms, native CLI commands and update instructions.

## Getting started

### Install Home Assistant Apps

In Home Assistant, open **Settings → Apps → App store → Repositories** and add:

```text
https://github.com/DigitalHouses/home-assistant-apps
```

Choose an app, install it, configure the required options and start it. Apps with a web interface can be opened through Supervisor Ingress.

### Dashboards and integration

MQTT Discovery creates Home Assistant entities for products that provide MQTT integration. [DH Sync](digitalhouses_sync_app/README.md) manages compatible dashboard Views and packages from the repository using retained product announcements. Follow the individual product instructions for MQTT, dashboard and package requirements; not every app requires MQTT.

### Updates and releases

See [GitHub Releases](https://github.com/DigitalHouses/home-assistant-apps/releases) for published versions. Each product has an independent version and changelog. Home Assistant apps with immutable container delivery use versioned GHCR images; Linux agents have their own installation and update mechanisms.

The current version and stage are defined in each app's `config.yaml` or agent's `VERSION` file. The catalog above intentionally does not duplicate version numbers.

## Project infrastructure

- [DigitalHouses Stats](digitalhouses-stats/README.md) — backend for product installation statistics and telemetry.
- [Canonical product registry](digitalhouses-stats/digitalhouses_stats/product_registry.json) — product identities, telemetry catalog and release metadata.

Telemetry requirements and consent behavior depend on the product and its current policy. Consult its README and the [Product Telemetry Policy](docs/standards/PRODUCT_TELEMETRY_POLICY.md). Review and redact diagnostic exports before sharing them publicly.

## Legacy products

[Speedtest App](digitalhouses_speedtest_app/README.md) is deprecated and superseded by Internet App. The former Aqara Switch App identity is deprecated; current development continues in Actions App. Existing legacy release artifacts remain available according to the release policy.

## Engineering documentation

- [Documentation index](docs/README.md)
- [Application Standard](docs/standards/DIGITALHOUSES_APP_STANDARD.md)
- [DH Journal Standard](docs/standards/DH_JOURNAL_STANDARD.md)
- [Product Naming Standard](docs/standards/PRODUCT_NAMING_STANDARD.md)
- [Contract Data Policy](docs/standards/CONTRACT_DATA_POLICY.md)
- [DH Sync Developer Standard](docs/standards/DH_SYNC_DEVELOPER_STANDARD.md) — retained MQTT /sync, canonical Views and packages
- [Events & Notifications Standard](docs/standards/EVENTS_AND_NOTIFICATIONS_STANDARD.md)
- [Linux Agent Management Standard](docs/standards/DH_LINUX_AGENT_MANAGEMENT_STANDARD.md) — PVE Agent as the operational reference
- [Unified Product Status Card Standard](docs/standards/UNIFIED_PRODUCT_STATUS_CARD_STANDARD.md)
- [Operation UI Standard](docs/standards/OPERATION_UI_STANDARD.md)
- [Manual Refresh Standard](docs/standards/MANUAL_REFRESH_STANDARD.md)
- [Repository Governance](docs/standards/REPOSITORY_GOVERNANCE.md)
- [Release Policy](docs/standards/RELEASE_POLICY.md)
- [Immutable Delivery, Compact Backup and Telemetry Standard](docs/standards/IMMUTABLE_DELIVERY_AND_TELEMETRY_STANDARD.md)
- [Product Telemetry Policy](docs/standards/PRODUCT_TELEMETRY_POLICY.md)
- [Telemetry Protocol v1](docs/standards/TELEMETRY_PROTOCOL_V1.md)
- [Telemetry Implementation Guide](docs/standards/TELEMETRY_IMPLEMENTATION_GUIDE.md)

GitHub is the source of truth for reusable DigitalHouses product code, canonical configuration resources and release provenance.

## Development and feedback

Each product owns its implementation, tests, compatibility contract and release version. Repository validation enforces common standards and product-specific checks. See [CONTRIBUTING.md](.github/CONTRIBUTING.md) and [SECURITY.md](.github/SECURITY.md).

For questions, bug reports and feature requests, use [GitHub Issues](https://github.com/DigitalHouses/home-assistant-apps/issues). Include the product name and version, relevant logs and anonymized diagnostics.

## Support

DigitalHouses projects are developed independently and provided free of charge.

[![Support DigitalHouses on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/digitalhouses)

Support is optional. Public features remain available to everyone.

## License

DigitalHouses source code is licensed under the [MIT License](LICENSE). Third-party software retains its own license terms.
