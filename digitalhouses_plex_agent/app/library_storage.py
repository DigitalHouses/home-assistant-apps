"""Cheap capacity of the system filesystem and Plex library mounts."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
import stat

from .plex_api import LibraryInfo


def storage_id(mountpoint: str) -> str:
    return hashlib.sha256(mountpoint.encode()).hexdigest()[:12]


def _library_path_is_directory(path: str) -> bool:
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except PermissionError:
        # A restricted library child does not mean its dataset is unavailable.
        return True


class LibraryStorageRuntime:
    def __init__(self) -> None:
        self.payload: dict[str, dict[str, object]] = {}
        self.mounts: tuple[str, ...] = ()
        self.observed = False
        self._paths: dict[str, str] = {}
        self._libraries: tuple[tuple[str, str], ...] = ()
        self._next_collect = 0.0
        self._sent: dict | None = None
        self._force_publish = False

    def collect(self, libraries: tuple[LibraryInfo, ...], *, now: float,
                force: bool = False, online: bool = True) -> bool:
        if not online:
            return False
        signature = tuple(sorted((lib.path or '', lib.title) for lib in libraries))
        if not force and signature == self._libraries and now < self._next_collect:
            return False
        self._libraries = signature
        self._next_collect = now + 60.0
        # Root is a real VM filesystem, not a fallback for unavailable media.
        groups: dict[str, dict] = {'/': {'names': set(), 'valid': True}}
        paths = {}
        for path, name in signature:
            if not path:
                continue
            previous = self._paths.get(path)
            mount = previous or path
            valid = False
            try:
                real = os.path.realpath(path)
                # The agent need not traverse the media directories. EACCES
                # on a child path does not prevent measuring its dataset.
                if not _library_path_is_directory(real):
                    raise OSError('library path is not a directory')
                candidate = real
                while not os.path.ismount(candidate):
                    parent = os.path.dirname(candidate)
                    if parent == candidate:
                        raise OSError('mount not found')
                    candidate = parent
                # Never substitute the host root filesystem for a missing media mount.
                if candidate == '/' or (previous and candidate != previous):
                    raise OSError('library mount unavailable or replaced')
                mount = candidate
                valid = True
            except (OSError, ValueError):
                pass
            if valid or previous:
                paths[path] = mount
            group = groups.setdefault(mount, {'names': set(), 'valid': True})
            group['names'].add(name)
            group['valid'] = group['valid'] and valid
        payload = {}
        for mount, group in sorted(groups.items()):
            entry = dict(percent=None, available_gib=None, used_gib=None,
                         total_gib=None, mountpoint=mount,
                         library_names=sorted(group['names']),
                         plex_integration='digitalhouses_plex_agent',
                         plex_section='library_storage',
                         storage_display_name=('System' if mount == '/' else os.path.basename(mount).replace('_', ' ').title()),
                         source='plex_library_storage_statvfs')
            if group['valid']:
                try:
                    stat = os.statvfs(mount)
                    used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
                    available = stat.f_bavail * stat.f_frsize
                    total = used + available
                    if total <= 0 or min(used, available) < 0:
                        raise ValueError('invalid capacity')
                    entry.update(percent=used / total * 100,
                                 used_gib=used / 1024**3,
                                 available_gib=available / 1024**3,
                                 total_gib=total / 1024**3)
                except (OSError, ValueError):
                    pass
            payload[storage_id(mount)] = entry
        changed_mounts = tuple(sorted(groups)) != self.mounts
        self.mounts = tuple(sorted(groups))
        self.observed = True
        self._paths = paths
        self.payload = payload
        return changed_mounts

    def publish(self, publish_state_group, *, force: bool = False) -> bool:
        self._force_publish = self._force_publish or force
        if self.payload == self._sent and not self._force_publish:
            return True
        if not publish_state_group('library_storage', self.payload):
            return False
        self._sent = deepcopy(self.payload)
        self._force_publish = False
        return True
