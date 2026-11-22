"""One MQTT client for HA Discovery, DH Sync 0.6 and machine Events."""
from __future__ import annotations

import json
import hashlib
import re
import math
import queue
import threading
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Config, PRODUCT_ID, REPO
from .state import StateStore, ViewLimits, VIEW_LIMIT_RANGES
from .view import render_trees, validate_timezone

HA_TIMEZONE_TOPIC = "DigitalHouses/Global/digitalhouses_pbs_agent/ha_timezone"


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


def job_component_key(kind: str, name: str) -> str:
    """Stable, collision-resistant discovery key from actual PBS job identity."""
    readable = re.sub(r"[^a-z0-9]+", "_", (kind + "_" + name).lower()).strip("_")[:45]
    digest = hashlib.sha256(json.dumps([kind, name]).encode("utf-8")).hexdigest()[:10]
    return f"job_{readable}_{digest}_status"


def job_identity(sample: dict | None) -> tuple[tuple[str, str], ...]:
    rows = (sample or {}).get("maintenance_jobs", [])
    return tuple(sorted({
        (str(item["type"]), str(item["id"]))
        for item in rows if isinstance(item, dict) and item.get("type") and item.get("id")
    }))


# Localized display names do not change PBS job types or MQTT entity identities.
JOB_TITLES = {
    "Push Sync": "Отправка копий",
    "S3 Sync": "Синхронизация S3",
    "Pull Sync": "Получение копий",
    "Verify": "Проверка копий",
    "Prune": "Очистка копий",
    "GC": "Сборка мусора",
}


def job_components(config: Config, sample: dict | None) -> dict:
    """Discover only actual PBS jobs; names are never installation constants."""
    ident = instance_id(config)
    base = f"DigitalHouses/Global/{PRODUCT_ID}/{ident}"
    device_id = f"dh_pbs_agent_{ident}"
    availability = [{"topic": base + "/availability",
                     "payload_available": "online", "payload_not_available": "offline"}]
    rows: dict = {}
    for kind, name in job_identity(sample):
        qkind, qname = json.dumps(kind, ensure_ascii=False), json.dumps(name, ensure_ascii=False)
        arr = f"(value_json.maintenance_jobs | selectattr('type', 'equalto', {qkind}) | selectattr('id', 'equalto', {qname}) | list | first | default({{}}))"
        key = job_component_key(kind, name)
        metadata = {
            "pbs_product": PRODUCT_ID,
            "pbs_section": "job",
            "pbs_metric": "status",
            "pbs_job_type": kind,
            "pbs_job_id": name,
            "pbs_display_name": name,
            "pbs_instance": ident,
        }
        # Object-literal metadata prevents job names from becoming identity rules in UI.
        props = ", ".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in metadata.items())
        rows[key] = {
            "platform": "sensor",
            "name": f"{JOB_TITLES.get(kind, kind)} · {name}",
            "unique_id": f"{device_id}_{key}",
            "default_entity_id": f"sensor.dh_pbs_agent_{ident}_{key}",
            "state_topic": base + "/state",
            "value_template": "{{ " + arr + ".status | default('UNKNOWN', true) }}",
            "json_attributes_topic": base + "/state",
            "json_attributes_template": (
                "{{ {" + props + ", 'schedule': " + arr +
                ".schedule | default(none), 'last_run_at': " + arr +
                ".last_run_at | default(none)} | tojson }}"
            ),
            "availability": availability,
            "entity_category": "diagnostic",
            "icon": "mdi:calendar-check-outline",
        }
    return rows


def discovery(config: Config, sample: dict | None = None) -> dict:
    ident = instance_id(config)
    base = f"DigitalHouses/Global/{PRODUCT_ID}/{ident}"
    availability = [{"topic": base + "/availability", "payload_available": "online", "payload_not_available": "offline"}]
    components: dict[str, dict] = {}
    device_id = f"dh_pbs_agent_{ident}"
    def sensor(key: str, name: str, expression: str, *, attributes: bool = False,
               icon: str = "mdi:backup-restore", section: str = "system",
               display_name: str | None = None, metric: str | None = None,
               extra_attributes: str | None = None):
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
        marker = {"pbs_product": PRODUCT_ID, "pbs_section": section,
                  "pbs_metric": metric or key, "pbs_display_name": display_name or name,
                  "pbs_instance": ident}
        fields = ", ".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}"
                           for k, v in marker.items())
        item["json_attributes_topic"] = base + "/state"
        if attributes:
            item["json_attributes_template"] = item["json_attributes_template"].replace(
                "'observed_at': value_json.observed_at}",
                "'observed_at': value_json.observed_at, " + fields + "}",
            )
        else:
            if extra_attributes:
                fields += ", " + extra_attributes
            item["json_attributes_template"] = "{{ {" + fields + "} | tojson }}"
        components[key] = item

    # Three ready-to-render texts: Lovelace contains no backup/date logic.
    for name, label in (("backup", "Группы PBS"),
                        ("jobs", "Задания PBS"),
                        ("history", "История PBS"),
                        ("summary", "Сводка PBS")):
        tree_topic = base + "/tree/" + name
        components["tree_" + name] = {
            "platform": "sensor",
            "name": label,
            "unique_id": f"{device_id}_tree_{name}",
            "default_entity_id": f"sensor.dh_pbs_agent_{name}_tree",
            "state_topic": tree_topic,
            "value_template": "{{ value_json.status }}",
            "json_attributes_topic": tree_topic,
            "json_attributes_template":
                "{{ {'text': value_json.text, 'ha_timezone': value_json.ha_timezone} | tojson }}",
            "availability": availability, "entity_category": "diagnostic",
            "icon": "mdi:file-tree-outline",
        }

    sensor("hostname", "Имя сервера", "value_json.hostname", icon="mdi:server")
    sensor("ip", "IP-адрес", "value_json.ip", icon="mdi:ip-network")
    sensor("version", "Версия агента", "value_json.agent_version", icon="mdi:information-outline")
    sensor("health", "Состояние PBS", "value_json.status", attributes=True, section="health")
    sensor("ha_timezone", "Часовой пояс HA",
           "value_json.ha_timezone | default('unknown', true)",
           icon="mdi:earth")
    sensor("upload_stats", "Размеры новых данных",
           "(value_json.upload_summary.available | string) ~ '/' ~ (value_json.upload_summary.total | string) if value_json.upload_summary is defined else 'unknown'",
           icon="mdi:database-arrow-up",
           extra_attributes=("'reasons': value_json.upload_summary.reasons | default({}), "
                             "'sample_error': value_json.upload_summary.sample_error | default(none)"
                             " if value_json.upload_summary is defined else none"))
    sensor("last_collection", "Последний успешный опрос", "value_json.last_success_at | default('unknown', true)", icon="mdi:clock-check-outline")
    sensor("backup_last_success", "Последняя успешная резервная копия", "value_json.backup_last_success_at | default('unknown', true)")
    sensor("backup_age_hours", "Возраст резервной копии", "value_json.backup_age_hours | default('unknown', true)")
    sensor("sync_state", "Синхронизация копий", "value_json.sync_overall", icon="mdi:cloud-upload-outline")
    sensor("sync_last_success", "Последняя успешная синхронизация", "value_json.sync_last_success_at | default('unknown', true)")
    sensor("zfs_pool_health", "Состояние ZFS", "value_json.zfs.status", icon="mdi:database-check")
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
        "platform": "binary_sensor", "name": "Проблема PBS",
        "unique_id": f"{device_id}_problem",
        "default_entity_id": "binary_sensor.dh_pbs_agent_problem",
        "device_class": "problem", "state_topic": base + "/state",
        "value_template": "{{ 'ON' if value_json.status in ['CRITICAL', 'DEGRADED', 'UNAVAILABLE', 'UNKNOWN'] else 'OFF' }}",
        "payload_on": "ON", "payload_off": "OFF", "availability": availability,
        "entity_category": "diagnostic",
        "json_attributes_topic": base + "/state",
        "json_attributes_template": "{{ {'pbs_product': 'digitalhouses_pbs_agent', 'pbs_section': 'system', 'pbs_metric': 'problem', 'pbs_instance': " + json.dumps(ident) + "} | tojson }}",
    }
    for store in config.datastores:
        suffix = store.lower().replace("-", "_")
        # Each datastore has its own stable metric key, no overwrites.
        # Jinja literal is JSON-quoted so names containing quotes remain portable.
        store_literal = json.dumps(store, ensure_ascii=False)
        arr = f"(value_json.datastores | selectattr('name', 'equalto', {store_literal}) | list | first | default({{}}))"
        details = (
            "'total_gib': ((" + arr + ".total_bytes / 1073741824) | round(2)) "
            "if " + arr + ".total_bytes is defined else none, "
            "'used_gib': ((" + arr + ".used_bytes / 1073741824) | round(2)) "
            "if " + arr + ".used_bytes is defined else none, "
            "'pbs_health': " + arr + ".health | default('UNKNOWN', true), "
            "'pbs_backend': " + arr + ".backend | default('LOCAL', true), "
            "'card_name': " + arr + ".card_name | default('', true), "
            "'card_secondary': " + arr + ".card_secondary | default('', true), "
            "'card_color': " + arr + ".card_color | default('grey', true), "
            "'card_icon': " + arr + ".card_icon | default('mdi:database', true), "
            "'card_percent': " + arr + ".card_percent | default(0)"
        )
        sensor(f"datastore_{suffix}_used_percent", store + " · занято, %", arr + ".used_percent | default('unknown', true)",
               section="datastore", display_name=store, metric="used_percent",
               extra_attributes=details)
        # Historical occupied capacity: one numeric MQTT sensor per datastore.
        # HA Recorder owns long-term statistics and native daily hover tooltips.
        # Preserve diagnostic provenance markers for dynamic auto-entities.
        sensor(f"datastore_{suffix}_used_gib", store + " · занято, GiB",
               f"(({arr}.used_bytes / 1073741824) | round(2))"
               f" if {arr}.used_bytes is defined"
               f" and {arr}.health | default('UNAVAILABLE') != 'UNAVAILABLE'"
               f" and {arr}.backend | default('LOCAL') != 'S3' else none",
               section="datastore", display_name=store, metric="used_gib",
               icon="mdi:database")
        components[f"datastore_{suffix}_used_gib"].update({
            "state_class": "measurement",
            "unit_of_measurement": "GiB",
            "suggested_display_precision": 2,
        })
        sensor(f"datastore_{suffix}_available_gib", store + " · свободно, ГиБ",
               f"(({arr}.available_bytes / 1073741824) | round(2)) if {arr}.available_bytes is defined else 'unknown'",
               section="datastore", display_name=store, metric="available_gib")
    EVENT_TITLES = {
        "backup": "События резервного копирования",
        "sync": "События синхронизации",
        "storage": "События хранилищ",
        "maintenance": "События обслуживания",
    }
    catalog = {
        "backup": ["backup_failed", "backup_overdue", "backup_recovered", "service_unavailable", "service_recovered"],
        "sync": ["sync_failed", "sync_overdue", "sync_recovered"],
        "storage": ["disk_space_low", "disk_space_recovered", "zfs_pool_degraded", "zfs_pool_recovered"],
        "maintenance": ["verify_failed"],
    }
    for cat, event_types in catalog.items():
        components[f"{cat}_event"] = {
            "platform": "event", "name": EVENT_TITLES[cat],
            "unique_id": f"{device_id}_{cat}_event",
            "default_entity_id": f"event.dh_pbs_agent_{cat}_event",
            "state_topic": base + "/event/" + cat,
            "event_types": event_types, "qos": 1, "availability": availability,
            "entity_category": "diagnostic",
        }
    # PVE-compatible, stable native MQTT controls. Never reinterpret the
    # existing Number settings or PBS native task identities.
    commands = {
        "refresh": ("Обновить данные", "mdi:refresh"),
        "check_updates": ("Проверить версию", "mdi:cloud-search"),
        "update": ("Установить обновление", "mdi:package-down"),
        "restart_agent": ("Перезапустить агент", "mdi:restart"),
    }
    routes = {"refresh": "refresh", "check_updates": "check",
              "update": "install", "restart_agent": "restart"}
    for key, (title, icon) in commands.items():
        components[key] = {
            "platform": "button", "name": title,
            "unique_id": f"{device_id}_{key}",
            "default_entity_id": f"button.dh_pbs_agent_{key}",
            "command_topic": base + "/command/" + routes[key],
            "payload_press": "PRESS", "qos": 1, "retain": False,
            "availability": availability, "entity_category": "diagnostic",
            "icon": icon,
        }

    def operation_sensor(key: str, name: str, expression: str, icon: str,
                         attr_expression: str | None = None) -> None:
        item = {
            "platform": "sensor", "name": name,
            "unique_id": f"{device_id}_{key}",
            "default_entity_id": f"sensor.dh_pbs_agent_{key}",
            "state_topic": base + "/operation",
            "value_template": "{{ " + expression + " }}",
            "availability": availability, "entity_category": "diagnostic",
            "icon": icon,
        }
        if attr_expression:
            item["json_attributes_topic"] = base + "/operation"
            item["json_attributes_template"] = "{{ " + attr_expression + " | tojson }}"
        components[key] = item

    operation_sensor("card", "Управление PBS Agent", "value_json.card.state",
                     "mdi:backup-restore",
                     "{'operation': value_json.card.operation, 'started_at': value_json.card.started_at, 'finished_at': value_json.card.finished_at, 'duration_seconds': value_json.card.duration_seconds, 'error': value_json.card.error, 'last_collection_at': value_json.last_collection_at, 'from_version': value_json.card.from_version | default(none), 'target_version': value_json.card.target_version | default(none)}")
    operation_sensor("refresh_state", "Состояние обновления данных",
                     "value_json.refresh.state", "mdi:refresh",
                     "value_json.refresh")
    operation_sensor("last_refresh", "Последнее ручное обновление",
                     "value_json.last_refresh | default('unknown', true)",
                     "mdi:clock-check")
    operation_sensor("latest_version", "Последняя версия",
                     "value_json.latest_version | default('unknown', true)", "mdi:tag-check")
    operation_sensor("update_status", "Состояние проверки версии",
                     "value_json.update_status | default('idle', true)", "mdi:progress-wrench")
    components["update_available"] = {
        "platform": "binary_sensor", "name": "Доступна новая версия",
        "unique_id": f"{device_id}_update_available",
        "default_entity_id": "binary_sensor.dh_pbs_agent_update_available",
        "state_topic": base + "/operation",
        "value_template": "{{ 'ON' if value_json.update_available == true else 'OFF' if value_json.update_available == false else 'unknown' }}",
        "payload_on": "ON", "payload_off": "OFF",
        "availability": availability, "entity_category": "diagnostic",
        "icon": "mdi:package-up",
    }
    components["auto_update"] = {
        "platform": "switch", "name": "Автоматическое обновление",
        "unique_id": f"{device_id}_auto_update",
        "default_entity_id": "switch.dh_pbs_agent_auto_update",
        "command_topic": base + "/command/auto_update",
        "state_topic": base + "/operation",
        "value_template": "{{ 'ON' if value_json.auto_update == true else 'OFF' }}",
        "payload_on": "ON", "payload_off": "OFF",
        "state_on": "ON", "state_off": "OFF",
        "qos": 1, "retain": False, "availability": availability,
        "entity_category": "config", "icon": "mdi:autorenew",
    }
    components.update(job_components(config, sample))
    return {
        "device": {"identifiers": [device_id], "name": "DigitalHouses PBS Agent " + ident,
                   "manufacturer": "DigitalHouses", "model": "PBS Agent",
                   "sw_version": _read_version()},
        "origin": {"name": "DigitalHouses PBS Agent", "sw_version": _read_version(), "support_url": REPO},
        "components": components,
    }


class Publisher:
    def __init__(self, config: Config, *, view_limits: ViewLimits | None = None,
                 job_registry: StateStore | None = None,
                 timezone_store: StateStore | None = None):
        import paho.mqtt.client as mqtt
        self.config = config
        self.view_limits = view_limits if view_limits is not None else ViewLimits()
        self._state_lock = threading.Lock()
        self.job_registry = job_registry
        self.timezone_store = timezone_store
        try:
            saved_timezone = timezone_store.load().get("timezone") if timezone_store else None
        except (OSError, ValueError):
            saved_timezone = None
        self.ha_timezone = validate_timezone(saved_timezone)
        saved_jobs = job_registry.load().get("jobs", []) if job_registry else []
        self._known_jobs = {
            (str(row[0]), str(row[1])) for row in saved_jobs
            if isinstance(row, list) and len(row) == 2
        }
        self._discovery_primed = False
        self.id = instance_id(config)
        self.base = f"DigitalHouses/Global/{PRODUCT_ID}/{self.id}"
        self.discovery_topic = f"homeassistant/device/dh_pbs_agent_{self.id}/config"
        self.synctopic = self.base + "/sync"
        self.connected = False
        self.last_connect_error: str | None = None
        self.last_state: dict | None = None
        self.last_ack_at: str | None = None
        self.last_control: dict | None = None
        self.commands: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.auto_update_commands: queue.SimpleQueue[bool] = queue.SimpleQueue()
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

    def _publish_trees(self, client: Any, payload: dict) -> None:
        texts = render_trees(payload, getattr(self, "ha_timezone", None),
                             payload.get("view_limits") or self.view_limits.snapshot())
        for name, value in texts.items():
            msg = {"status": "OK", "text": value,
                   "ha_timezone": getattr(self, "ha_timezone", None) or "unknown"}
            client.publish(self.base + "/tree/" + name,
                           json.dumps(msg, ensure_ascii=False, separators=(",", ":")),
                           qos=1, retain=True)

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
        with self._state_lock:
            current = self.last_state
            if current is None:
                enqueue(self.discovery_topic, discovery(self.config))
                self._discovery_primed = False
            else:
                self._announce_jobs(client, current)
            client.subscribe(self.base + "/set/view/+", qos=1)
        client.subscribe(self.base + "/command/+", qos=1)
        client.subscribe(HA_TIMEZONE_TOPIC, qos=1)
        if self.last_control is not None:
            enqueue(self.base + "/operation", self.last_control)
            if current is not None:
                enqueue(self.base + "/state", current)
                self._publish_trees(client, current)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        if message.topic == HA_TIMEZONE_TOPIC:
            try:
                value = validate_timezone(message.payload.decode("utf-8").strip())
            except UnicodeDecodeError:
                value = None
            if value and value != self.ha_timezone:
                self.ha_timezone = value
                if self.timezone_store:
                    self.timezone_store.save({"timezone": value})
                with self._state_lock:
                    if self.last_state is not None:
                        updated = {**self.last_state, "ha_timezone": value}
                        self.last_state = updated
                        client.publish(self.base + "/state",
                                       json.dumps(updated, ensure_ascii=False, separators=(",", ":")),
                                       qos=1, retain=True)
                        self._publish_trees(client, updated)
            return
        # Do not replay stale retained commands when the broker reconnects.
        if getattr(message, "retain", False):
            return
        command_prefix = self.base + "/command/"
        if message.topic == command_prefix + "auto_update":
            if message.payload in (b"ON", b"OFF"):
                self.auto_update_commands.put(message.payload == b"ON")
            return
        if message.topic.startswith(command_prefix):
            action = message.topic[len(command_prefix):]
            if action in {"refresh", "check", "install", "restart"} and message.payload == b"PRESS":
                self.commands.put(action)
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
                self._publish_trees(client, new_state)

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

    def _announce_jobs(self, client: Any, sample: dict | None) -> None:
        """Publish device discovery only on change; remove obsolete job entities."""
        current = set(job_identity(sample)) if sample is not None else set(self._known_jobs)
        removed = self._known_jobs - current
        discovered = discovery(self.config, sample)
        if removed:
            deleting = discovery(self.config, sample)
            for kind, name in removed:
                deleting["components"][job_component_key(kind, name)] = {"platform": "sensor"}
            client.publish(self.discovery_topic, json.dumps(deleting, ensure_ascii=False), qos=1, retain=True)
        client.publish(self.discovery_topic, json.dumps(discovered, ensure_ascii=False), qos=1, retain=True)
        if sample is not None and self._known_jobs != current:
            if self.job_registry:
                self.job_registry.save({"jobs": [list(pair) for pair in sorted(current)]})
            self._known_jobs = current
        self._discovery_primed = True

    def state(self, payload: dict) -> bool:
        # Queue while locked so an incoming Number command cannot be overwritten
        # by a concurrent polling publish with older view settings.
        with self._state_lock:
            updated = {
                **payload,
                "view_limits": self.view_limits.snapshot(),
                "ha_timezone": getattr(self, "ha_timezone", None),
            }
            self.last_state = updated
            if not self.connected:
                return False
            data = json.dumps(updated, ensure_ascii=False, separators=(",", ":"))
            current_jobs = set(job_identity(updated))
            if updated.get("status") != "UNAVAILABLE" and (
                not self._discovery_primed or current_jobs != self._known_jobs
            ):
                self._announce_jobs(self.client, updated)
            info = self.client.publish(self.base + "/state", data, qos=1, retain=True)
            self._publish_trees(self.client, updated)
        if info.rc != 0:
            return False
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            return False
        from datetime import datetime, timezone
        self.last_ack_at = datetime.now(timezone.utc).isoformat()
        return True

    def control(self, payload: dict) -> bool:
        self.last_control = payload
        return self._send(self.base + "/operation", payload, retain=True)

    def event(self, category: str, payload: dict) -> bool:
        if category not in {"backup", "sync", "storage", "maintenance"}:
            raise ValueError("invalid event category")
        return self._send(self.base + "/event/" + category, payload, retain=False)

    def stop(self) -> None:
        if self.connected:
            self._send(self.base + "/availability", "offline", retain=True)
            self.client.disconnect()
        self.client.loop_stop()
