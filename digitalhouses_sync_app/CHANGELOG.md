# Changelog

## 0.1.0

- First opt-in YAML view controller with admin-only Ingress and Supervisor Core API.
- Pinned version-compatible CORE v3 PVE/UPS and Plex resources.
- Detect duplicates, unexpected local edits, pinned Git metadata and incompatible agent versions.
- Durable transaction journal, SHA-verified backup, HA config validation, Lovelace readback and rollback.
- Default allow_changes: false; no automatic HA writes or restarts.
- DH Sync Discovery Contract v1: retained MQTT metadata for installed DigitalHouses products, strict GitHub repository-owner validation, and read-only catalog of sources and versions.
- Regression coverage for the CORE retained MQTT payloads: PVE Agent 0.5.89 and Plex Agent 0.8.18 (catalog visible even when YAML Apply is blocked).
- This first release is strictly operator-controlled: no automatic YAML updates, agent updates, HACS installation, or background changes.

## 0.0.1 — unpublished prototype

- MQTT product inventory and diagnostics.
- Read-only Plex adoption preflight and separately gated Storage migration prototype.
