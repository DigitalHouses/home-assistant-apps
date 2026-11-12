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
from typing import Sequence

from .build_info import load_build_info
from .config import ConfigError, load_config

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path('/etc/digitalhouses_plex_agent/digitalhouses_plex_agent.conf')
RUNTIME_STATUS = Path('/var/lib/digitalhouses_plex_agent/runtime_status.json')
SERVICE = 'digitalhouses_plex_agent.service'
REFERENCE = 'https://github.com/DigitalHouses/home-assistant-apps/tree/main/digitalhouses_plex_agent'

class CliError(ValueError):
    """An administrator-facing error containing no untrusted input."""


KEYS = {
    'instance_id': ('general', 'instance_id'),
    'instance_name': ('general', 'instance_name'),
    'poll_interval': ('general', 'poll_interval_seconds'),
    'cpu_window': ('general', 'cpu_window_seconds'),
    'log_level': ('general', 'log_level'),
    'telemetry_enabled': ('telemetry', 'enabled'),
    'cpu_change_threshold': ('telemetry', 'cpu_change_threshold'),
    'high_load_threshold': ('telemetry', 'high_load_threshold'),
    'high_load_interval': ('telemetry', 'high_load_publish_interval_seconds'),
    'plex_api_enabled': ('plex_api', 'enabled'),
    'plex_api_url': ('plex_api', 'base_url'),
    'plex_api_token_file': ('plex_api', 'token_file'),
    'plex_api_timeout': ('plex_api', 'timeout_seconds'),
    'library_refresh': ('plex_api', 'library_refresh_seconds'),
    'mqtt_ip': ('mqtt', 'host'),
    'mqtt_host': ('mqtt', 'host'),
    'mqtt_port': ('mqtt', 'port'),
    'mqtt_username': ('mqtt', 'username'),
    'mqtt_password': ('mqtt', 'password'),
    'mqtt_topic_prefix': ('mqtt', 'topic_prefix'),
    'mqtt_discovery_prefix': ('mqtt', 'discovery_prefix'),
    'mqtt_keepalive': ('mqtt', 'keepalive_seconds'),
}


def service_info() -> dict[str, str]:
    result = subprocess.run(
        ['systemctl', 'show', SERVICE, '--property=ActiveState,SubState,MainPID,ActiveEnterTimestampMonotonic,ExecMainStartTimestampMonotonic'],
        text=True, capture_output=True, timeout=15, check=True,
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
            os.fchmod(handle.fileno(), stat.S_IMODE(metadata.st_mode))
            if (os.geteuid() == 0 or (metadata.st_uid, metadata.st_gid) != (os.geteuid(), os.getegid())):
                os.fchown(handle.fileno(), metadata.st_uid, metadata.st_gid)
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


def set_config(path: Path, pairs: Sequence[str]) -> bool:
    if not pairs:
        raise CliError('set requires key=value arguments')
    changes: dict[tuple[str, str], str] = {}
    for pair in pairs:
        key, separator, value = pair.partition('=')
        if key not in KEYS:
            raise CliError('unknown configuration key (see help)')
        if key == 'mqtt_password':
            if separator and value != '-':
                raise CliError('mqtt_password requires hidden entry or mqtt_password=- with stdin')
            if separator:
                value = sys.stdin.readline()
                if value == '':
                    raise CliError('password stdin is empty; supply a newline for an empty password')
                value = value.removesuffix('\n').removesuffix('\r')
            else:
                if not sys.stdin.isatty():
                    # getpass must never fall back to echoing input for automation.
                    raise CliError('hidden password entry requires a terminal; use mqtt_password=- with stdin')
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('error', getpass.GetPassWarning)
                        value = getpass.getpass('MQTT password: ')
                except getpass.GetPassWarning as exc:
                    raise CliError('hidden password entry unavailable; use mqtt_password=- with stdin') from exc
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
        active = service_info().get('ActiveState') == 'active'
        _atomic_write(path, proposed, metadata)
        if active:
            try:
                restart_service()
            except Exception as exc:
                try:
                    _atomic_write(path, original, metadata)
                except Exception as rollback:
                    raise RuntimeError('service restart failed and configuration rollback failed; administrator intervention required') from rollback
                raise RuntimeError('service restart failed; configuration rolled back; service recovery may be required') from exc
        return True


def _timestamp(value: object) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, OverflowError):
        return 0.0


def print_status(path: Path, runtime_path: Path = RUNTIME_STATUS) -> None:
    from .runtime_status import host_identity
    config = load_config(path)
    build = load_build_info(APP_ROOT)
    service = service_info()
    identity = host_identity(config.mqtt.host, config.mqtt.port)
    now = time.time()
    monotonic = time.monotonic()
    active = service.get('ActiveState', 'unknown')
    uptime = 'unknown'
    try:
        entered = int(service.get('ActiveEnterTimestampMonotonic', '0')) / 1_000_000
        if entered and active == 'active':
            uptime = f'{max(0, int(monotonic - entered))}s'
    except ValueError:
        pass
    try:
        runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
        if not isinstance(runtime, dict):
            runtime = {}
    except (OSError, ValueError):
        runtime = {}
    try:
        main_pid = int(service.get('MainPID', '0'))
        start_mono = int(service.get('ExecMainStartTimestampMonotonic', '0')) / 1_000_000
        age = now - _timestamp(runtime.get('updated_at'))
        # Matching PID alone is insufficient: PIDs can be reused after restart.
        live = (active == 'active' and main_pid > 0 and runtime.get('pid') == main_pid
                and 0 <= age <= 120 and start_mono > 0
                and _timestamp(runtime.get('updated_at')) >= now - monotonic + start_mono - 1)
    except (TypeError, ValueError):
        live = False
    mqtt = runtime.get('mqtt', {}) if live else {}
    if not isinstance(mqtt, dict):
        mqtt = {}
    print(f'DigitalHouses Plex Agent {build.version} | commit {build.commit}')
    print(f'Service: {active}/{service.get("SubState", "unknown")} | uptime {uptime}')
    print(f'Linux hostname: {identity.get("hostname") or "unknown"} | IPv4: {identity.get("ip") or "unknown"}')
    print(f'Configured MQTT broker: {config.mqtt.host}:{config.mqtt.port}')
    print('Runtime status: ' + ('live' if live else 'stale or unavailable (historical snapshot is not current state)'))
    print(f'MQTT: {mqtt.get("state", "UNKNOWN")} | reconnect: 60s delay + up to 5s connect timeout')
    print(f'Last successful connect: {mqtt.get("last_connected") or "unknown"}')
    print(f'Publication: {mqtt.get("publication_state") or "unknown"}')
    print(f'Last successful publish (QoS0 local send, not broker ACK): {mqtt.get("last_publish") or "unknown"}')
    print(f'Last broker PUBACK (QoS1): {mqtt.get("last_ack") or "unknown"}')
    print(f'Last MQTT error: {mqtt.get("last_error") or "none known"}')
    print(f'Plex API: {runtime.get("plex_api_status", "unknown") if live else "unknown (stale or unavailable)"}')


def print_help() -> None:
    print('Usage: /usr/local/bin/dh-plex-agent status | restart | help | set key=value [key=value ...]')
    print('Run status/restart/set as root or through sudo. Config: ' + str(DEFAULT_CONFIG))
    print('set validates the entire batch, updates atomically, and restarts once only when running.')
    print('Keys (native INI mapping):')
    for key, (section, field) in KEYS.items():
        print(f'  {key}: [{section}] {field}')
    print('Constraints: instance_id ^[a-z0-9][a-z0-9_]*$; log_level debug/info/warning/error;')
    print('poll_interval 2..300s; cpu_window >= poll_interval and <=3600s;')
    print('telemetry_enabled/plex_api_enabled true/false; thresholds >0, finite; high_load_interval >= poll_interval;')
    print('plex_api_url nonempty when enabled; plex_api_timeout 0.5..30s; library_refresh 60..86400s;')
    print('mqtt_ip/mqtt_host nonempty; mqtt_port 1..65535; topic/discovery prefixes nonempty; mqtt_keepalive 10..3600s.')
    print('Values must be single-line. mqtt_password: hidden entry with bare mqtt_password, or mqtt_password=- reads one stdin line.')
    print('Literal password arguments are rejected. Use Ansible no_log: true for secret operations.')
    print('Full reference: ' + REFERENCE)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args in ([], ['help'], ['--help'], ['-h']):
            print_help()
            return 0
        if os.geteuid() != 0:
            raise PermissionError('run as root or through sudo')
        if args == ['status']:
            print_status(DEFAULT_CONFIG)
        elif args == ['restart']:
            restart_service()
            print('Restarted ' + SERVICE)
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
