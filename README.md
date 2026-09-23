# DigitalHouses Home Assistant Apps

[![CI](https://github.com/DigitalHouses/home-assistant-apps/actions/workflows/validate.yml/badge.svg)](https://github.com/DigitalHouses/home-assistant-apps/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Open-source applications and Linux agents by **DigitalHouses**, built to extend Home Assistant with infrastructure, media, database, and connectivity observability.

## Products

| Product | Type | Purpose |
| --- | --- | --- |
| [DigitalHouses PVE Agent](dh_pve_app/README.md) | Linux agent | Proxmox VE monitoring, hardware diagnostics, VM/LXC state, SMART, fan RPM, and optional NUT/UPS monitoring |
| [DigitalHouses Plex Agent](digitalhouses_plex_monitoring/README.md) | Linux agent | Plex workload, playback, transcoding, and library monitoring |
| [DigitalHouses Recorder App](digitalhouses_db_monitoring/README.md) | Home Assistant App | Home Assistant Recorder database size, depth, write activity, and database diagnostics |
| [DigitalHouses Backblaze](digitalhouses_backblaze/README.md) | Home Assistant App | Backblaze B2 account totals and per-bucket storage usage through MQTT Discovery |
| [DigitalHouses Internet App](digitalhouses_internet/README.md) | Home Assistant App | Internet availability, outage history, and automatic ONT/router recovery |\n| [DigitalHouses Speedtest App](digitalhouses_speedtest/README.md) | Home Assistant App | Internet availability, Ookla speed tests, and connection-quality monitoring |

DigitalHouses uses two delivery models:

- **Home Assistant Apps** run under Home Assistant Supervisor and are installed from this repository.
- **Linux agents** run on the target Linux host and publish their state to Home Assistant through MQTT Discovery.

## Install Home Assistant Apps

Add this repository in Home Assistant:

```text
https://github.com/DigitalHouses/home-assistant-apps
```

Then open **Settings → Apps → App store → Repositories**, add the URL above, and install the required DigitalHouses App.

## Install Linux agents

Linux agents are installed directly on the target host:

- [DigitalHouses PVE Agent](dh_pve_app/README.md)
- [DigitalHouses Plex Agent](digitalhouses_plex_monitoring/README.md)

Installation, configuration, supported platforms, and product-specific operational procedures are documented in each product README.

## Documentation

Engineering documentation is separated into shared standards and product-specific design records:

- [Documentation index](docs/README.md)
- [DigitalHouses Application Standard](docs/standards/DIGITALHOUSES_APP_STANDARD.md)
- [DigitalHouses Release Policy](docs/standards/RELEASE_POLICY.md)
- [Immutable Delivery, Compact Backup and Telemetry Standard](docs/standards/IMMUTABLE_DELIVERY_AND_TELEMETRY_STANDARD.md)

GitHub is the source of truth for reusable DigitalHouses application code and release provenance.

## Development

Each product owns its implementation, tests, compatibility contract, and release version. Repository-level validation enforces the common DigitalHouses application contract and dispatches type-specific and product-specific checks.

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for contribution workflow and [SECURITY.md](.github/SECURITY.md) for responsible vulnerability reporting.

## Support

DigitalHouses projects are developed independently and provided free of charge.

[![Support DigitalHouses on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/digitalhouses)

Support is optional. Public features remain available to everyone.

## License

DigitalHouses source code is licensed under the [MIT License](LICENSE). Third-party software retains its own license terms.
