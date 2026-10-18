"""Bounded App-owned event history for read-only Home Assistant presentation.

Only MQTT machine Events that were acknowledged as published are recorded.
This is a diagnostic UI snapshot, not a new notification or machine Event.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .storage import atomic_json

DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_LABEL = 120

TITLES = {
    "arrival": "🏠✅ Прибытие",
    "departure": "🏠🚪 Уход",
    "gps_in": "📍✅ GPS: дома",
    "gps_out": "📍🚶 GPS: вне дома",
    "wifi_in": "📶✅ Wi-Fi: в домашней сети",
    "wifi_out": "📶📴 Wi-Fi: вне домашней сети",
    "wifi_lost": "📶⚠️ Wi-Fi: нет подтверждения",
    "zone_enter": "📍✅ Вход в зону",
    "zone_leave": "📍🚪 Выход из зоны",
}


def _aware(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def _label(value: str) -> str:
    # UI summaries are deliberately bounded; no source/identity decisions here.
    return value.replace("\r", " ").replace("\n", " ").strip()[:MAX_LABEL]


def _markdown(value: str) -> str:
    # Event names/zone names come from HA/user input. Render them as text only.
    clean = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "".join("\\" + char if char in "\\`*_{}[]()#+-.!|" else char for char in clean)


class EventHistory:
    def __init__(self, path: str, limit: int = DEFAULT_LIMIT):
        if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
            raise ValueError("Invalid event history limit")
        self.path = path
        self.limit = limit
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {"schema_version": 1, "events": []}
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or not isinstance(data.get("events"), list)):
            raise ValueError("Invalid persisted event history")
        for item in data["events"]:
            self._validate(item)
        self.events = data["events"][:limit]
        if len(self.events) != len(data["events"]):
            self.save()

    @staticmethod
    def _validate(item: object):
        if not isinstance(item, dict):
            raise ValueError("Invalid persisted history item")
        for key in ("event_type", "resident_id", "device_name"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError("Invalid history field: " + key)
        if item["event_type"] not in TITLES:
            raise ValueError("Invalid history event type")
        for key in ("observed_at", "recorded_at"):
            if not _aware(item.get(key)):
                raise ValueError("Invalid history timestamp: " + key)
        for key in ("user_name", "zone_name"):
            if item.get(key) is not None and not isinstance(item[key], str):
                raise ValueError("Invalid history field: " + key)
        if item["event_type"] in ("zone_enter", "zone_leave") and not item.get("zone_name"):
            raise ValueError("Zone history event requires zone_name")

    def record(self, event: dict, *, recorded_at: datetime | None = None):
        if not isinstance(event, dict):
            raise ValueError("Invalid machine event")
        when = recorded_at if recorded_at is not None else datetime.now(timezone.utc)
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("Event history timestamp must include timezone")
        item = {
            "event_type": event.get("event_type"),
            "resident_id": event.get("resident_id"),
            "device_name": event.get("device_name"),
            "user_name": event.get("user_name"),
            "zone_name": event.get("zone_name"),
            "observed_at": event.get("observed_at"),
            "recorded_at": when.isoformat(),
        }
        self._validate(item)
        # Explicit UI-only length bound. Machine event payload stays untouched.
        for field in ("device_name", "user_name", "zone_name"):
            if item[field] is not None:
                item[field] = _label(item[field])
        self.events.insert(0, item)
        del self.events[self.limit:]
        self.save()

    def prune_residents(self, resident_ids: set[str]) -> bool:
        remaining = [e for e in self.events if e["resident_id"] in resident_ids]
        if len(remaining) == len(self.events):
            return False
        self.events = remaining
        self.save()
        return True

    def save(self):
        atomic_json(self.path, {"schema_version": 1, "events": self.events})

    def snapshot(self) -> dict:
        items = []
        for e in self.events:
            identity = e["user_name"] or e["device_name"]
            if e["user_name"] and e["device_name"] != e["user_name"]:
                identity += " (" + e["device_name"] + ")"
            details = _markdown(identity)
            if e["zone_name"] is not None:
                details += " · " + _markdown(e["zone_name"])
            items.append({
                "title": TITLES[e["event_type"]],
                "details": details,
                "timestamp": e["recorded_at"],
            })
        return {"count": len(items), "limit": self.limit, "items": items}
