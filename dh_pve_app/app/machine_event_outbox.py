from __future__ import annotations

from dataclasses import dataclass

from .state_store import StateStore, StateStoreError


_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PendingMachineEvent:
    key: str
    payload: dict[str, object]


class MachineEventOutbox:
    """Small persisted outbox for machine events awaiting MQTT acknowledgement."""

    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store
        self._pending = self._load()

    def _load(self) -> list[PendingMachineEvent]:
        state = self.state_store.load()
        if not state:
            return []

        if state.get("schema_version") != _SCHEMA_VERSION:
            raise StateStoreError("unsupported machine event outbox schema")

        raw_pending = state.get("pending")
        if not isinstance(raw_pending, list):
            raise StateStoreError("invalid machine event outbox state")

        pending: list[PendingMachineEvent] = []
        seen: set[str] = set()
        for raw_item in raw_pending:
            if not isinstance(raw_item, dict):
                raise StateStoreError("invalid machine event outbox state")
            key = raw_item.get("key")
            payload = raw_item.get("payload")
            if not isinstance(key, str) or not key or not isinstance(payload, dict):
                raise StateStoreError("invalid machine event outbox state")
            if key in seen:
                raise StateStoreError("duplicate machine event outbox key")
            seen.add(key)
            pending.append(PendingMachineEvent(key=key, payload=dict(payload)))
        return pending

    def _persist(self) -> None:
        self.state_store.save(
            {
                "schema_version": _SCHEMA_VERSION,
                "pending": [
                    {"key": item.key, "payload": dict(item.payload)}
                    for item in self._pending
                ],
            }
        )

    def enqueue(self, key: str, payload: dict[str, object]) -> bool:
        if not isinstance(key, str) or not key:
            raise ValueError("machine event key must be a non-empty string")
        if not isinstance(payload, dict):
            raise TypeError("machine event payload must be a dict")
        if any(item.key == key for item in self._pending):
            return False

        self._pending.append(PendingMachineEvent(key=key, payload=dict(payload)))
        try:
            self._persist()
        except Exception:
            self._pending.pop()
            raise
        return True

    def pending(self) -> tuple[PendingMachineEvent, ...]:
        return tuple(
            PendingMachineEvent(key=item.key, payload=dict(item.payload))
            for item in self._pending
        )

    def acknowledge(self, key: str) -> None:
        index = next(
            (index for index, item in enumerate(self._pending) if item.key == key),
            None,
        )
        if index is None:
            return

        removed = self._pending.pop(index)
        try:
            self._persist()
        except Exception:
            self._pending.insert(index, removed)
            raise
