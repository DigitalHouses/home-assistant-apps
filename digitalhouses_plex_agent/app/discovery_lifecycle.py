"""Acknowledged, inventory-driven Device Discovery reconciliation."""
from __future__ import annotations

import json
import logging
from copy import deepcopy

from .state_store import StateStore, StateStoreError


class DiscoveryLifecycle:
    RETRY_SECONDS = 10.0
    RECOVERY_SECONDS = 1800.0

    def __init__(self, bridge, store: StateStore, base: str) -> None:
        self.bridge = bridge
        self.store = store
        self.base = base.rstrip('/')
        self.manifest = {}
        self.valid = True
        self._fingerprint = None
        self._next_attempt = 0.0
        self._last_success = None
        self._force = False
        self._transaction = None
        self._stage = 0
        try:
            raw = store.load()
            if raw:
                if set(raw) != {'version', 'components'} or raw['version'] != 1:
                    raise ValueError('invalid manifest schema')
                components = raw['components']
                if not isinstance(components, dict):
                    raise ValueError('invalid components')
                for key, item in components.items():
                    if (not isinstance(key, str) or not key
                            or not isinstance(item, dict)
                            or set(item) != {'platform', 'topics'}
                            or not isinstance(item['platform'], str) or not item['platform']
                            or not isinstance(item['topics'], list)
                            or any(not isinstance(t, str) or not self._owned(t)
                                   for t in item['topics'])):
                        raise ValueError('invalid component')
                self.manifest = components
            elif store.path.exists():
                raise ValueError('empty manifest')
        except (StateStoreError, ValueError):
            self.valid = False
            logging.getLogger(__name__).error('Invalid Discovery manifest; reconciliation paused')

    @property
    def deadline(self) -> float:
        if self._next_attempt:
            return self._next_attempt
        if self._last_success is None:
            return 0.0
        return self._last_success + self.RECOVERY_SECONDS

    def _owned(self, topic: str) -> bool:
        # Restrict cleanup to state namespaces; availability, commands and
        # Discovery are never owned state, even if a corrupt file names them.
        if not topic.startswith(self.base + '/') or any(c in topic for c in '+#\x00'):
            return False
        suffix = topic[len(self.base) + 1:]
        return suffix == 'state' or suffix.startswith('state/') or suffix in {
            'update/state', 'agent/card',
        }

    def _manifest(self, payload):
        return {key: {'platform': item['platform'], 'topics': sorted({
            item[field] for field in ('state_topic', 'json_attributes_topic')
            if isinstance(item.get(field), str) and self._owned(item[field])
        })} for key, item in payload['components'].items()}

    def sync(self, payload, *, now: float, confirmed: bool, online: bool,
             force: bool = False) -> bool:
        self._force |= force
        if not self.valid or not confirmed or not online:
            return False
        if now < self._next_attempt:
            return False
        fingerprint = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        if self._transaction is None:
            if (not self._force and fingerprint == self._fingerprint
                    and self._last_success is not None
                    and now < self._last_success + self.RECOVERY_SECONDS):
                return True
            current = self._manifest(payload)
            removed = self.manifest.keys() - current.keys()
            shared = {t for item in current.values() for t in item['topics']}
            cleanup = sorted({t for key in removed for t in self.manifest[key]['topics']} - shared)
            intermediate = deepcopy(payload)
            intermediate['components'].update({key: {'platform': self.manifest[key]['platform']}
                                                for key in removed})
            stages = ([intermediate] if removed else []) + [deepcopy(payload)]
            self._transaction = (stages, cleanup, current, fingerprint)
            self._stage = 0
            self._force = False
        stages, cleanup, current, published_fingerprint = self._transaction
        self._next_attempt = now + self.RETRY_SECONDS
        for index in range(self._stage, len(stages)):
            self.bridge.set_discovery_payload(stages[index])
            if not self.bridge.publish_discovery():
                return False
            self._stage += 1
        # Keep cleanup progress too: a failed later delete never repeats earlier ones.
        latest_topics = {t for item in self._manifest(payload).values() for t in item['topics']}
        while cleanup:
            if cleanup[0] in latest_topics:
                cleanup.pop(0)
                continue
            if not self.bridge.clear_discovery_state(cleanup[0]):
                return False
            cleanup.pop(0)
        try:
            if current != self.manifest or not self.store.path.exists():
                self.store.save({'version': 1, 'components': current})
        except (StateStoreError, OSError):
            logging.getLogger(__name__).exception('Unable to save Discovery manifest')
            return False
        self.manifest = current
        self._fingerprint = published_fingerprint
        self._last_success = now
        self._next_attempt = 0.0
        self._transaction = None
        self._force = False
        # An inventory change during an outstanding PUBACK is reconciled next.
        return published_fingerprint == fingerprint and not self._force
