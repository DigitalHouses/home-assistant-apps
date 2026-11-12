"""Local administrator CLI. The native INI remains the only configuration store."""
from __future__ import annotations

import configparser
from dataclasses import fields
from datetime import datetime, timezone
import fcntl
import getpass
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import warnings
from typing import Mapping, Sequence

from .runtime_status import load_build_info
from .restart_safety import guard_restart
from .config import ConfigError, load_config

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path('/etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf')
RUNTIME_STATUS = Path('/run/digitalhouses_pve_agent/runtime_status.json')
SERVICE = 'digitalhouses_pve_agent.service'
REFERENCE = 'https://github.com/DigitalHouses/home-assistant-apps/tree/main/digitalhouses_pve_agent'
UPDATE_SERVICE = 'digitalhouses_pve_agent-update.service'
STATE_DIR = Path('/var/lib/digitalhouses_pve_agent')

class CliError(ValueError):
    """An administrator-facing error containing no untrusted input."""


# Canonical dotted names plus convenient administrator aliases. Ignored legacy
# ups.poll_interval_seconds is intentionally not configurable.
KEYS = {}
for _section, _fields in {
    'general': ('instance_id', 'node_name', 'log_level'),
    'mqtt': ('host', 'port', 'username', 'password', 'topic_prefix', 'discovery_prefix', 'keepalive_seconds'),
    'ups': ('enabled', 'name', 'host', 'port', 'command_timeout_seconds', 'command_username', 'command_password'),
    'events': ('pve_problem_debounce_seconds',),
    'telemetry': ('enabled',),
}.items():
    for _field in _fields:
        _target = (_section, _field)
        KEYS[f'{_section}.{_field}'] = _target
        KEYS[_field if _section == 'general' else f'{_section}_{_field}'] = _target
KEYS['mqtt_ip'] = KEYS['mqtt_host']
KEYS['mqtt_keepalive'] = KEYS['mqtt_keepalive_seconds']
SECRETS = {('mqtt', 'password'), ('ups', 'command_password')}



def service_info() -> dict[str, str]:
    result = subprocess.run(
        ['systemctl', 'show', SERVICE, '--property=ActiveState,SubState,MainPID,ActiveEnterTimestampMonotonic,ExecMainStartTimestampMonotonic'],
        text=True, capture_output=True, timeout=2, check=True,
    )
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def restart_service() -> None:
    result = subprocess.run(['systemctl', 'restart', SERVICE], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('systemctl restart failed; inspect systemctl status ' + SERVICE)


def _edit_ini(text: str, changes: dict[tuple[str, str], str]) -> str:
    """Replace intended assignments, retaining unrelated lines verbatim.

    ConfigParser's native dialect has full-line comments, not inline comments.
    Remove only continuations belonging to the changed value.
    """
    lines = text.splitlines(keepends=True)
    remaining = dict(changes)
    result: list[str] = []
    section = None
    replacing_indent: int | None = None

    def append_missing(current: str | None) -> None:
        for (sec, key), value in list(remaining.items()):
            if sec == current:
                if result and not result[-1].endswith('\n'):
                    result[-1] += '\n'
                result.append(f'{key} = {value}\n')
                del remaining[(sec, key)]

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(('#', ';')):
            result.append(line)
            continue
        header = re.match(r'^\s*\[([^\]]+)\]', line)
        if header:
            append_missing(section)
            section = header.group(1)
            replacing_indent = None
            result.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if replacing_indent is not None and indent > replacing_indent:
            continue
        replacing_indent = None
        assignment = re.match(r'^([ \t]*)([^\s=:][^=:\r\n]*?)([ \t]*[=:][ \t]*)(.*?)(\r?\n)?$', line)
        if assignment:
            key = assignment.group(2).strip().lower()
            target = (section, key)
            if target in remaining:
                result.append(assignment.group(1) + assignment.group(2) + assignment.group(3) + remaining.pop(target) + (assignment.group(5) or '\n'))
                replacing_indent = indent
                continue
        result.append(line)
    append_missing(section)
    for sec in dict.fromkeys(sec for sec, _ in remaining):
        if result and not result[-1].endswith('\n'):
            result[-1] += '\n'
        result.append(f'\n[{sec}]\n')
        append_missing(sec)
    return ''.join(result)


def _atomic_write(path: Path, content: bytes, metadata: os.stat_result) -> None:
    fd, filename = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, 'wb') as handle:
            if (os.geteuid() == 0 or (metadata.st_uid, metadata.st_gid) != (os.geteuid(), os.getegid())):
                os.fchown(handle.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(handle.fileno(), stat.S_IMODE(metadata.st_mode))
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _validate(path: Path):
    config = load_config(path)
    for section in fields(config):
        for field in fields(getattr(config, section.name)):
            value = getattr(getattr(config, section.name), field.name)
            if isinstance(value, float) and not math.isfinite(value):
                raise CliError(f'{section.name}.{field.name} must be finite')
    return config


def set_config(path: Path, pairs: Sequence[str], *, prepare: bool = False,
               hidden_values: Mapping[tuple[str, str], str] | None = None) -> bool:
    if not pairs:
        raise CliError('set requires key=value arguments')
    changes: dict[tuple[str, str], str] = {}
    for pair in pairs:
        key, separator, value = pair.partition('=')
        if key not in KEYS:
            raise CliError('unknown configuration key (see help)')
        if KEYS[key] in SECRETS:
            if hidden_values is not None and KEYS[key] in hidden_values:
                if separator:
                    raise CliError('internal hidden password entry must not use key=value')
                value = hidden_values[KEYS[key]]
            elif separator:
                if value != '-':
                    raise CliError('password requires hidden entry or key=- with redirected stdin')
                if sys.stdin.isatty():
                    raise CliError('stdin password mode requires redirected input; use bare password key for a hidden terminal prompt')
                value = sys.stdin.readline()
                if value == '':
                    raise CliError('password stdin is empty; supply a newline for an empty password')
                value = value.removesuffix('\n').removesuffix('\r')
            else:
                if not sys.stdin.isatty():
                    # getpass must never fall back to echoing input for automation.
                    raise CliError('hidden password entry requires a terminal; use key=- with stdin')
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('error', getpass.GetPassWarning)
                        value = getpass.getpass('Password: ')
                except (getpass.GetPassWarning, EOFError) as exc:
                    raise CliError('hidden password entry unavailable; use key=- with stdin') from exc
        elif not separator:
            raise CliError('set requires key=value arguments')
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise CliError('configuration values must be single-line text without control characters')
        target = KEYS[key]
        if target in changes:
            raise CliError('duplicate configuration key or alias in batch')
        changes[target] = value

    # A stable sidecar lock survives atomic replacement of the config inode.
    lock_flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    fd = os.open(path.with_name(path.name + '.lock'), lock_flags, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.is_symlink():
            raise CliError('refusing to replace a symlink configuration')
        metadata = path.stat()
        original = path.read_bytes()
        proposed = _edit_ini(original.decode('utf-8'), changes).encode('utf-8')
        # Validate a private candidate using the exact native loader, before writing.
        candidate_fd, candidate_name = tempfile.mkstemp(prefix='.validate-', dir=path.parent)
        candidate = Path(candidate_name)
        try:
            with os.fdopen(candidate_fd, 'wb') as handle:
                handle.write(proposed)
            config = _validate(candidate)
            try:
                old = _validate(path)
            except ConfigError:
                # Allow one fully validated batch to repair a native config.
                old = None
        finally:
            candidate.unlink(missing_ok=True)
        if config == old:
            return False
        active = False if prepare else service_info().get('ActiveState') == 'active'
        if active:
            guard_restart(old if old is not None else config)
        try:
            _atomic_write(path, proposed, metadata)
            if active:
                restart_service()
        except Exception as exc:
            try:
                if path.read_bytes() != original:
                    _atomic_write(path, original, metadata)
            except Exception as rollback:
                raise RuntimeError('configuration transaction and rollback failed; administrator intervention required') from rollback
            raise RuntimeError('configuration transaction failed; rolled back; service recovery may be required') from exc
        return True


def ups_connection_details(
    config, *, nut_path: Path = Path('/etc/nut/ups.conf'),
    selection_path: Path = STATE_DIR / 'ups_selection.json',
) -> tuple[str, str | None]:
    """Read local config only. Never connect to NUT or output credentials."""
    name = config.ups.name
    try:
        selected = json.loads(selection_path.read_text(encoding='utf-8')).get('selected_name')
        if isinstance(selected, str) and re.fullmatch(r'[a-zA-Z0-9_.-]+', selected):
            name = selected
    except (OSError, ValueError, AttributeError):
        pass
    target = f'{name}@{config.ups.host}:{config.ups.port}'
    if config.ups.host not in {'127.0.0.1', '::1', 'localhost'}:
        return target, None
    try:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(nut_path, encoding='utf-8')
        if not parser.has_section(name):
            return target, None
        driver = parser.get(name, 'driver', fallback='').strip()
        address = parser.get(name, 'port', fallback='').strip()
        if driver == 'snmp-ups':
            # Only a literal IP is shown, never credentials, URLs or commands.
            import ipaddress
            ip = ipaddress.ip_address(address)
            version = parser.get(name, 'snmp_version', fallback='').strip()
            version = version if version in {'v1', 'v2c', 'v3'} else ''
            return target, f'SNMP {version} -> {ip} (configured)'.replace('  ', ' ')
        if driver:
            return target, f'Driver: {driver}' if re.fullmatch(r'[a-zA-Z0-9_.-]+', driver) else None
    except (OSError, ValueError, configparser.Error):
        pass
    return target, None


def print_status(path: Path, runtime_path: Path = RUNTIME_STATUS) -> None:
    """Compact human-readable local summary, never a live hardware probe."""
    from .runtime_status import host_identity, read_status, sample_live, timestamp
    config = load_config(path)
    build = load_build_info(APP_ROOT)
    try:
        service = service_info()
    except (OSError, subprocess.SubprocessError):
        service = {}
    identity = host_identity(config.mqtt.host, config.mqtt.port)
    runtime, live = read_status(runtime_path, service)
    active = service.get('ActiveState', 'unknown')
    uptime = 'unknown'
    try:
        entered = int(service.get('ActiveEnterTimestampMonotonic', '0')) / 1_000_000
        if entered and active == 'active':
            uptime = f'{max(0, int(time.monotonic() - entered))}s'
    except ValueError:
        pass
    mqtt = runtime.get('mqtt', {}) if live else {}
    if not isinstance(mqtt, dict):
        mqtt = {}
    raw_samples = runtime.get('samples', {}) if live else {}
    samples = raw_samples if isinstance(raw_samples, dict) else {}

    def sample(name: str) -> tuple[dict, bool]:
        item = samples.get(name, {})
        if not isinstance(item, dict):
            return {}, False
        return item, sample_live(name, item)

    def temperature(value: object) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return f'{value:.1f}°C'
        return 'unavailable'

    def percent(value: object) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return f'{value:.0f}%'
        return 'unavailable'

    def metric(value: object, unit: str) -> str:
        return f'{value:g} {unit}' if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else 'unavailable'

    print(f'DigitalHouses PVE Agent {build.version} | commit {build.commit}')
    print('SYSTEM')
    print(f'  Service:   {active}/{service.get("SubState", "unknown")} | uptime {uptime}')
    print(f'  Hostname:  {identity.get("hostname") or "unknown"}')
    print(f'  IP:        {identity.get("ip") or "unknown"}')
    print('MQTT')
    print(f'  Broker:    {config.mqtt.host}:{config.mqtt.port}')
    print(f'  State:     {mqtt.get("state", "UNKNOWN")} | retry 60s, connect timeout 5s')
    print(f'  Connected: {mqtt.get("last_connected") or "unknown"}')
    print(f'  PUBACK:    {mqtt.get("last_ack") or "unknown"}')
    print(f'  Publish:   {mqtt.get("publication_state") or "unknown"}')
    print(f'  Error:     {mqtt.get("last_error") or "none known"}')
    print('HARDWARE')
    cpu, cpu_ok = sample('cpu')
    cpu_data = cpu.get('data') if cpu_ok else None
    cpu_data = cpu_data if isinstance(cpu_data, dict) else {}
    print(f'  CPU:       {temperature(cpu_data.get("temperature_c"))} | usage {percent(cpu_data.get("usage_percent"))}' + ('' if cpu_ok else ' (STALE/UNAVAILABLE)'))
    memory, memory_ok = sample('memory')
    mem_data = memory.get('data') if memory_ok else None
    mem_data = mem_data if isinstance(mem_data, dict) else {}
    if memory_ok:
        print(f'  RAM:       {metric(mem_data.get("used_gib"), "GiB")} / {metric(mem_data.get("total_gib"), "GiB")} ({percent(mem_data.get("usage_percent"))})')
    else:
        print('  RAM:       STALE/UNAVAILABLE')

    gpu, gpu_ok = sample('gpu')
    gpu_data = gpu.get('data') if gpu_ok else None
    if isinstance(gpu_data, dict):
        for gpu_id, gpu_info in sorted(gpu_data.items()):
            if not isinstance(gpu_info, dict):
                continue
            name = str(gpu_info.get('name') or gpu_info.get('model') or gpu_id)
            print(f'  GPU {name}: {temperature(gpu_info.get("temperature_c"))}')

    disk, disk_ok = sample('disk_temperature')
    smart, smart_ok = sample('smart')
    disk_data = disk.get('data') if disk_ok else {}
    disk_data = disk_data if isinstance(disk_data, dict) else {}
    smart_data = smart.get('data') if smart_ok else {}
    smart_data = smart_data if isinstance(smart_data, dict) else {}
    print('DISKS')
    if not disk_data:
        print('  STALE/UNAVAILABLE' if not disk_ok else '  No detected disks')
    else:
        for disk_id, info in sorted(disk_data.items()):
            if not isinstance(info, dict):
                continue
            name = str(info.get('model') or info.get('device_path') or disk_id)
            item_fresh = info.get('fresh') is not False and info.get('available') is True
            label = temperature(info.get('temperature_c')) if item_fresh else 'STALE/UNAVAILABLE'
            health = smart_data.get(disk_id) if smart_ok else None
            health = health if isinstance(health, dict) else {}
            health_str = str(health.get('health_state')) if health.get('fresh') is not False and health.get('health_state') else 'unknown'
            via_guest = f' | VM {info.get("source_guest_id")}' if info.get('source_type') == 'guest' else ''
            print(f'  {name}: {label} | SMART {health_str}{via_guest}')

    fans, fan_ok = sample('fans')
    fan_data = fans.get('data') if fan_ok else {}
    fan_data = fan_data if isinstance(fan_data, dict) else {}
    print('FANS')
    fan_lines = 0
    for fan_id, info in sorted(fan_data.items()):
        if not isinstance(info, dict) or 'rpm' not in info:
            continue
        m = re.search(r'fan([0-9]+)$', str(fan_id), re.I)
        name = f'FAN {m.group(1)}' if m else str(info.get('name') or info.get('label') or fan_id)
        print(f'  {name}: {metric(info.get("rpm"), "RPM")}' if fan_ok else f'  {name}: STALE/UNAVAILABLE')
        fan_lines += 1
    if not fan_lines:
        print('  STALE/UNAVAILABLE' if not fan_ok else '  No detected fans')

    print('UPS')
    ups, ups_ok = sample('ups')
    ups_data = ups.get('data') if ups_ok else None
    if config.ups.enabled or ups_ok:
        nut_target, ups_link = ups_connection_details(config)
        print(f'  NUT:       {nut_target}')
        if ups_link:
            print(f'  Link:      {ups_link}')
    if ups_ok and isinstance(ups_data, dict):
        # Cached and fresh NUT snapshot only; no network reads by status CLI.
        identity = []
        for field in ('manufacturer', 'model'):
            value = ups_data.get(field)
            if isinstance(value, str) and value.strip():
                identity.append(' '.join(value.split())[:80])
        if identity:
            print('  Device:    ' + ' '.join(identity))
        source_status = ups_data.get('status_raw')
        display_status = str(ups_data.get('primary_status') or 'unknown')
        if isinstance(source_status, str) and re.fullmatch(r'[A-Z0-9 ]{1,40}', source_status):
            display_status += ' (' + source_status + ')'
        print(f'  Status:    {display_status}')
        remaining = ups_data.get('runtime_seconds')
        minutes = f'{round(remaining / 60):g} min' if isinstance(remaining, (int, float)) and not isinstance(remaining, bool) and math.isfinite(remaining) and remaining >= 0 else 'unavailable'
        print(f'  Battery:   {percent(ups_data.get("battery_charge_percent"))} | runtime {minutes}')
        if ups_data.get('load_percent') is not None:
            print(f'  Load:      {percent(ups_data.get("load_percent"))}')
    elif live and runtime.get('ups_configured') is False:
        print('  Not configured')
    else:
        print('  STALE/UNAVAILABLE')

    print('MONITORING')
    pve, pve_ok = sample('pve_problems')
    pve_data = pve.get('data') if pve_ok else None
    if isinstance(pve_data, list):
        pve_count = sum(1 for item in pve_data if isinstance(item, dict) and item.get('active') is True)
        print(f'  PVE problems: {pve_count}')
    else:
        print('  PVE problems: unknown')
    ups_probs, ups_probs_ok = sample('ups_problems')
    ups_prob_data = ups_probs.get('data') if ups_probs_ok else None
    if isinstance(ups_prob_data, dict):
        print(f'  UPS problems: {ups_prob_data.get("problems_count", "unknown")}')
    else:
        print('  UPS problems: unknown')
    latest = timestamp(runtime.get('updated_at')) if runtime else 0
    age = time.time() - latest if latest else None
    print('  Data:      ' + (f'LIVE, {age:.0f}s old' if live and age is not None else 'STALE/UNAVAILABLE'))



def update_agent(*, state_dir: Path = STATE_DIR, app_dir: Path = APP_ROOT) -> None:
    """Install the newest published stable release via the existing updater.

    Works without MQTT. The independent updater owns safety, backup, rollback,
    and service replacement; the CLI only checks and submits the request.
    """
    from .state_store import StateStore
    from .update_manager import latest_release, stable_version

    if service_info().get('ActiveState') != 'active':
        raise CliError('agent service is not running; update requires an active agent')
    try:
        current = (app_dir / 'VERSION').read_text(encoding='utf-8').strip()
        tag, version = latest_release()
        if stable_version(version) <= stable_version(current):
            print(f'UP_TO_DATE {current}')
            return
    except (OSError, ValueError) as exc:
        raise CliError('unable to verify latest stable GitHub Release') from exc

    # An active worker must not have its request overwritten.
    active = subprocess.run(
        ['systemctl', 'is-active', '--quiet', UPDATE_SERVICE],
        capture_output=True, timeout=5,
    )
    if active.returncode == 0:
        raise CliError('update already running')
    request = StateStore(state_dir / 'update_request.json')
    worker = StateStore(state_dir / 'update_worker.json')
    if worker.load().get('state') in {'queued', 'downloading', 'installing', 'verifying', 'rolling_back'}:
        raise CliError('previous update still pending; check update service status')
    request.save({'tag': tag, 'version': version,
                  'requested_at': datetime.now(timezone.utc).isoformat()})
    worker.save({'state': 'queued', 'error': None,
                 'updated_at': datetime.now(timezone.utc).isoformat()})
    print(f'UPDATING {current} -> {version}', flush=True)
    # oneshot service blocks until verification/rollback is complete.
    try:
        result = subprocess.run(['systemctl', 'start', UPDATE_SERVICE],
                                capture_output=True, timeout=950)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('update is still running; check systemctl status ' + UPDATE_SERVICE) from exc
    outcome = worker.load()
    if result.returncode or outcome.get('state') != 'completed':
        raise RuntimeError('update failed or rolled back; inspect systemctl status ' + UPDATE_SERVICE)
    actual = (app_dir / 'VERSION').read_text(encoding='utf-8').strip()
    if actual != version:
        raise RuntimeError('updater finished but installed version differs')
    print(f'UPDATED {actual}')


def print_help() -> None:
    print('Usage: /usr/local/bin/dh-pve-agent status | update | restart | help | set key=value [key=value ...]')
    print('Run status/update/restart/set as root or through sudo. Config: ' + str(DEFAULT_CONFIG))
    print('set validates the entire batch, updates atomically, and restarts once only when running.')
    print('Keys (native INI mapping):')
    for key, (section, field) in KEYS.items():
        print(f'  {key}: [{section}] {field}')
    print('Constraints: instance_id empty or ^[a-z0-9][a-z0-9_]*$; node_name defaults to PVE;')
    print('log_level debug/info/warning/error; mqtt host required; ports 1..65535;')
    print('topic/discovery prefixes nonempty; mqtt keepalive 10..3600s; enabled true/false;')
    print('ups name/host nonempty; command timeout 1..30s; event debounce 0..3600s, finite.')
    print('Legacy ups.poll_interval_seconds is ignored: collection cadence is fixed at 10s.')
    print('Passwords: bare secret key uses hidden terminal entry; key=- reads one stdin line.')
    print('Literal secret arguments are rejected. With both secrets stdin follows argument order.')
    print('Values must be single-line; use Ansible no_log: true for secret operations.')
    print('Full reference: ' + REFERENCE)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if os.geteuid() != 0:
            raise CliError('run as root or through sudo')
        if args in ([], ['help'], ['--help'], ['-h']):
            print_help()
            return 0
        if args == ['status']:
            print_status(DEFAULT_CONFIG)
        elif args == ['update']:
            update_agent()
        elif args == ['restart']:
            if service_info().get('ActiveState') != 'active':
                raise CliError('service is not running; restart never starts an inactive service')
            guard_restart(load_config(DEFAULT_CONFIG))
            restart_service()
            print('Restarted ' + SERVICE)
        elif len(args) >= 2 and args[0] == '--prepare':
            target = Path(args[1])
            if args[2:]:
                set_config(target, args[2:], prepare=True)
            else:
                _validate(target)
        elif args[0] == 'set':
            print('CHANGED' if set_config(DEFAULT_CONFIG, args[1:]) else 'UNCHANGED')
        else:
            raise CliError('unknown command or arguments; use help')
        return 0
    except (CliError, RuntimeError) as exc:
        print('ERROR: ' + str(exc))
        return 1
    except (OSError, ValueError, subprocess.SubprocessError, configparser.Error):
        # Parser/system errors may include source lines or credentials. Never echo them.
        print('ERROR: operation failed; check command values, native configuration, permissions and systemctl status ' + SERVICE)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
