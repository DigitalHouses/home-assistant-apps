"""Fail-closed local restart preflight; independent of MQTT and cached samples."""
from dataclasses import replace
import json
from pathlib import Path
import re
import sys

from .config import AppConfig
from .ups_nut import NutReadError, read_ups

STATE_DIR = Path('/var/lib/digitalhouses_pve_agent')


def _object(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError) as exc:
        raise RuntimeError('UPS safety evidence unavailable or invalid; restart denied') from exc


def guard_restart(
    config: AppConfig, *, state_dir: Path = STATE_DIR, allow_nut_unavailable: bool = False,
) -> None:
    """Require safe power for CLI restart; installer may tolerate missing NUT.

    Committed shutdown and an observed unsafe UPS status ALWAYS deny the restart.
    Only a nonresponsive NUT endpoint / absent selection may be tolerated by
    installation so that the agent can diagnose/configure UPS monitoring.
    """
    # History persists an accepted FSD even if the process exits before any
    # subsequent runtime status write. Previous boots are not active commitments.
    history = _object(state_dir / 'shutdown_history.json')
    current = history.get('current_boot')
    if current is not None and not isinstance(current, dict):
        raise RuntimeError('UPS shutdown evidence invalid; restart denied')
    if isinstance(current, dict) and current.get('fsd_at'):
        try:
            boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        except OSError as exc:
            raise RuntimeError('Unable to verify UPS shutdown boot; restart denied') from exc
        if not current.get('boot_id') or current['boot_id'] == boot:
            raise RuntimeError('UPS shutdown already committed; restart denied')
    commitment = _object(state_dir / 'ups_shutdown_commit.json')
    if commitment.get('committed'):
        try:
            boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        except OSError as exc:
            raise RuntimeError('Unable to verify UPS shutdown boot; restart denied') from exc
        if not commitment.get('boot_id') or commitment['boot_id'] == boot:
            raise RuntimeError('UPS shutdown already committed; restart denied')
    selection = _object(state_dir / 'ups_selection.json')
    name = selection.get('selected_name')
    if name is None or name == '':
        if config.ups.enabled:
            if allow_nut_unavailable:
                print('WARNING: UPS is enabled but not selected; installation continues for UPS diagnosis', file=sys.stderr)
                return
            raise RuntimeError('UPS enabled but selection unknown; restart denied')
        return
    if not isinstance(name, str) or re.fullmatch(r'[a-zA-Z0-9_.-]+', name) is None:
        raise RuntimeError('Invalid selected UPS name; restart denied')
    try:
        snapshot = read_ups(replace(config.ups, enabled=True, name=name))
    except NutReadError as exc:
        if allow_nut_unavailable:
            print('WARNING: NUT/UPS unavailable; installation continues, UPS monitoring needs attention', file=sys.stderr)
            return
        raise RuntimeError('Unable to read fresh UPS state; restart denied') from exc
    if (snapshot is None or not snapshot.line_power or snapshot.on_battery
            or snapshot.low_battery or snapshot.discharging or 'FSD' in snapshot.status_tokens):
        raise RuntimeError('UPS power not confirmed safe; restart denied')
