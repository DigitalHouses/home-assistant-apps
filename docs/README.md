# DigitalHouses Documentation

This directory separates ecosystem-wide standards from product-specific engineering records.

## Shared standards

- [DigitalHouses Application Standard](standards/DIGITALHOUSES_APP_STANDARD.md) — common contract for DigitalHouses Home Assistant Apps and Linux agents.
- [DigitalHouses Contract Data Policy](standards/CONTRACT_DATA_POLICY.md) — required/optional runtime data semantics, explicit contract failures, and repository-wide prohibition of silent fallback across contract boundaries.
- [DigitalHouses Release Policy](standards/RELEASE_POLICY.md) — product versions, release tags, GitHub Releases, immutable artifacts, and release provenance.
- [Immutable Delivery, Compact Backup and Telemetry Standard](standards/IMMUTABLE_DELIVERY_AND_TELEMETRY_STANDARD.md) — mandatory target architecture and rollout for all current DigitalHouses products.
- [DigitalHouses Product Telemetry Policy](standards/PRODUCT_TELEMETRY_POLICY.md) — consent, privacy, retained-history lifecycle, deletion, and telemetry boundaries.
- [DigitalHouses Telemetry Protocol v1](standards/TELEMETRY_PROTOCOL_V1.md) — shared heartbeat/delete wire contract and server semantics.
- [DigitalHouses Telemetry Implementation Guide](standards/TELEMETRY_IMPLEMENTATION_GUIDE.md) — practical checklist, persistence/timing rules, production architecture, and current rollout status for product-specific implementation work.
- [DigitalHouses Repository Governance](standards/REPOSITORY_GOVERNANCE.md) — `main`, pull requests, CI, merge strategy, and branch lifecycle.

## Product engineering records

- [DigitalHouses PVE Agent](digitalhouses_pve_agent/) — architecture specifications, implementation plans, audits, and technical debt for the PVE agent.
- [DigitalHouses Plex Agent](digitalhouses_plex_agent/) — architecture specification and implementation plan for the Plex agent.

Product README files remain the source for installation and user-facing operational documentation. Files under the product documentation directories are engineering design records and may describe historical implementation states.
