from __future__ import annotations

import json
import os
import shlex
import urllib.request
from pathlib import Path
from typing import Any, Callable


from config import StorageConfig
from db.base import DatabaseAdapter

SUPERVISOR_HOST_INFO_URL = 'http://supervisor/host/info'
KNOWN_HOSTS_FILE = Path('/data/ssh_known_hosts')


def parse_df_output(output: str) -> dict[str, float]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError('Unexpected df output')
    fields = lines[-1].split()
    if len(fields) < 6:
        raise ValueError('Unexpected df output fields')
    available_bytes = float(fields[-3])
    capacity = fields[-2]
    if not capacity.endswith('%'):
        raise ValueError('Unexpected df capacity value')
    used_percentage = float(capacity[:-1])
    return {
        'db_disk_free': round(available_bytes / 1_000_000_000, 1),
        'db_disk_used_percentage': round(used_percentage, 1),
    }


def parse_supervisor_host_payload(payload: dict[str, Any]) -> dict[str, float]:
    if payload.get('result') != 'ok' or not isinstance(payload.get('data'), dict):
        raise ValueError('Supervisor host info response is not valid')
    data = payload['data']
    free = float(data['disk_free'])
    used = float(data['disk_used'])
    total = float(data['disk_total'])
    if total <= 0:
        raise ValueError('Supervisor disk_total must be greater than zero')
    return {
        'db_disk_free': round(free, 1),
        'db_disk_used_percentage': round(used / total * 100.0, 1),
    }


def fetch_supervisor_host_payload() -> dict[str, Any]:
    token = os.getenv('SUPERVISOR_TOKEN', '')
    if not token:
        raise RuntimeError('SUPERVISOR_TOKEN is not available')
    request = urllib.request.Request(
        SUPERVISOR_HOST_INFO_URL,
        headers={'Authorization': f'Bearer {token}'},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))


def _run_ssh_command(config: StorageConfig, command: str) -> str:
    import paramiko

    client = paramiko.SSHClient()
    if KNOWN_HOSTS_FILE.exists():
        client.load_host_keys(str(KNOWN_HOSTS_FILE))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
            look_for_keys=False,
            allow_agent=False,
        )
        client.save_host_keys(str(KNOWN_HOSTS_FILE))
        _stdin, stdout, stderr = client.exec_command(command, timeout=10)
        exit_status = stdout.channel.recv_exit_status()
        output = stdout.read().decode('utf-8', errors='replace')
        error = stderr.read().decode('utf-8', errors='replace').strip()
        if exit_status != 0:
            raise RuntimeError(error or f'SSH command exited with status {exit_status}')
        return output
    finally:
        client.close()


def fetch_ssh_df_output(config: StorageConfig, path: str) -> str:
    return _run_ssh_command(config, f'df -P -B1 {shlex.quote(path)}')


def detect_ssh_database_path(config: StorageConfig, engine: str) -> str:
    if engine == 'postgresql':
        command = r'''\
if command -v pg_lsclusters >/dev/null 2>&1; then
  p="$(pg_lsclusters --no-header 2>/dev/null | awk 'NR==1 {print $6}')"
  if [ -n "$p" ] && [ -d "$p" ]; then printf '%s\n' "$p"; exit 0; fi
fi
for p in /var/lib/postgresql/*/main /var/lib/pgsql/data /var/lib/postgres/data /var/lib/postgresql /var/lib/pgsql /var/lib/postgres; do
  if [ -d "$p" ]; then printf '%s\n' "$p"; exit 0; fi
done
printf '/\n'
'''
    elif engine == 'mariadb':
        command = r'''\
p="$(ps -eo args 2>/dev/null | sed -n 's/.*--datadir=\([^ ]*\).*/\1/p' | head -n 1)"
if [ -n "$p" ] && [ -d "$p" ]; then printf '%s\n' "$p"; exit 0; fi
for p in /var/lib/mysql /var/lib/mariadb; do
  if [ -d "$p" ]; then printf '%s\n' "$p"; exit 0; fi
done
printf '/\n'
'''
    else:
        return '/'

    output = _run_ssh_command(config, command)
    for line in output.splitlines():
        path = line.strip()
        if path:
            return path
    return '/'


class StorageCollector:
    def __init__(
        self,
        config: StorageConfig,
        adapter: DatabaseAdapter,
        supervisor_fetcher: Callable[[], dict[str, Any]] = fetch_supervisor_host_payload,
        ssh_fetcher: Callable[[StorageConfig, str], str] = fetch_ssh_df_output,
        ssh_path_detector: Callable[[StorageConfig, str], str] = detect_ssh_database_path,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.supervisor_fetcher = supervisor_fetcher
        self.ssh_fetcher = ssh_fetcher
        self.ssh_path_detector = ssh_path_detector
        self._detected_path = ''

    @property
    def enabled(self) -> bool:
        return self.config.source != 'disabled'

    @property
    def resolved_path(self) -> str:
        return self.config.path or self._detected_path

    def collect(self) -> dict[str, float]:
        if self.config.source == 'supervisor':
            return parse_supervisor_host_payload(self.supervisor_fetcher())
        if self.config.source == 'ssh':
            path = self.config.path or self._detected_path
            if not path:
                try:
                    path = str(self.adapter.data_directory() or '').strip()
                except Exception:
                    path = ''
                if not path:
                    engine = str(getattr(getattr(self.adapter, 'config', None), 'engine', ''))
                    try:
                        path = str(self.ssh_path_detector(self.config, engine) or '').strip()
                    except Exception:
                        path = ''
                self._detected_path = path or '/'
                path = self._detected_path
            return parse_df_output(self.ssh_fetcher(self.config, path))
        raise RuntimeError('Storage monitoring is disabled')
