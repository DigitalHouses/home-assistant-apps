"""Local diagnostics, independent of MQTT and without configuration secrets."""
from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import logging
import os
from pathlib import Path
import socket
import time

from .models import BuildInfo
from .state_store import StateStore, StateStoreError

STATUS_PATH = Path('/var/lib/digitalhouses_plex_agent/runtime_status.json')
STATUS_INTERVAL = 30.0
HOST_REFRESH_INTERVAL = 60.0


def host_identity(host: str, port: int) -> dict[str, str]:
    """Ask the IPv4 routing table for the local source, without sending a packet.

    No fallback to hostname DNS (which may resolve to a parent or loopback).
    """
    result = {'hostname': socket.gethostname() or 'unknown', 'ip': 'unknown'}
    try:
        addresses = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)
        for _, _, _, _, destination in addresses:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.connect(destination)
                    local = sock.getsockname()[0]
                address = ipaddress.ip_address(local)
                if not (address.is_unspecified or address.is_loopback or address.is_multicast):
                    result['ip'] = str(address)
                    break
            except OSError:
                continue
    except OSError:
        pass
    return result


class HostIdentity:
    """Refresh on reconnect and at most once a minute for network changes."""
    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port
        self.value = {'hostname': 'unknown', 'ip': 'unknown'}
        self._next_refresh = 0.0

    def refresh(self, *, now: float, force: bool = False) -> bool:
        if not force and now < self._next_refresh:
            return False
        self._next_refresh = now + HOST_REFRESH_INTERVAL
        value = host_identity(self.host, self.port)
        changed = value != self.value
        self.value = value
        return changed


class RuntimeStatus:
    def __init__(self, path: Path, build: BuildInfo) -> None:
        self.store = StateStore(path)
        self.build = build
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._next_write = 0.0
        self._transition: object = None
        self._failed = False

    def update(self, mqtt: dict, plex_api_status: str, identity: dict, *, force: bool = False) -> None:
        now = time.monotonic()
        transition = (mqtt.get('state'), plex_api_status, identity.get('hostname'), identity.get('ip'),
                      mqtt.get('last_connected'), mqtt.get('last_error'))
        if not force and now < self._next_write and transition == self._transition:
            return
        # Only the explicitly selected diagnostics enter this file, never config.
        payload = {
            'pid': os.getpid(), 'updated_at': datetime.now(timezone.utc).isoformat(),
            'started_at': self.started_at, 'version': self.build.version,
            'commit': self.build.commit, 'hostname': identity.get('hostname', 'unknown'),
            'ip': identity.get('ip', 'unknown'), 'mqtt': dict(mqtt),
            'plex_api_status': plex_api_status,
        }
        try:
            self.store.save(payload)
            self._failed = False
            self._transition = transition
        except (StateStoreError, OSError):
            if not self._failed:
                logging.getLogger(__name__).warning('Unable to write local runtime status')
            self._failed = True
        self._next_write = now + STATUS_INTERVAL
