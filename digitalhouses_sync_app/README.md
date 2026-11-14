# DigitalHouses Sync App — v0.2.1

## One rule: GitHub owner DigitalHouses

DH Sync discovers products from retained MQTT /sync messages and reads dashboard YAML from their GitHub repositories. **The only source-admission rule is that the GitHub repository owner is DigitalHouses.**

No hardcoded approved product list, no static per-product Git SHA pins, no fixed monorepo, no product_path equality gate, and no required Agent/App version range or DH-Compatible header.

Each explicit GitHub preview resolves the repository's default branch to a concrete SHA and reads every dashboards/ru/*.yaml from that single revision. This supports PVE (Proxmox plus UPS), Plex, Recorder, and future DigitalHouses products. Optional dashboard metadata is shown as information, not approval.

The separate 'Сравнить с файлами CORE' action compares actual YAML views with GitHub by Lovelace path, SHA-256 and parsed YAML. It reports changes, missing files, duplicate paths and Storage collisions without modifying them.

**Safety boundary:** GitHub URL/path parsing and bounded reads remain necessary to avoid malformed network requests. Supervisor homeassistant_config is mapped read_only: true. There is no Home Assistant API permission; admin-only Ingress allows GET only and returns HTTP 405 to all POST requests. No YAML Apply, backups, Restarts, Recorder changes or HACS installs in v0.2.1.

Organizational ownership is **not proof of dashboard compatibility**. A future write phase must separately provide exact change review, backups, rollback and explicit operator approval.

See docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md and docs/LOCAL_AUDIT_V2.md.
