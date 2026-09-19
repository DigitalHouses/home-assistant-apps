# DigitalHouses Home Assistant Apps

Open-source Home Assistant applications and Linux agents maintained by **DigitalHouses**.

This repository contains both Home Assistant OS Apps and native Linux agents that publish their state to Home Assistant through MQTT Discovery.

## Applications

| Application | Type | Purpose |
| --- | --- | --- |
| [DH PVE App](dh_pve_app/README.md) | Linux agent | Proxmox VE monitoring, hardware diagnostics, VM/LXC state, SMART, fan RPM and optional NUT/UPS monitoring |
| [DH Recorder Monitor](digitalhouses_db_monitoring/README.md) | HAOS App | Home Assistant Recorder database size, depth, write activity and database diagnostics |
| [DigitalHouses Speedtest](digitalhouses_speedtest/README.md) | HAOS App | Internet availability, Ookla speed tests and connection-quality monitoring |
| [DigitalHouses Plex Monitoring](digitalhouses_plex_monitoring/README.md) | Linux agent | Plex workload, playback, transcoding and library monitoring |

Each application has its own README with installation, configuration, Home Assistant entities and operational notes.

## Install HAOS Apps

Add this repository in Home Assistant:

```text
https://github.com/DigitalHouses/home-assistant-apps
```

Then open **Settings → Apps → App store → Repositories**, add the URL above and install the required DigitalHouses App.

## Linux agents

Linux agents are installed directly on the target Linux or Proxmox host rather than through the Home Assistant App Store.

- **DH PVE App:** [installation and documentation](dh_pve_app/README.md)
- **Plex Monitoring:** [installation and documentation](digitalhouses_plex_monitoring/README.md)

Hardware-specific procedures are kept with the relevant agent. For example, the Beelink/AZW IT8613E fan profile for DH PVE App is documented in [dh_pve_app/hardware/beelink/README.md](dh_pve_app/hardware/beelink/README.md).

## Development standard

DigitalHouses applications in this repository follow the [DigitalHouses Application Standard v1](docs/DIGITALHOUSES_APP_STANDARD.md).

Repository CI validates application metadata, tests, shell syntax and shared repository contracts.

## Repository layout

```text
home-assistant-apps/
├── dh_pve_app/                       # Proxmox VE Linux agent
├── digitalhouses_db_monitoring/      # HAOS App
├── digitalhouses_plex_monitoring/    # Plex Linux agent
├── digitalhouses_speedtest/          # HAOS App
├── docs/                             # Shared design/development documentation
├── scripts/                          # Repository validation tooling
├── .github/                          # GitHub Actions
├── repository.yaml
└── LICENSE
```

## Support

DigitalHouses projects are developed independently and provided free of charge.

[![Support DigitalHouses on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/digitalhouses)

Support is optional. Public features remain available to everyone.

## License

DigitalHouses source code is licensed under the [MIT License](LICENSE). Third-party software retains its own license terms.
