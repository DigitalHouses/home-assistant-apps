# DigitalHouses Network App

Experimental native **Home Assistant OS App** for a durable LAN device inventory, presence history, and future device events. Internal/entity prefix: `dh_network_app`. Canonical product ID, App Store slug, and repository directory: `digitalhouses_network_app`.

## Current state (0.1.0 foundation)

Available now:
- standard installation from the **DigitalHouses Home Assistant Apps repository** (no copying files into HAOS);
- authenticated Home Assistant Ingress Web UI, optionally shown on the HA sidebar;
- Go process, persistent SQLite at `/data/network.sqlite3`;
- UI sections for Devices, Sources and Events, REST status/devices/sources/events endpoints and note updates for records that exist;
- an empty inventory on first launch: no fabricated device, presence or event data.

**Not yet implemented:** IPv4/IPv6 scanning, router/device_tracker import from HA, mDNS/Bonjour/SSDP discovery, identity reconciliation, presence transitions or HA Event publication. The Web UI identifies these as planned.

## Install / update (only through standard HA App Store)

1. In Home Assistant open **Settings → Apps → App store → Repositories**.
2. Add `https://github.com/DigitalHouses/home-assistant-apps` once, if not already present.
3. Refresh the App Store and install **DigitalHouses Network App**.
4. Start it and use **Open Web UI**; optionally enable **Show in sidebar**.
5. Future updates must also be installed by the Home Assistant App Store.

Do **not** install using `/local_apps`, arbitrary `docker run`, a separate web port, or manual copying into HAOS. This early experimental build has no published GHCR image, so Supervisor builds it from the repository. Production immutable images will be added before the first stable release following the common DigitalHouses release policy.

## Security and compatibility

Ingress serves the only public UI entry point. No host port mappings, `NET_RAW`, `full_access`, Docker socket or host network permission are requested in this foundation. Later LAN scanning will require explicit reviewed capabilities. Data survives App restart/upgrade in `/data`; generated code and images do not belong there. No dependency on Nmap, an MQTT broker, remote telemetry or a database server.

No existing NetAlertX, Presence App, Internet App or HA entities are modified.

See [DOCS.md](DOCS.md) for design boundaries and [CHANGELOG.md](CHANGELOG.md) for status.
