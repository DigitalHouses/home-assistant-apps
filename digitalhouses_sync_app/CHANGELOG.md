# Changelog

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
