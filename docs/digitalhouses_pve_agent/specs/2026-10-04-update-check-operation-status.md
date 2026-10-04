# Status semantics for update checks and installation

Date: 2026-10-04 · v0.5.57

The HA update card displays the current/most-recent operation, not a stale install-worker result.

- While checking a published stable release: `status=checking`.
- After a successful check with no newer release: `status=idle`, `available=false` (show «Обновлений нет»).
- After a successful check with a newer release: `status=idle`, `available=true` (show «Доступно обновление»).
- If a check fails: `status=error`, `available=null`, and `error` explains the check failure (do not claim «Нет обновлений»).
- While an install/rollback is running: the real active worker phase wins.
- A completed or failed installation may be displayed as the main status only until a later successful check. Both `installation_status` and `installation_error` remain available as independent diagnostic attributes afterward.
- Compare persisted UTC `update_check.json.checked_at` and `update_worker.json.updated_at`; this also survives agent restarts. No extra MQTT entity or client timer.

The fix does not touch the updater worker, GitHub release filtering, UPS safety preflight, installer, credentials, Proxmox guests or UPS state. Existing MQTT topics and entity IDs remain stable.
