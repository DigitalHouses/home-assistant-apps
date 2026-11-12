# Plex Agent 0.8.6 implementation plan

Specification: the requested 0.8.6 scope and `docs/standards/DH_LINUX_AGENT_MANAGEMENT_STANDARD.md`.
Architecture: retain the installed Python/systemd/MQTT architecture and native INI. Foreground monitoring waits on the MQTT wake event while paused; callbacks only signal work. Local atomic status snapshots support the native CLI independently of MQTT.

- [ ] Regression-test overdue-heartbeat/startup disconnect; implement blocking pause and forced fresh reconnect collection/publication.
- [ ] Test and implement bounded MQTT reconnect, disconnected publication guards, PUBACK-only durable event removal and bounded outbox.
- [ ] Test and implement all native CLI keys, atomic validation/update, secret input, idempotence/restart and stale status checks.
- [ ] Test and implement host identity, diagnostic Discovery entities and atomic runtime status at transitions/30-second cadence.
- [ ] Update installer, compact root reference, unattended native config provisioning, version and product documentation.
- [ ] Run unittest discovery and available broader checks; review diff for product scope, identity preservation and security.

No deployment, production VM changes, git commits or pushes. Existing worktree starts at origin/main 945fa53e. Changes stay in the Plex product.

Review focus: event wake races, stale process snapshots, offline publication queueing, multi-key validation rollback, secrets in errors, reconnect pending cache freshness, network-address changes.
