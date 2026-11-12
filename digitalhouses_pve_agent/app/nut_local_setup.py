"""Installer-only NUT address reconciliation for a locally managed PVE UPS."""
from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .cli import _atomic_write, set_config
from .config import load_config
from .restart_safety import guard_restart


def _run(command: list[str], *, run=subprocess.run, timeout: int = 7) -> str:
    return run(command, text=True, capture_output=True, check=True, timeout=timeout).stdout


def local_status(name: str, *, run=subprocess.run) -> set[str] | None:
    try:
        return set(_run(['upsc', f'{name}@127.0.0.1:3493', 'ups.status'], run=run).split())
    except (OSError, subprocess.SubprocessError):
        return None


def management_ip(*, run=subprocess.run) -> ipaddress.IPv4Interface | None:
    try:
        output = _run(['ip', '-4', '-o', 'addr', 'show', 'dev', 'vmbr0'], run=run)
    except (OSError, subprocess.SubprocessError):
        return None
    addresses = re.findall(r'\binet\s+(\d+\.\d+\.\d+\.\d+/\d+)\b', output)
    return ipaddress.IPv4Interface(addresses[0]) if len(addresses) == 1 else None


def reconcile_nut_listener(*, nut_dir: Path, pve_ip: ipaddress.IPv4Interface | None,
                           selected: str, run=subprocess.run) -> bool:
    """Only a single stale same-subnet netserver LISTEN may be repaired."""
    conf, mode, mon = (nut_dir / name for name in ('upsd.conf', 'nut.conf', 'upsmon.conf'))
    if not pve_ip or not all(x.is_file() and not x.is_symlink() for x in (conf, mode, mon)):
        return False
    if not re.search(r'^\s*MODE\s*=\s*netserver\s*$', mode.read_text(), re.M):
        return False
    if not re.search(r'^\s*MONITOR\s+' + re.escape(selected) + r'@127\.0\.0\.1\s', mon.read_text(), re.M):
        return False
    contents = conf.read_text()
    lines = contents.splitlines(keepends=True)
    remote = []
    loopback = False
    pattern = re.compile(r'^(\s*LISTEN\s+)(\d+\.\d+\.\d+\.\d+)(\s+3493\s*(?:#.*)?)$', re.I)
    for i, line in enumerate(lines):
        match = pattern.fullmatch(line.rstrip('\r\n'))
        if not match:
            if re.match(r'^\s*LISTEN\s+', line, re.I):
                return False
            continue
        if match.group(2) == '127.0.0.1':
            loopback = True
        else:
            remote.append((i, match, ipaddress.IPv4Address(match.group(2))))
    if not loopback or len(remote) != 1:
        return False
    idx, match, old_ip = remote[0]
    if old_ip == pve_ip.ip or old_ip not in pve_ip.network:
        return False
    try:
        all_ips = _run(['ip', '-4', '-o', 'addr', 'show'], run=run)
    except (OSError, subprocess.SubprocessError):
        return False
    if str(old_ip) in re.findall(r'\binet\s+(\d+\.\d+\.\d+\.\d+)/', all_ips):
        return False
    # Preserve original NUT configuration and ownership; never silently overwrite
    # a previous backup from an earlier migration.
    backup = conf.with_name(conf.name + '.dh-pre-ip-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    if backup.exists():
        raise RuntimeError('NUT listener migration backup already exists')
    suffix = '\n' if lines[idx].endswith('\n') else ''
    lines[idx] = f'{match.group(1)}{pve_ip.ip}{match.group(3)}{suffix}'
    shutil.copy2(conf, backup)
    try:
        _atomic_write(conf, ''.join(lines).encode(), conf.stat())
        _run(['systemctl', 'restart', 'nut-server.service'], run=run, timeout=35)
        status = local_status(selected, run=run)
        if not status or 'OL' not in status or status.intersection({'OB', 'LB', 'FSD', 'DISCHRG'}):
            raise RuntimeError('NUT local UPS check failed after listener migration')
    except Exception:
        shutil.copy2(backup, conf)
        _run(['systemctl', 'restart', 'nut-server.service'], run=run, timeout=35)
        raise
    print(f'NUT LISTEN: {old_ip} -> {pve_ip.ip}; backup: {backup}')
    return True


def configure(prepared: Path, state_dir: Path, *, nut_dir: Path = Path('/etc/nut'),
              run=subprocess.run) -> None:
    config = load_config(prepared)
    try:
        selected = json.loads((state_dir / 'ups_selection.json').read_text()).get('selected_name')
    except (OSError, ValueError, AttributeError):
        selected = None
    name = selected if isinstance(selected, str) and re.fullmatch(r'[A-Za-z0-9_.-]+', selected) else (
        config.ups.name if config.ups.enabled else None
    )
    if not name:
        return
    status = local_status(name, run=run)
    if status is None:
        return  # No local NUT: preserve existing remote server.
    if config.ups.host != '127.0.0.1' or config.ups.port != 3493:
        set_config(prepared, ['ups_host=127.0.0.1', 'ups_port=3493'], prepare=True)
        print('NUT: selected local 127.0.0.1:3493 for the PVE Agent')
    # A committed shutdown or a reported unsafe UPS state MUST abort the install.
    if not isinstance(selected, str) or not selected:
        return  # First install: no selected UPS yet.
    guard_restart(load_config(prepared), state_dir=state_dir)
    reconcile_nut_listener(nut_dir=nut_dir, pve_ip=management_ip(run=run),
                           selected=name, run=run)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    args = parser.parse_args()
    configure(args.prepared, args.state_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
