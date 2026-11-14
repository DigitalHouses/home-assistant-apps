# Changelog

## 0.2.2

- Remove DH-Compatible-Agent/App headers from canonical PVE, UPS, Plex and Recorder dashboards; no compatibility declaration is required.
- Remove legacy compatibility text, range display, `constraint` and unreachable version-block status from the read-only DH Sync preview and CORE audit.
- Keep GitHub owner `DigitalHouses` as the only source-admission rule, while retaining safe parsing, read-only access and manual review before any future Apply.
- Update tests and product documentation to remove version-range and product-registry admission assumptions.

## 0.2.1

- Reduce source admission to the GitHub repository owner DigitalHouses. Remove the fixed monorepo check, product-specific SHA allowlist, product-path equality rule, agent/app version gates and required DH-Compatible metadata.
- Resolve each GitHub repository's default branch to a commit SHA on explicit user request. Discover dashboards/ru/*.yaml from that SHA; support Recorder and future products without central registration.
- Keep dashboard metadata as optional informational text. The local CORE diff works across DigitalHouses repositories and safe relative product paths.
- Retain technical URL/path parsing to prevent malformed network requests and retain read-only HAOS access; no Apply, automatic YAML writes, updates or restarts.

## 0.2.0

- Add operator-triggered read-only CORE HAOS YAML audit through Supervisor homeassistant_config map with read_only: true.
- Compare pinned PVE Proxmox/UPS and Plex resources against local DigitalHouses views by Lovelace path, exact SHA-256 and parsed YAML. Present a bounded, HTML-escaped diff of modified view YAML.
- Detect absent views, occupied filenames, duplicate YAML paths and matching Lovelace Storage views including modern .storage/lovelace.<dashboard> variants, without exposing Storage JSON.
- Default Ingress never scans local files; GitHub preview and local audit require distinct GET actions. HTTP POST still returns 405.
- Fail closed for missing or writable mount, symlink, unreadable/malformed or oversized files, and source identity mismatch.
- No HA Core API, writable HA mount, backup, Apply, rollback, Recorder mutation or automatic restart in v0.2.0.

## 0.1.4

- Pin the immutable approved merged PR #502 commit for both PVE Proxmox/UPS views and merged PR #508 for Plex Dashboard; do not fetch unreviewed Draft sources.
- Confirm compatibility preview for PVE Agent 0.5.89 (>=0.5.88,<0.5.90) and Plex Agent 0.8.18 (>=0.8.17,<0.8.19), while future versions still fail closed.
- Improve GitHub resource table column widths and natural word wrapping for longer Russian names.
- Retain GET-only, admin-only preview with no Home Assistant API/config mount, file comparison, Apply, backup, rollback, automatic agent updates or YAML writes.

## 0.1.3

- Add operator-initiated, read-only preview of canonical RU dashboards at immutable pinned GitHub commits.
- Discover any number of YAML views under each allowed product's `dashboards/ru/`, including both PVE views and the Plex view, without embedding YAML filenames in MQTT.
- Display view revision, compatibility range, source review state and blocked reasons for running Agent 0.5.89/0.8.18.
- Validate standalone YAML, duplicate paths and GitHub response origins. Do not introduce HA API access, config mount, YAML Apply or background polling.
- Add HAOS container smoke coverage and unit tests for GitHub listing, version gates and read-only Ingress.

## 0.1.2

- Show the installed release version in the Ingress heading and startup log using APP_VERSION instead of hardcoding v0.1.0.
- Recognize the Sync App's own canonical product-level availability topic and display Online after receiving its retained MQTT status.
- Add regression tests for release-version rendering, escaped header output, and self availability; no change to YAML, HA API permissions, or MQTT Discovery Contract v1.

## 0.1.1

- Fix HAOS startup crash with Alpine `py3-paho-mqtt` 1.x, where `mqtt.CallbackAPIVersion` is not available.
- Use Paho 2.x callback API when present and a compatible 1.x client otherwise; accept both four- and five-argument connect callbacks.
- Add unit regression tests for both Paho API generations and a smoke test that executes the MQTT client constructor inside the actual built HAOS image.
- No changes to broker authentication, MQTT topic names, Dashboard YAML, HA permissions or read-only Ingress behavior.

## 0.1.0

- First HAOS Ingress read-only catalog of detected DigitalHouses agents and apps.
- Discover product ID, running version, instance and owning GitHub repository from retained MQTT Discovery Contract v1 messages.
- Strictly accept only direct GitHub repositories owned by `DigitalHouses`; reject URL spoofing and mismatched product identities.
- Display product-level online/offline/unknown availability separately from retained source metadata. Offline never means uninstall.
- Publish its own Version/Started-at diagnostics and source metadata using the existing HAOS MQTT service.
- No Home Assistant API permission, configuration mount, YAML Apply or Rollback, external services, dynamic downloads, Home Assistant restarts or executable agent updates in installed v0.1.0.
- Keep view transaction and migration prototypes in source for future product-compatibility-gated integration; they are not part of the running v0.1.0 UI.

## 0.0.1 — unpublished prototype

- MQTT product inventory and diagnostics.
- Read-only Plex adoption preflight and separately gated Storage migration prototype.
