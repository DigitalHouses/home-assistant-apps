# DH Sync 0.6.0 — Documentation

The active specification is [DH Sync Developer Standard](../docs/standards/DH_SYNC_DEVELOPER_STANDARD.md).

MQTT retained `/sync` supplies product identity; GitHub YAML supplies panel composition and product resources. No migrations, compatibility gates, manual confirmation, or source-provided panel routing. Views are published through HA's supported Storage dashboard WebSocket API; packages use atomic file sync. Other Apps/Agents are not changed.
