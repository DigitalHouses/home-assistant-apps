# Changelog

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
