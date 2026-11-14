"""Developer-only CLI; disabled unless explicitly unlocked for a test HA.

Do not enable this program in the production App until authenticated HA access,
UI opt-in, backup/rollback and acceptance on two HA installations are approved.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from adoption import AdoptionError, canonical
from ha_bridge import HAWebSocketBridge
from storage_migration import PlexMigration, MigrationError


def main() -> int:
    p = argparse.ArgumentParser(description="DH Sync experimental Plex Storage migration")
    p.add_argument("action", choices=("inspect", "stage", "cutover", "rollback"))
    p.add_argument("--source-url-path", required=True)
    p.add_argument("--storage-file", required=True)
    p.add_argument("--home", type=Path, default=Path("/homeassistant"))
    p.add_argument("--data", type=Path, default=Path("/data"))
    p.add_argument("--confirm-stage", action="store_true")
    p.add_argument("--confirm-rendered", action="store_true")
    p.add_argument("--confirm-rollback", action="store_true")
    args = p.parse_args()
    if os.environ.get("DH_SYNC_MIGRATION_DEV_ENABLE") != "1":
        print(json.dumps({"ok": False, "error": "Development migration explicitly disabled"}))
        return 2
    try:
        url = os.environ.get("DH_SYNC_HA_URL", "")
        token = os.environ.get("DH_SYNC_HA_ADMIN_TOKEN", "")
        bridge = HAWebSocketBridge(
            base_url=url,
            admin_token=token,
            home=args.home,
            storage_file=args.storage_file,
        )
        engine = PlexMigration(
            args.home, args.data, bridge, source_url_path=args.source_url_path
        )
        view, _ = canonical()
        if args.action == "inspect":
            result = {
                "source_url_path": args.source_url_path,
                "destination": "digital-houses",
                "installed_agent_version": bridge.read_plex_agent_version(),
                "migration_journal_exists": engine.state_file.exists(),
                "storage_matches_disk": (
                    bridge.read_storage(engine.source) ==
                    bridge.read_persisted_storage(engine.source)
                ),
                "no_writes": True,
            }
        elif args.action == "stage":
            if not args.confirm_stage:
                raise MigrationError("--confirm-stage is required")
            result = engine.stage(
                view,
                runtime_version=bridge.read_plex_agent_version(),
                confirm=True,
            )
        elif args.action == "cutover":
            result = engine.cutover(view, confirm_rendered=args.confirm_rendered)
        else:
            result = engine.rollback(confirm=args.confirm_rollback)
    except (AdoptionError, MigrationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **result}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
