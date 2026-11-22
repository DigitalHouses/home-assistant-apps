# DH Sync 0.6.3 — Documentation

The active specification is [DH Sync Developer Standard](../docs/standards/DH_SYNC_DEVELOPER_STANDARD.md).

MQTT retained `/sync` supplies product identity; GitHub YAML supplies panel composition and product resources. No migrations, compatibility gates, manual confirmation, or source-provided panel routing. Views are published through HA's supported Storage dashboard WebSocket API; packages use atomic file sync. Other Apps/Agents are not changed. With manual «Проверить и обновить»,
changed or previously unapplied Recorder packages trigger a validated,
one-time Home Assistant Core restart request; automatic MQTT/hourly sync
does not restart Core. No HAOS restart or extra authorization token.
