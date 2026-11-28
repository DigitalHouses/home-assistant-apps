# International release acceptance

Status: live acceptance checklist, not evidence of completed acceptance. Maintainer approved direct stable publication of 0.1.33 without a separate RC. Both existing installations were backed up before publication.

## Upgrade on an existing test HAOS installation

1. Record the current version and take an HAOS App backup (cold backup; do not run Reset). Retain the existing SQLite file and the App data directory, including telemetry identity if present. Keep the backup local.
2. Record an authenticated diagnostic export before upgrade. Compare stable UUID/MAC pairs, Notes, retained event/history rows, Presence subscriptions and labels, and settings; do not expect counts/timestamps to remain unchanged while scans continue. Confirm SQLite integrity on a safe offline backup copy, not on a partially copied live database.
3. Install the released image through the approved HAOS workflow; both existing installations may auto-update. Verify startup and upgrade logs and repeat the comparison. Test restart and re-open Ingress. Do not clear inventory or manipulate live data to obtain screenshots.
4. Check RU and EN on all tabs, tooltips, settings, event journal, Presence menu, diagnostic export and Reset cancellation without executing Reset. Check persisted language across reload. Verify device names and Notes remain unchanged.
5. Check normal ARP, HA router, mDNS, SSDP and WSD cycles and a confirmed Presence transition using a controlled test device. Verify MQTT reconnect and retained DH Sync announcement when an MQTT broker is available.
6. Verify that telemetry remains optional and off by default. On an installation already opted in, confirm DH Stats shows the tested version; do not enable consent silently.
7. Record CPU and RSS (idle and scan peak), storage used by SQLite/WAL and logs, and receive/transmit byte or packet deltas over at least 15 minutes including multiple discovery cycles. Use the Supervisor app stats and read-only host/app metrics where available. Compare against version 0.1.32 under similar conditions. Host networking may make container-level network counters aggregate rather than product-specific; label this limitation and use non-intrusive per-process/source observations where possible.
8. Capture real English Ingress screens (Devices, Sources, Event log, Settings/Presence), redact private device identifiers, addresses, notes and timestamps if necessary, and add only the reviewed images to public documentation.
9. Verify both native architecture builds and provenance using the Network-specific registry and image configuration. Do not reuse a published version number. Record any post-release acceptance failures and address them in a new version.
10. Verify GitHub release, canonical tag, exact source SHA and both GHCR architecture digests, and test the actual final released image on HAOS before forum publication.

## Out of scope

IPv6, VLAN, subnets larger than /24, scanner redesign, changes to telemetry consent, and unrelated DigitalHouses products.
