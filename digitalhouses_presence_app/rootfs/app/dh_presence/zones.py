"""Zone transitions use Home Assistant's own device_tracker state classification.

No custom geofencing; zone entity IDs are the identity and friendly names are display-only.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from .storage import atomic_json


def zone_key(entity_id: str) -> str:
    if not isinstance(entity_id, str) or not entity_id.startswith("zone."):
        raise ValueError("Invalid zone entity")
    return hashlib.sha256(entity_id.encode("utf-8")).hexdigest()[:16]


def zone_catalog(states: list[dict]) -> dict[str, str]:
    """Return zone entity id -> name; reject ambiguous names at classification time."""
    if not isinstance(states, list):
        raise ValueError("Invalid HA states response")
    zones = {}
    for entry in states:
        if not isinstance(entry, dict):
            continue
        entity = entry.get("entity_id")
        if not isinstance(entity, str) or not entity.startswith("zone."):
            continue
        name = entry.get("attributes", {}).get("friendly_name")
        if not isinstance(name, str) or not name.strip():
            name = entity.removeprefix("zone.")
        zones[entity] = name.strip()
    return zones


def classify(raw: str, zones: dict[str, str]) -> str | None:
    """Resolve HA zone name, without guessing when two names coincide.

    None means an untrustworthy observation, not a departure.
    Empty string means HA explicitly reports not_home.
    """
    if raw == "not_home":
        return ""
    if raw in ("unknown", "unavailable", "") or not isinstance(raw, str):
        return None
    if raw == "home":
        return "zone.home" if "zone.home" in zones else None
    matches = [entity for entity, name in zones.items() if name.casefold() == raw.casefold()]
    return matches[0] if len(matches) == 1 else None


class ZoneMonitor:
    def __init__(self, path: str):
        self.path = path
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {"schema_version": 1, "residents": {}}
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or not isinstance(data.get("residents"), dict)):
            raise ValueError("Invalid persisted zone monitoring state")
        self.residents = data["residents"]

    def observe(self, resident_id: str, raw: str, observed: datetime,
                zones: dict[str, str]) -> list[dict]:
        current = classify(raw, zones)
        if current is None:
            return []
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("Zone timestamp must be timezone-aware")
        previous = self.residents.get(resident_id)
        timestamp = observed.isoformat()
        # On startup, a missing baseline must never generate a synthetic arrival.
        if previous is None:
            self.residents[resident_id] = {"zone": current, "observed_at": timestamp}
            self.save()
            return []
        old_time = datetime.fromisoformat(previous["observed_at"])
        if observed <= old_time:
            return []
        before = previous["zone"]
        if before == current:
            self.residents[resident_id] = {"zone": current, "observed_at": timestamp}
            self.save()
            return []
        # A removed zone or a changed label cannot produce an asserted departure.
        # Rebaseline rather than attaching a transition to a non-existing zone.
        if before and before not in zones:
            self.residents[resident_id] = {"zone": current, "observed_at": timestamp}
            self.save()
            return []
        self.residents[resident_id] = {"zone": current, "observed_at": timestamp}
        self.save()
        events = []
        for kind, zone in (("zone_leave", before), ("zone_enter", current)):
            if zone and zone in zones:
                events.append({"event_type": kind, "resident_id": resident_id,
                               "source": "gps", "observed_at": timestamp,
                               "zone_entity_id": zone, "zone_name": zones[zone],
                               "zone_key": zone_key(zone)})
        return events

    def prune_residents(self, resident_ids: set[str]) -> None:
        missing = set(self.residents) - resident_ids
        if missing:
            for key in missing:
                del self.residents[key]
            self.save()

    def save(self) -> None:
        atomic_json(self.path, {"schema_version": 1, "residents": self.residents})
