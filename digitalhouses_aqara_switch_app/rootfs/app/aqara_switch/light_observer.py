"""Passive one-group MQTT observation. No Zigbee commands or optimistic confirmation."""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading

_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def selection(config: Mapping) -> tuple[str, str] | None:
    """Optional site-owned group selector in the existing configuration_yaml."""
    item = config.get("light_monitor")
    if item is None:
        return None
    if not isinstance(item, Mapping):
        raise ValueError("light_monitor must be a mapping")
    base, group = item.get("base_topic"), item.get("group")
    if not isinstance(base, str) or not _SEGMENT.fullmatch(base):
        raise ValueError("light_monitor.base_topic must be one MQTT segment")
    if not isinstance(group, str) or not _SEGMENT.fullmatch(group):
        raise ValueError("light_monitor.group must be one MQTT segment")
    return base, group


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decode_list(blob: bytes | None) -> list | None:
    if blob is None:
        return None
    try:
        result = json.loads(blob)
    except (ValueError, UnicodeError, TypeError):
        return None
    return result if isinstance(result, list) else None


class GroupObserver:
    """Read-only MQTT group and member state, with bounded persistent JSONL."""
    def __init__(self, selected: tuple[str, str] | None,
                 logfile: Path = Path("/data/light_monitor_events.jsonl")):
        self.selected = selected
        self.logfile = logfile
        self.lock = threading.RLock()
        self.events = deque(maxlen=15)
        self.event_count = 0
        self._reset()

    def _reset(self):
        self.state = "disabled" if self.selected is None else "waiting_inventory"
        self.group_id = None
        self.members = []
        self.group_observation = None
        self.observations = {}

    def reset_connection(self):
        """Old MQTT state is not rebranded as current after reconnect."""
        with self.lock:
            self._reset()

    def _log(self, role, name, data, retained):
        record = {
            "at": utcnow(), "role": role, "name": name,
            "retained": bool(retained),
            "state": data.get("state"), "brightness": data.get("brightness"),
        }
        self.events.appendleft(record)
        self.event_count += 1
        try:
            self.logfile.parent.mkdir(parents=True, exist_ok=True)
            if self.logfile.exists() and self.logfile.stat().st_size >= 2_000_000:
                rotated = self.logfile.with_suffix(".jsonl.1")
                self.logfile.replace(rotated)
            with self.logfile.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            # Logging failure should not interrupt incoming MQTT processing.
            pass

    def inventory(self, groups_bytes: bytes | None,
                  devices_bytes: bytes | None) -> list[str]:
        """Reconstruct group from live Z2M sources. Return MQTT topics to watch."""
        with self.lock:
            if self.selected is None:
                return []
            base, group = self.selected
            group_list = decode_list(groups_bytes)
            if group_list is None:
                self.state = "waiting_inventory"
                return []
            match = next((entry for entry in group_list
                          if isinstance(entry, dict) and entry.get("friendly_name") == group), None)
            if match is None:
                self.state = "group_missing"
                self.members = []
                self.group_id = None
                self.group_observation = None
                self.observations.clear()
                return []
            members = match.get("members")
            if not isinstance(members, list):
                self.state = "invalid_group"
                return []
            devices = decode_list(devices_bytes)
            if devices is None:
                self.state = "waiting_devices"
                return [base + "/" + group]
            by_ieee = {d["ieee_address"].lower(): d for d in devices
                       if isinstance(d, dict) and isinstance(d.get("ieee_address"), str)}
            resolved = []
            seen = set()
            for m in members:
                if not isinstance(m, dict) or not isinstance(m.get("ieee_address"), str):
                    self.state = "invalid_group"
                    return []
                ieee = m["ieee_address"].lower()
                ep = m.get("endpoint")
                if (ieee, ep) in seen:
                    continue
                seen.add((ieee, ep))
                device = by_ieee.get(ieee, {})
                name = device.get("friendly_name")
                if not isinstance(name, str) or not _SEGMENT.fullmatch(name):
                    name = None
                resolved.append({"ieee": ieee, "endpoint": ep, "name": name})
            previous = {(x["ieee"], x["endpoint"]): x["name"] for x in self.members}
            current = {(x["ieee"], x["endpoint"]): x["name"] for x in resolved}
            if previous != current or self.group_id != match.get("id"):
                # A new member must not inherit state from an old name or prior group.
                names = {x["name"] for x in resolved if x["name"]}
                self.observations = {k: v for k, v in self.observations.items() if k in names}
            self.members = resolved
            self.group_id = match.get("id")
            self.state = "observing" if resolved else "empty_group"
            return [base + "/" + group] + [
                base + "/" + m["name"] for m in resolved if m["name"]
            ]

    def accept(self, topic: str, payload: bytes, retained: bool = False) -> bool:
        with self.lock:
            if self.selected is None or self.state not in {"observing", "empty_group"}:
                return False
            base, group = self.selected
            if topic == base + "/" + group:
                role, name = "group", group
            else:
                name = topic[len(base) + 1:] if topic.startswith(base + "/") else ""
                if name not in {m["name"] for m in self.members if m["name"]}:
                    return False
                role = "member"
            try:
                data = json.loads(payload)
            except (ValueError, TypeError, UnicodeError):
                return False
            if not isinstance(data, dict):
                return False
            meaningful = {k: data.get(k) for k in ("state", "brightness", "linkquality")
                          if k in data}
            if not meaningful:
                return False
            entry = {
                **meaningful, "observed_at": utcnow(),
                "retained": bool(retained), "confidence": "unverified",
            }
            if role == "group":
                self.group_observation = entry
            else:
                self.observations[name] = entry
            self._log(role, name, data, retained)
            return True

    def snapshot(self) -> dict:
        with self.lock:
            if self.selected is None:
                return {"state": "disabled", "members": [], "events": []}
            base, group = self.selected
            members = []
            for member in self.members:
                observed = self.observations.get(member["name"], {}) if member["name"] else {}
                members.append({**member,
                                "state": observed.get("state", "unknown"),
                                "brightness": observed.get("brightness"),
                                "observed_at": observed.get("observed_at"),
                                "retained": observed.get("retained"),
                                "confidence": "unverified" if observed else "unknown"})
            return {
                "state": self.state, "base_topic": base, "group": group,
                "group_id": self.group_id,
                "group_state": (self.group_observation or {}).get("state", "unknown"),
                "group_observed_at": (self.group_observation or {}).get("observed_at"),
                "group_confidence": "unverified" if self.group_observation else "unknown",
                "members": members, "member_count": len(members),
                "observed_count": sum(m["confidence"] == "unverified" for m in members),
                "confirmed_count": 0,
                "events": list(self.events), "event_count": self.event_count,
                "log_path": str(self.logfile),
            }
