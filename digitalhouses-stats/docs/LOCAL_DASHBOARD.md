# Local dashboard

DigitalHouses Stats exposes two separate local processes.

```text
Internet agents
  -> Cloudflare
  -> Cloudflare Tunnel
  -> 127.0.0.1:8080
  -> telemetry ingestion API

LAN browser
  -> http://192.168.11.254/
  -> nginx
  -> 127.0.0.1:8081
  -> local statistics API
```

The public telemetry process intentionally does not expose statistics routes.
The local statistics API listens only on loopback and nginx listens only on the
server LAN address.

## Local URL

```text
http://192.168.11.254/
```

## Local API

nginx maps the following browser paths to the loopback-only statistics API:

```text
/api/summary
/api/products
/api/versions
/api/countries
/api/history?days=30
```

The underlying API process uses `/v1/stats/*` on `127.0.0.1:8081`.

Version and country distributions count each installation only in the value
from its latest heartbeat. History is grouped by UTC calendar day.

## Installation

From the checked-out application directory:

```bash
chmod +x deploy/install-local-dashboard.sh
deploy/install-local-dashboard.sh
```

The installer:

- installs nginx;
- installs the dashboard API systemd unit;
- copies static dashboard assets to `/var/www/digitalhouses-stats`;
- installs an nginx virtual host bound to `192.168.11.254:80`;
- disables the Debian default nginx site;
- verifies both loopback API and LAN nginx health.

No JavaScript libraries, fonts, images, or CDN resources are required.


## Dashboard metrics

The dashboard summary shows:

- known installations;
- active installations over 24 hours, 7 days and 30 days;
- total accepted heartbeat count;
- the latest heartbeat time, rendered locally in the browser.

The activity chart compares unique active installations with accepted heartbeat
volume for each UTC calendar day. The selected period also shows total
heartbeats, number of active days and peak active installations.
