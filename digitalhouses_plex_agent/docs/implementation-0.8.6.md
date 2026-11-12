# Plex Agent 0.8.6 implementation plan

Specification: the requested 0.8.6 scope and `docs/standards/DH_LINUX_AGENT_MANAGEMENT_STANDARD.md`.
Architecture: retain the installed Python/systemd/MQTT architecture and native INI. Foreground monitoring waits on the MQTT wake event while paused; callbacks only signal work. Local atomic status snapshots support the native CLI independently of MQTT.

- [x] Regression-test overdue-heartbeat/startup disconnect; implement blocking pause and forced fresh reconnect collection/publication.
- [x] Test and implement bounded MQTT reconnect, disconnected publication guards, PUBACK-only durable event removal and bounded outbox.
- [x] Test and implement all native CLI keys, atomic validation/update, secret input, idempotence/restart and stale status checks.
- [x] Test and implement host identity, diagnostic Discovery entities and atomic runtime status at transitions/30-second cadence.
- [x] Update installer, compact root reference, unattended native config provisioning, version and product documentation.
- [x] Run unittest discovery and available broader checks; review diff for product scope, identity preservation and security.

No deployment, production VM changes, git commits or pushes. Existing worktree starts at origin/main 945fa53e. Changes stay in the Plex product.

Review focus: event wake races, stale process snapshots, offline publication queueing, multi-key validation rollback, secrets in errors, reconnect pending cache freshness, network-address changes.

## Review and acceptance evidence

- Deterministic main-loop tests cover initial offline startup, overdue heartbeat after disconnect, disconnect during an outbox ACK wait, and failed-first-collector scheduling. Foreground process/GPU/API work is mocked at its boundaries; no VM is contacted.
- Reconnect publication forces a newly collected snapshot and discards older pending group values first. Host identity updates at startup/reconnect and every 60 seconds to detect network changes; runtime status updates at transitions and every 30 seconds.
- MQTT tests cover bounded queues, disconnected publication guards, callback lock ordering, receipt reuse after timeout/send loss, and PUBACK-only durable outbox removal.
- CLI tests cover every key, native cross-field validation, comment/mode preservation, idempotence, secret input, stopped service updates, restart rollback, stale status detection, and arbitrary caller working directories.
- The existing updater now backs up the new CLI/reference artifacts. An already running 0.8.5 updater retains its historical backup list during synchronous rollback; the wrapper reports ERROR if rollback restores a version without the CLI. Upgrade/failure acceptance from that version remains a live release check.
- Local full unittest discovery has dependency import blockers: `pytest`, `paho-mqtt`, and `psutil` are absent. The environment also lacks venv ensurepip and cannot resolve PyPI; no system packages or production hosts were modified to work around this. Dependency-free unit cases and plain functions were run separately. Repository validation, compilation, shell syntax and diff whitespace checks pass.
- CI, real-broker/systemd/HA/VM acceptance and published GitHub release are not claimed. No git commits, pushes or deployments were made.
