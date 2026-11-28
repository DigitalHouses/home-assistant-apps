# Home Assistant Community post (draft — publish only after acceptance)

**Title:** DigitalHouses Network App – Local network inventory and device presence for Home Assistant

Hi everyone,

I built DigitalHouses Network App because I wanted a single place in Home Assistant to see what is connected to my local network, how each device was discovered, and when it was last positively observed.

Router integrations are useful, but they do not always report the same information. A router may retain an old IP address, a device may change its hostname, and not every device responds to ping. I wanted a local inventory that keeps these sources separate instead of treating every report as an equally reliable indication of availability.

Network App runs as a Home Assistant OS app (formerly add-on), with its own web interface through Ingress.

### What it does

- Discovers devices on the primary local IPv4 network using bounded ARP discovery.
- Reads existing Home Assistant router device trackers when available; no separate router credentials are needed.
- Enriches verified devices using Bonjour/mDNS, SSDP and WS-Discovery.
- Keeps persistent device identities, IP address history, notes and discovery sources in a local SQLite database.
- Highlights newly discovered devices and provides a local event journal.
- Supports optional monitoring of selected IP and MAC addresses, with MQTT events when availability changes are confirmed.
- Provides JSON diagnostics to help investigate conflicting observations.

Online is a positive observation, not an ICMP ping result. A failed discovery source alone must not be treated as evidence that a device has disappeared.

### Installation

Add the following repository to your Home Assistant App Store:

https://github.com/DigitalHouses/home-assistant-apps

Install DigitalHouses Network App, start it and open its web interface.

### Privacy and limitations

The inventory stays local. Optional installation statistics are disabled by default and do not include discovered devices, local IP addresses, MAC addresses or hostnames. MQTT is optional.

This version targets Home Assistant OS on amd64 and aarch64 and the primary local IPv4 subnet, up to /24. IPv6, VLAN discovery and larger networks are outside the current scope.

Project and documentation:
https://github.com/DigitalHouses/home-assistant-apps/tree/main/digitalhouses_network_app

I would particularly appreciate feedback from users with different router integrations, managed switches and devices that do not respond to ping. If you encounter unexpected discovery results, please review and redact the diagnostic JSON before sharing it.

Thank you!
