from __future__ import annotations

import argparse
from pathlib import Path

from .state_store import StateStore
from .ups_legacy_timer import legacy_timer_present
from .ups_policy import (
    DEFAULT_RUNTIME_RESERVE_SECONDS,
    DEFAULT_SHUTDOWN_BATTERY_CHARGE_THRESHOLD_PERCENT,
    UpsPolicyDraft,
)


LEGACY_POLICY_KEYS = {
    "on_battery_delay_minutes",
    "power_restore_delay_seconds",
}

DEFAULT_V2_DRAFT = UpsPolicyDraft(
    shutdown_battery_charge_threshold_percent=(
        DEFAULT_SHUTDOWN_BATTERY_CHARGE_THRESHOLD_PERCENT
    ),
    runtime_reserve_seconds=DEFAULT_RUNTIME_RESERVE_SECONDS,
)


def _is_legacy_policy_mapping(value: object) -> bool:
    return isinstance(value, dict) and bool(LEGACY_POLICY_KEYS & set(value))


def _is_runtime_normalized_legacy_state(state: dict[str, object]) -> bool:
    return (
        state.get("policy_status") == "Legacy policy"
        and state.get("policy_active") is None
    )


def _read_upssched(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def migrate_retired_legacy_policy_state(
    *,
    state_store: StateStore,
    upssched_path: Path = Path("/etc/nut/upssched.conf"),
) -> bool:
    state = state_store.load()
    if not state:
        return False

    legacy_state = (
        _is_legacy_policy_mapping(state.get("policy_active"))
        or _is_legacy_policy_mapping(state.get("policy_draft"))
        or _is_runtime_normalized_legacy_state(state)
    )
    if not legacy_state:
        return False

    if legacy_timer_present(_read_upssched(upssched_path)):
        return False

    updated = dict(state)
    updated["policy_active"] = None
    updated["policy_draft"] = DEFAULT_V2_DRAFT.as_dict()
    updated["policy_status"] = "Commissioning"
    updated["policy_apply_result"] = "Not applied"
    updated["policy_last_applied"] = None
    updated["policy_revision"] = 0
    updated["policy_hash"] = None
    state_store.save(updated)
    return True


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize retired legacy UPS policy state before DigitalHouses PVE Agent starts."
    )
    parser.add_argument(
        "--state-dir",
        default="/var/lib/digitalhouses_pve_agent",
        help="DigitalHouses PVE Agent state directory",
    )
    parser.add_argument(
        "--upssched-path",
        default="/etc/nut/upssched.conf",
        help="Read-only NUT upssched.conf path",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    migrate_retired_legacy_policy_state(
        state_store=StateStore(Path(args.state_dir) / "ups_runtime.json"),
        upssched_path=Path(args.upssched_path),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
