"""One MQTT client for HA Discovery, DH Sync 0.6 and machine Events."""
from __future__ import annotations

import json
import math
import threading
import socket
from pathlib import Path
from typing import Any, Callable

from .config import Config, PRODUCT_ID, REPO
from .state import ViewLimits, VIEW_LIMIT_RANGES


def _read_version() -> str:
    return (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()


def instance_id(config: Config) -> str:
    import re
    name = config.instance_id or socket.gethostname().split(".")[0]
    return re.sub(r"[^a-z0-9_-]", "_", name.lower())[:63]


def host_ip(host: str, port: int) -> str | None:
    """IP of this Linux VM, determined by routing to the actual MQTT server."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((host, port))
            address = s.getsockname()[0]
            return address if address and address != "0.0.0.0" else None
    except OSError:
        return None


def discovery(config: Config) -> dict:
    ident = instance_id(config)
    base = f"DigitalHouses/Global/{PRODUCT_ID}/{ident}"
    availability = [{"topic": base + "/availability", "payload_available": "online", "payload_not_available": "offline"}]
    components: dict[str, dict] = {}
    device_id = f"dh_pbs_agent_{ident}"
    def sensor(key: str, name: str, expression: str, *, attributes: bool = False, icon: str = "mdi:backup-restore"):
        item = {
            "platform": "sensor", "name": name,
            "unique_id": f"{device_id}_{key}",
            "default_entity_id": f"sensor.dh_pbs_agent_{key}",
            "state_topic": base + "/state",
            "value_template": "{{ " + expression + " }}",
            "availability": availability, "entity_category": "diagnostic",
            "icon": icon,
        }
        if attributes:
            item["json_attributes_topic"] = base + "/state"
            item["json_attributes_template"] = "{{ {'summary': value_json.summary, 'datastores': value_json.datastores, 'backups': value_json.backups, 'sync_jobs': value_json.sync_jobs, 'verify_jobs': value_json.verify_jobs, 'prune_jobs': value_json.prune_jobs, 'gc': value_json.gc, 'maintenance_jobs': value_json.maintenance_jobs, 'task_history': value_json.task_history, 'task_history_status': value_json.task_history_status, 'backup_groups': value_json.backup_groups, 'backup_groups_status': value_json.backup_groups_status, 'view_limits': value_json.view_limits, 'zfs': value_json.zfs, 'errors': value_json.errors, 'observed_at': value_json.observed_at} | tojson }}"
        components[key] = item

    sensor("hostname", "Hostname", "value_json.hostname", icon="mdi:server")
    sensor("ip", "IP", "value_json.ip", icon="mdi:ip-network")
    sensor("version", "Version", "value_json.agent_version", icon="mdi:information-outline")
    sensor("health", "PBS health", "value_json.status", attributes=True)
    sensor("last_collection", "Last successful collection", "value_json.last_success_at | default('unknown', true)", icon="mdi:clock-check-outline")
    sensor("backup_last_success", "Last successful backup", "value_json.backup_last_success_at | default('unknown', true)")
    sensor("backup_age_hours", "Backup age", "value_json.backup_age_hours | default('unknown', true)")
    sensor("sync_state", "Push Sync", "value_json.sync_overall", icon="mdi:cloud-upload-outline")
    sensor("sync_last_success", "Push Sync last success", "value_json.sync_last_success_at | default('unknown', true)")
    sensor("zfs_pool_health", "ZFS pool", "value_json.zfs.status", icon="mdi:database-check")
    # Native HA MQTT Number controls, in the same device as all PBS entities.
    for key, title in (("backup_groups", "Групп резервных копий"),
                       ("task_events", "Последних событий")):
        low, high = VIEW_LIMIT_RANGES[key]
        components["view_" + key + "_limit"] = {
            "platform": "number",
            "name": title,
            "unique_id": f"{device_id}_view_{key}_limit",
            "default_entity_id": f"number.dh_pbs_agent_{key}_limit",
            "state_topic": base + "/state",
            "value_template": "{{ value_json.view_limits." + key + " | default(10) }}",
            "command_topic": base + "/set/view/" + key,
            "min": low, "max": high, "step": 1, "mode": "box",
            "qos": 1, "retain": False,
            "availability": availability, "entity_category": "config",
            "icon": "mdi:format-list-numbered",
        }
    components["problem"] = {
        "platform": "binary_sensor", "name": "PBS problem",
        "unique_id": f"{device_id}_problem",
        "default_entity_id": "binary_sensor.dh_pbs_agent_problem",
        "device_class": "problem", "state_topic": base + "/state",
        "value_template": "{{ 'ON' if value_json.status in ['CRITICAL', 'DEGRADED', 'UNAVAILABLE', 'UNKNOWN'] else 'OFF' }}",
        "payload_on": "ON", "payload_off": "OFF", "availability": availability,
        "entity_category": "diagnostic",
    }
    for store in config.datastores:
        suffix = store.lower().replace("-", "_")
        # Each datastore has its own stable metric key, no overwrites.
        arr = f"(value_json.datastores | selectattr('name', 'equalto', '{store}') | list | first | default({{}}))"
        sensor(f"datastore_{suffix}_used_percent", store + " used %", arr + ".used_percent | default('unknown', true)")
        sensor(f"datastore_{suffix}_available_gib", store + " available GiB",
               f"(({arr}.available_bytes / 1073741824) | round(2)) if {arr}.available_bytes is defined else 'unknown'")
    catalog = {
        "backup": ["backup_failed", "backup_overdue", "backup_recovered", "service_unavailable", "service_recovered"],
        "sync": ["sync_failed", "sync_overdue", "sync_recovered"],
        "storage": ["disk_space_low", "disk_space_recovered", "zfs_pool_degraded", "zfs_pool_recovered"],
        "maintenance": ["verify_failed"],
    }
    for cat, event_types in catalog.items():
        components[f"{cat}_event"] = {
            "platform": "event", "name": cat.title() + " event",
            "unique_id": f"{device_id}_{cat}_event",
            "default_entity_id": f"event.dh_pbs_agent_{cat}_event",
            "state_topic": base + "/event/" + cat,
            "event_types": event_types, "qos": 1, "availability": availability,
            "entity_category": "diagnostic",
        }
    return {
        "device": {"identifiers": [device_id], "name": "DigitalHouses PBS Agent " + ident,
                   "manufacturer": "DigitalHouses", "model": "PBS Agent",
                   "sw_version": _read_version()},
        "origin": {"name": "DigitalHouses PBS Agent", "sw_version": _read_version(), "support_url": REPO},
        "components": components,
    }


class Publisher:
    def __init__(self, config: Config, *, view_limits: ViewLimits | None = None):
        import paho.mqtt.client as mqtt
        self.config = config
        self.view_limits = view_limits if view_limits is not None else ViewLimits()
        self._state_lock = threading.Lock()
        self.id = instance_id(config)
        self.base = f"DigitalHouses/Global/{PRODUCT_ID}/{self.id}"
        self.discovery_topic = f"homeassistant/device/dh_pbs_agent_{self.id}/config"
        self.synctopic = self.base + "/sync"
        self.connected = False
        self.last_connect_error: str | None = None
        self.last_state: dict | None = None
        self.last_ack_at: str | None = None
        self.on_connection_change: Callable[[str, str | None], None] | None = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="dh_pbs_agent_" + self.id)
        self.client.reconnect_delay_set(60, 60)
        if config.mqtt_username:
            self.client.username_pw_set(config.mqtt_username, config.mqtt_password)
        self.client.will_set(self.base + "/availability", payload="offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _send(self, topic: str, payload: dict | str, *, retain: bool) -> bool:
        if not self.connected:
            return False
        if not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        info = self.client.publish(topic, payload=payload, qos=1, retain=retain)
        if info.rc != 0:
            return False
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            return False
        from datetime import datetime, timezone
        self.last_ack_at = datetime.now(timezone.utc).isoformat()
        return True

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if getattr(reason_code, "is_failure", False):
            self.connected = False
            self.last_connect_error = str(reason_code)
            if self.on_connection_change is not None:
                self.on_connection_change("DISCONNECTED", self.last_connect_error)
            return
        self.connected = True
        self.last_connect_error = None
        if self.on_connection_change is not None:
            self.on_connection_change("CONNECTED", None)
        # Network callbacks MUST NOT wait for PUBACK on their own I/O thread.
        # paho queues these QoS1 publications; the client loop sends them.
        def enqueue(topic: str, payload: dict | str) -> None:
            if not isinstance(payload, str):
                payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            client.publish(topic, payload=payload, qos=1, retain=True)
        enqueue(self.base + "/availability", "online")
        enqueue(self.synctopic, {
            "schema": 1, "product_id": PRODUCT_ID, "type": "agent",
            "version": _read_version(), "repository": REPO,
            "product_path": PRODUCT_ID,
        })
        enqueue(self.discovery_topic, discovery(self.config))
        client.subscribe(self.base + "/set/view/+", qos=1)
        with self._state_lock:
            if self.last_state is not None:
                enqueue(self.base + "/state", self.last_state)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        # Do not replay stale retained commands when the broker reconnects.
        if getattr(message, "retain", False):
            return
        prefix = self.base + "/set/view/"
        if not message.topic.startswith(prefix):
            return
        key = message.topic[len(prefix):]
        if key not in VIEW_LIMIT_RANGES:
            return
        try:
            raw = message.payload.decode("utf-8").strip()
            number = float(raw)
            if not math.isfinite(number) or not number.is_integer():
                return
            limits = self.view_limits.update(key, int(number))
        except (ValueError, UnicodeDecodeError, OSError):
            return
        # MQTT callback cannot block waiting for its own PUBACK.
        with self._state_lock:
            if self.last_state is not None:
                new_state = {**self.last_state, "view_limits": limits}
                self.last_state = new_state
                client.publish(self.base + "/state",
                               json.dumps(new_state, ensure_ascii=False, separators=(",", ":")),
                               qos=1, retain=True)

    def _on_disconnect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        self.connected = False
        if str(reason_code) not in ("Normal disconnection", "Success"):
            self.last_connect_error = str(reason_code)
        if self.on_connection_change is not None:
            self.on_connection_change("DISCONNECTED", self.last_connect_error)

    def start(self) -> None:
        self.client.connect_async(self.config.mqtt_host, self.config.mqtt_port,
                                  keepalive=self.config.mqtt_keepalive_seconds)
        self.client.loop_start()

    def state(self, payload: dict) -> bool:
        # Queue while locked so an incoming Number command cannot be overwritten
        # by a concurrent polling publish with older view settings.
        with self._state_lock:
            updated = {**payload, "view_limits": self.view_limits.snapshot()}
            self.last_state = updated
            if not self.connected:
                return False
            data = json.dumps(updated, ensure_ascii=False, separators=(",", ":"))
            info = self.client.publish(self.base + "/state", data, qos=1, retain=True)
        if info.rc != 0:
            return False
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            return False
        from datetime import datetime, timezone
        self.last_ack_at = datetime.now(timezone.utc).isoformat()
        return True

    def event(self, category: str, payload: dict) -> bool:
        if category not in {"backup", "sync", "storage", "maintenance"}:
            raise ValueError("invalid event category")
        return self._send(self.base + "/event/" + category, payload, retain=False)

    def stop(self) -> None:
        if self.connected:
            self._send(self.base + "/availability", "offline", retain=True)
            self.client.disconnect()
        self.client.loop_stop()
