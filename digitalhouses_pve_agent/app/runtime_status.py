"""Small volatile diagnostics; no monitored API calls or configuration secrets."""
from datetime import datetime, timezone
import ipaddress
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from types import SimpleNamespace

STATUS_PATH = Path('/run/digitalhouses_pve_agent/runtime_status.json')
STATUS_INTERVAL = 30.0
SAMPLE_MAX_AGE = {'cpu': 45, 'memory': 45, 'fans': 45, 'gpu': 150,
                  'disk_temperature': 150, 'smart': 7500, 'ups': 45,
                  'pve_problems': 120, 'ups_problems': 45}
MAX_STATUS_BYTES = 512 * 1024


def load_build_info(root: Path):
    version = (root / 'VERSION').read_text().strip()
    values = {}
    try:
        for line in (root / 'BUILD_INFO').read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep:
                values[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return SimpleNamespace(version=values.get('version', version), commit=values.get('commit', 'unknown'))


def host_identity(host: str, port: int) -> dict[str, str]:
    """Read the source route to the broker, with a bounded DNS/route lookup."""
    result = {'hostname': socket.gethostname() or 'unknown', 'ip': 'unknown'}
    try:
        process = subprocess.run(['ip', '-j', '-4', 'route', 'get', host], capture_output=True,
                                 text=True, timeout=1.5, check=True)
        routes = json.loads(process.stdout)
        sources = {str(ipaddress.IPv4Address(row.get('prefsrc') or row.get('src')))
                   for row in routes if row.get('prefsrc') or row.get('src')}
        if len(sources) == 1:
            address = ipaddress.IPv4Address(sources.pop())
            if not (address.is_loopback or address.is_unspecified or address.is_multicast):
                result['ip'] = str(address)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        pass
    return result


class HostIdentity:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.value = {'hostname': 'unknown', 'ip': 'unknown'}
        self._next_refresh = 0.0

    def refresh(self, *, now: float, force: bool = False) -> bool:
        if not force and now < self._next_refresh:
            return False
        self._next_refresh = now + 60
        value = host_identity(self.host, self.port)
        changed = self.value != value
        self.value = value
        return changed


def timestamp(value) -> float:
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return 0.0


def sample_live(name: str, sample: dict) -> bool:
    age = time.time() - timestamp(sample.get('last_success'))
    return sample.get('available') is True and 0 <= age <= SAMPLE_MAX_AGE.get(name, 120)


def read_status(path: Path, service: dict) -> tuple[dict, bool]:
    try:
        with path.open('rb') as handle:
            raw = handle.read(MAX_STATUS_BYTES + 1)
        if len(raw) > MAX_STATUS_BYTES:
            return {}, False
        runtime = json.loads(raw)
        if not isinstance(runtime, dict):
            return {}, False
        now, mono = time.time(), time.monotonic()
        updated = timestamp(runtime.get('updated_at'))
        started = int(service.get('ExecMainStartTimestampMonotonic', '0')) / 1_000_000
        live = (service.get('ActiveState') == 'active' and int(service.get('MainPID', '0')) > 0
                and runtime.get('pid') == int(service['MainPID']) and started > 0
                and 0 <= now - updated <= 120
                and timestamp(runtime.get('started_at')) >= now - mono + started - 1
                and updated >= timestamp(runtime.get('started_at')))
        return runtime, live
    except (OSError, ValueError, TypeError, KeyError):
        return {}, False


# Whitelist physical diagnostics. In particular never serialize UPS raw NUT
# output, credentials, guest inventory, config or arbitrary exception messages.
FIELDS = {
    'cpu': ('usage_percent', 'temperature_c', 'frequency_mhz', 'load_1m', 'load_5m', 'load_15m'),
    'memory': ('total_gib', 'used_gib', 'available_gib', 'usage_percent', 'swap_used_gib'),
    'disk_temperature': ('disk_id', 'device_path', 'model', 'temperature_c', 'source', 'source_type', 'source_guest_id', 'source_device_path', 'passthrough_hostpci', 'passthrough_pci_address', 'health_state', 'available'),
    'smart': ('disk_id', 'device_path', 'model', 'temperature_c', 'health_state', 'health_reasons', 'recommendation', 'source_type', 'source_guest_id', 'smart_passed', 'available', 'last_success_at'),
    'fans': ('fan_id', 'label', 'name', 'rpm', 'available'),
    'gpu': ('gpu_id', 'name', 'model', 'temperature_c', 'available', 'source_type', 'source_id', 'connection', 'pci_address', 'kernel_driver'),
    'ups': ('manufacturer', 'model', 'driver_name', 'primary_status', 'status_raw', 'line_power', 'on_battery', 'low_battery', 'discharging', 'battery_charge_percent', 'runtime_seconds', 'load_percent'),
}


def _fields(data: dict, name: str) -> dict:
    return {key: data[key] for key in FIELDS[name] if key in data}


def local_samples(runtime, ups_runtime) -> dict:
    result = {}
    for name in FIELDS:
        if name == 'ups':
            continue
        state = runtime._subsystems.get(name)
        if state is None:
            continue
        data = runtime._jsonable(state.data)
        selected = {}
        if isinstance(data, dict):
            if name in ('cpu', 'memory'):
                selected = _fields(data, name)
            else:
                for key, value in data.items():
                    if not isinstance(value, dict):
                        continue
                    item = _fields(value, name)
                    item['sample_at'] = value.get('last_success_at') or state.last_success
                    item['fresh'] = sample_live(name, {'available': state.available and value.get('available', True) is not False,
                                                       'last_success': item['sample_at']})
                    selected[key] = item
        result[name] = {'available': state.available, 'last_success': state.last_success, 'data': selected}
    if 'cpu' in result:
        try:
            result['cpu']['data'].update(dict(zip(('load_1m', 'load_5m', 'load_15m'), os.getloadavg())))
        except OSError:
            pass
    engine = getattr(runtime, 'problem_engine', None)
    if engine is not None:
        result['pve_problems'] = {'available': True, 'last_success': getattr(runtime, 'last_problem_sample_at', None),
                                  'data': [{'id': s.problem_id, 'active': s.active} for s in engine.states()]}
    if ups_runtime is not None:
        snap = ups_runtime.last_snapshot
        result['ups'] = {'available': ups_runtime.nut_available,
                         'last_success': getattr(ups_runtime, 'last_sample_at', None),
                         'data': {key: getattr(snap, key) for key in FIELDS['ups']} if snap is not None else None}
        # Problems are computed by the existing runtime, never invented by CLI.
        problems = getattr(ups_runtime, 'local_problem_fields', None)
        if problems is not None:
            from .ups_health import ups_problem_observations
            problems = dict(problems, active=[p.problem_id for p in ups_problem_observations(
                snap, nut_available=ups_runtime.nut_available) if p.active])
            result['ups_problems'] = {'available': ups_runtime.nut_available,
                                     'last_success': getattr(ups_runtime, 'last_sample_at', None), 'data': problems}
    return result


class RuntimeStatus:
    def __init__(self, path: Path, build):
        self.path, self.build = path, build
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._next_write = 0.0
        self._failed = False

    def update(self, mqtt: dict, identity: dict, runtime, ups_runtime, *,
               agent_process_cpu: dict[str, object] | None = None, force: bool = False):
        now = time.monotonic()
        if not force and now < self._next_write:
            return
        self._next_write = now + STATUS_INTERVAL
        temporary = None
        try:
            payload = {'pid': os.getpid(), 'started_at': self.started_at,
                       'updated_at': datetime.now(timezone.utc).isoformat(),
                       'version': self.build.version, 'commit': self.build.commit,
                       'hostname': identity.get('hostname'), 'ip': identity.get('ip'),
                       'mqtt': mqtt, 'ups_configured': ups_runtime is not None,
                       'samples': local_samples(runtime, ups_runtime),
                       'agent_process_cpu': agent_process_cpu or {}}
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            if len(raw) > MAX_STATUS_BYTES:
                raise ValueError('status too large')
            self.path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            fd, filename = tempfile.mkstemp(prefix='.status-', dir=self.path.parent)
            temporary = Path(filename)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
            # /run is volatile. Atomic replace suffices; no persistent fsync.
            os.replace(temporary, self.path)
            self._failed = False
        except Exception:
            if not self._failed:
                logging.getLogger(__name__).warning('Unable to write local runtime status')
            self._failed = True
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
