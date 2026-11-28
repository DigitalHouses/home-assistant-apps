# DigitalHouses Internet App

[![CI](https://github.com/DigitalHouses/home-assistant-apps/actions/workflows/validate.yml/badge.svg)](https://github.com/DigitalHouses/home-assistant-apps/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
![Type: Home Assistant App](https://img.shields.io/badge/type-Home%20Assistant%20App-41BDF5.svg)

**Monitor, diagnose and automatically recover your internet connection in Home Assistant.**

Track connectivity, speed, traffic and outages. Optionally let Home Assistant recover your ONT or router when connectivity is lost.

## Why I built this app

I wanted reliable internet monitoring in my own Home Assistant installation in Kazakhstan. Automatic Speedtest server selection occasionally chose a server in another country, including Poland. This produced misleading low-speed alerts, even when a manual test against a local server showed normal performance.

I wanted to choose several local providers in priority order, fall back when needed, and avoid declaring the internet down just because one ping target stopped responding.

## From Speedtest to Internet App

The [original DigitalHouses Speedtest project](https://community.home-assistant.io/t/digitalhouses-speedtest-preferred-ookla-servers-dual-connectivity-checks-and-performance-thresholds/1019636) began with those problems. Internet App extends that idea beyond speed tests: it tracks outages and traffic and can attempt to restore connectivity automatically.

## What can it do?

| Area | What the app provides |
| --- | --- |
| Availability | Independent ICMP checks of Google and Cloudflare plus local router reachability. |
| Quality | Download, upload, ping, jitter, packet loss when provided, editable download/upload/ping thresholds, preferred Ookla servers and fallback. |
| Traffic | Optional router counters, current transfer rates and WAN status; monthly traffic history. |
| Reliability | Current-month outage history, duration and availability; the last 20 successful speed tests. |
| Recovery | Optional automatic ONT or router reboot using existing Home Assistant buttons or switches. |

A failed Speedtest is not an internet outage. Failed tests preserve the last successful measurement and its timestamp and do not send technical error notifications. Measurements represent the last successful test, not necessarily current speed.

## Dashboard

- [English dashboard (YAML)](dashboards/en/13_internet.yaml)
- [Russian dashboard (YAML)](dashboards/ru/13_internet.yaml)

The view combines live reachability, recent measurements, monthly availability, traffic and recovery controls. MQTT Discovery creates monitoring entities automatically. You can use them in your own dashboards and automations.

Install Mushroom and Button Card (5.0 or newer) through HACS to use the supplied dashboard. Import one language as a view under `views:` in your dashboard YAML. The view has the same path and entities in both languages.

Real English dashboard screenshots will be added after live Home Assistant acceptance.

## How automatic recovery works

Recovery is disabled by default. Once you configure suitable local Home Assistant entities and enable recovery:

- **Smart:** if the internet is unavailable but the router responds locally, the app targets the ONT. If the router is unreachable, it targets the router.
- **Both:** the app attempts to restart the ONT and then the router in each cycle.

A reboot button or a switch controlling the equipment's power can be used. Boot wait, retry delay, maximum cycles and cooldown limit how often equipment is restarted. A Stop Recovery button suppresses further attempts for the current outage. The app persists cycle limits and cooldown across restarts.

Use locally controlled recovery devices that remain reachable when the internet or router fails. Do not use a relay that loses its own control connection when it switches off the equipment. Test the power restoration path before enabling recovery; a hard power loss or unreachable switch can prevent the app from restoring power. Recovery cannot fix every ISP outage.

## Requirements and quick start

1. Use Home Assistant OS with Apps support on AMD64 or ARM64. Configure MQTT in Home Assistant and a Supervisor MQTT broker service (for example, Mosquitto).
2. Open **Settings → Apps → App store → Repositories** and add:

   ```text
   https://github.com/DigitalHouses/home-assistant-apps
   ```

3. Install **DigitalHouses Internet App**. Set the router IP to its local LAN address; no router integration or ONT is required for basic monitoring.
4. Review the [statistics policy](../docs/standards/PRODUCT_TELEMETRY_POLICY.md) and explicitly enable statistics collection consent. The app does not start monitoring without it.
5. Review the [Ookla terms](https://www.speedtest.net/about/terms) and [privacy policy](https://www.speedtest.net/about/privacy) before using Speedtest. Set the periodic interval, or disable periodic tests. Leave the preferred server list empty for automatic selection.
6. Start the app and check its MQTT device. Run a manual Speedtest only if permitted by Ookla's terms. Enable Start on boot and Watchdog after verifying operation.

The app works without DigitalHouses Sync or any other DigitalHouses app. Sync is optional; its current implementation selects Russian resources. Import the English dashboard and notification package manually instead of installing both languages.

For notifications, use the [English](packages/locales/en/dh_internet_app_notification_local_package.yaml) or [Russian](packages/locales/ru/dh_internet_app_notification_local_package.yaml) Home Assistant package. For history graphs, merge the [Recorder selection](packages/common/dh_internet_app_global_package.yaml) with your existing Recorder configuration as appropriate. Enable Home Assistant packages if you do not already use them.

## Optional router integration

Map existing Home Assistant sensors for cumulative download and upload together if you want traffic accounting. WAN state and live transfer rates can be added independently. The app does not discover or configure router-specific SNMP or API integrations for you.

## Ookla CLI: limits and terms

The official Ookla CLI is a separate proprietary component, not covered by this project's MIT license. Its standard license restricts use to personal, non-commercial use on a single personal computer. Commercial or embedded use requires appropriate authorization; see [Ookla licensing](https://www.ookla.com/speedtest-embedded). Review the license before using it in your environment.

Tests use bandwidth and count toward provider restrictions. Use a conservative schedule; there is no guaranteed daily quota. When Ookla reports a rate limit, version 0.1.28 stops fallback and pauses manual tests, automatic tests and server discovery for 24 hours, including across restarts. This is a local protective pause, not a promise of when Ookla will lift its limit. Do not try to bypass it.

## Privacy

The current DigitalHouses policy requires explicit consent to minimal statistics before monitoring starts. Statistics contain the product, version and random installation identifier, with protocol/policy versions; country is derived server-side. No speed results, router data, IP fields, outage history, entity IDs or configuration are included in the telemetry payload. Monitoring continues if the statistics server is temporarily unavailable after consent. See the [telemetry policy](../docs/standards/PRODUCT_TELEMETRY_POLICY.md). Ookla has its own privacy terms.

## Moving from the original Speedtest App

Internet App is a separate product with different MQTT identities. There is no automatic migration of old entity IDs or Recorder history. Back up Home Assistant, record your old server IDs and thresholds, install and configure Internet App, update automations and dashboards to reference its entities, and disable the old app's scheduled tests to avoid duplicate Ookla calls. Preserve old history as needed.

## Documentation and feedback

- [Technical documentation](DOCS.md)
- [Implementation and migration details](docs/IMPLEMENTATION.md)
- [DH Sync compatibility](docs/DH_SYNC_COMPATIBILITY.md)
- [Changelog](CHANGELOG.md)
- [Report a bug or suggest a feature](https://github.com/DigitalHouses/home-assistant-apps/issues)

This is an independent community project, not affiliated with Home Assistant or Ookla. Feedback on different ISPs, hardware and recovery setups is welcome.
