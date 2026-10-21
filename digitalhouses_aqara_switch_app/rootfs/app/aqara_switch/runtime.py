"""MQTT runtime: read-only observation + explicit user-pressed Scan only.

No physical Zigbee2MQTT set/get requests, relay writes, or target HA commands.
"""
from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import threading
import time

from .catalog import CatalogError, decode_bridge_devices, validate_config
from .configuration import parse_configuration
from .ha_registry import HARegistryClient
from .mqtt_ui import (
    AVAILABILITY, DISCOVERY_TOPIC, ROOT, SCAN_REQUEST, wire_payload,
)
from .scan import scan_once
from .supervisor import SupervisorOptions

LOG = logging.getLogger(__name__)
_IEEE = re.compile(r"^0x[0-9a-f]{16}$")
_BASE_FORBIDDEN = {"homeassistant", "DigitalHouses", "$SYS"}
_FILTERS = tuple(
    "/".join(["+"] * levels) + "/bridge/" + suffix
    for levels in (1, 2, 3) for suffix in ("info", "devices")
)


def bridge_path(topic: str) -> tuple[str, str] | None:
    base, sep, suffix = topic.rpartition("/bridge/")
    if not sep or suffix not in ("info", "devices"):
        return None
    parts = base.split("/")
    if not 1 <= len(parts) <= 3 or parts[0] in _BASE_FORBIDDEN or any(
        not segment or segment in {"+", "#", ".", ".."} for segment in parts
    ):
        return None
    return base, suffix


def verified_snapshots(networks: Mapping) -> list[dict]:
    """Require complete, mutually consistent MQTT bridge info+inventory."""
    ready = []
    for base, info in sorted(networks.items()):
        if not isinstance(info, Mapping):
            continue
        raw_info, raw_devices = info.get("info"), info.get("devices")
        if not isinstance(raw_info, bytes) or not isinstance(raw_devices, bytes):
            continue
        try:
            decoded = json.loads(raw_info)
            coord = decoded["coordinator"]["ieee_address"]
            if not isinstance(coord, str) or not _IEEE.fullmatch(coord.lower()):
                continue
            devices = decode_bridge_devices(raw_devices)
            peers = [d.get("ieee_address") for d in devices
                     if d.get("type") == "Coordinator"]
            if len(peers) != 1 or not isinstance(peers[0], str) or peers[0].lower() != coord.lower():
                continue
        except (KeyError, ValueError, TypeError, AttributeError, CatalogError):
            continue
        ready.append({
            "base_topic": base,
            "coordinator_ieee": coord.lower(),
            "devices": raw_devices,
            "states": deepcopy(info.get("states", {})),
        })
    return ready


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_previous(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
        if len(raw) > 262144:
            raise ValueError("Last scan file exceeds limit")
        record = json.loads(raw)
    except (OSError, ValueError) as exc:
        LOG.warning("Unable to load prior scan record: %s", exc)
        return None
    return record if isinstance(record, dict) else None


def _save_previous(path: Path, report: dict) -> None:
    encoded = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 262144:
        raise CatalogError("Scan report exceeds persistent size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(encoded, encoding="utf-8")
    tmp.replace(path)


class Application:
    """One MQTT client and one foreground scan worker, entirely read-only."""
    def __init__(self, mqtt_module, *, options: SupervisorOptions | None = None,
                 registry: HARegistryClient | None = None,
                 last_scan_path: Path = Path("/data/last_scan.json"),
                 version: str | None = None):
        self.version = version if version is not None else os.environ["APP_VERSION"]
        self.options = options or SupervisorOptions()
        self.registry = registry or HARegistryClient(os.environ.get("SUPERVISOR_TOKEN", ""))
        self.config = parse_configuration(self.options.read())
        self._previous = _load_previous(last_scan_path)
        self._previous_path = last_scan_path
        self._stop = threading.Event()
        self._mutex = threading.RLock()
        self._scan_lock = threading.Lock()
        self._networks: dict[str, dict] = {}
        self._subscribed: set[str] = set()
        self._scan = {"state": "idle", "started_at": None,
                      "finished_at": None, "duration_seconds": None, "error": None}
        self._card = {"state": "idle", "operation": None,
                      "started_at": None, "finished_at": None,
                      "duration_seconds": None, "error": None}
        if hasattr(mqtt_module, "CallbackAPIVersion"):
            self.client = mqtt_module.Client(
                mqtt_module.CallbackAPIVersion.VERSION1,
                client_id="dh-aqara-switch-app",
            )
        else:
            self.client = mqtt_module.Client(client_id="dh-aqara-switch-app")
        user = os.getenv("MQTT_USER", "")
        if user:
            self.client.username_pw_set(user, os.getenv("MQTT_PASSWORD", ""))
        self.client.will_set(AVAILABILITY, "offline", qos=1, retain=True)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _publish(self, path: str, data, retain: bool = True) -> None:
        payload = data if isinstance(data, str) else json.dumps(
            data, ensure_ascii=False, separators=(",", ":")
        )
        result = self.client.publish(path, payload, qos=1, retain=retain)
        if getattr(result, "rc", 1) != 0:
            LOG.error("MQTT publication failed: %s", path)

    def _subscribe(self, topic: str) -> None:
        with self._mutex:
            if topic in self._subscribed:
                return
            result = self.client.subscribe(topic, qos=1)
            if result[0] == 0:
                self._subscribed.add(topic)
            else:
                LOG.error("MQTT subscription failed: %s", topic)

    def _publish_all(self):
        self._publish(DISCOVERY_TOPIC, wire_payload(self.version))
        self._publish(ROOT + "/version", self.version)
        self._publish(ROOT + "/scan_state", dict(self._scan))
        self._publish(ROOT + "/scan_details", {"state": "ready" if self._previous else "unknown",
                                               **(self._previous or {})})
        self._publish_details()
        self._publish_card()

    def _publish_card(self):
        self._publish(ROOT + "/card", dict(self._card))

    def _publish_details(self):
        with self._mutex:
            config = deepcopy(self.config)
            networks = verified_snapshots(self._networks)
        for room in config["rooms"]:
            for switch in room["switches"]:
                matches = [d for net in networks for d in decode_bridge_devices(net["devices"])
                           if net["coordinator_ieee"] == switch["coordinator_ieee"]
                           and d.get("friendly_name") == switch["logical_name"]]
                switch["online_identity"] = (matches[0].get("ieee_address")
                                              if len(matches) == 1 else None)
                switch["status"] = "observed" if len(matches) == 1 else "unknown"
        self._publish(ROOT + "/devices", {"state": "ready", "rooms": config["rooms"]})
        self._publish(ROOT + "/problems", {"state": "ready", "active": []})

    def _on_connect(self, client, userdata, flags, rc):
        del client, userdata, flags
        if rc != 0:
            LOG.error("MQTT connect failed: %s", rc)
            return
        with self._mutex:
            self._subscribed.clear()
            self._networks.clear()
        for topic in (*_FILTERS, SCAN_REQUEST, "homeassistant/status"):
            self._subscribe(topic)
        self._publish(AVAILABILITY, "online")
        self._publish_all()

    def _on_disconnect(self, client, userdata, rc):
        del client, userdata
        if rc:
            LOG.warning("MQTT disconnected: %s", rc)
        with self._mutex:
            self._subscribed.clear()
            self._networks.clear()

    def _on_message(self, client, userdata, message):
        del client, userdata
        if message.topic == SCAN_REQUEST:
            # No startup scan; no retained command replay.
            if not message.retain and bytes(message.payload) == b"SCAN":
                self.request_scan()
            return
        if message.topic == "homeassistant/status":
            if bytes(message.payload) == b"online":
                self._publish_all()
            return
        parsed = bridge_path(message.topic)
        if parsed:
            base, suffix = parsed
            with self._mutex:
                node = self._networks.setdefault(base, {"states": {}})
                node[suffix] = bytes(message.payload)
                if suffix == "devices":
                    try:
                        devices = decode_bridge_devices(node["devices"])
                    except CatalogError:
                        LOG.warning("Invalid Zigbee2MQTT inventory: %s", base)
                        return
                    for device in devices:
                        name = device.get("friendly_name")
                        if isinstance(name, str) and name and device.get("type") != "Coordinator":
                            self._subscribe(base + "/" + name)
            self._publish_details()
            return
        # Capturing observed device state does not import or rewrite options.
        with self._mutex:
            for base, net in self._networks.items():
                if message.topic.startswith(base + "/") and not message.topic.endswith(("/set", "/get")):
                    topic_name = message.topic[len(base) + 1:]
                    try:
                        if topic_name in {x.get("friendly_name") for x in decode_bridge_devices(net["devices"])}:
                            payload = json.loads(bytes(message.payload))
                            if isinstance(payload, dict):
                                net["states"][topic_name] = payload
                    except (KeyError, CatalogError, ValueError, UnicodeDecodeError):
                        pass
                    break

    def request_scan(self) -> bool:
        if not self._scan_lock.acquire(blocking=False):
            return False
        threading.Thread(target=self._run_scan, daemon=True,
                         name="dh-aqara-manual-scan").start()
        return True

    def _run_scan(self) -> None:
        start = time.monotonic()
        now = _iso_now()
        with self._mutex:
            snapshots = verified_snapshots(self._networks)
        self._scan = {"state": "updating", "started_at": now,
                      "finished_at": None, "duration_seconds": None, "error": None}
        self._card = {"state": "running", "operation": "scan",
                      "started_at": now, "finished_at": None,
                      "duration_seconds": None, "error": None}
        self._publish(ROOT + "/scan_state", self._scan)
        self._publish_card()
        try:
            if not snapshots:
                raise CatalogError("No confirmed Zigbee2MQTT network snapshot available")
            merged, report = scan_once(snapshots, self.options, self.registry)
            _save_previous(self._previous_path, report)
            with self._mutex:
                self.config = merged
                self._previous = report
            self._publish_details()
            self._publish(ROOT + "/scan_details", {"state": "ready", **report})
            error = None
        except Exception as exc:
            LOG.exception("Manual Aqara scan failed")
            error = str(exc)
        finally:
            duration = round(time.monotonic() - start, 3)
            finished = _iso_now()
            self._scan = {"state": "error" if error else "idle", "started_at": now,
                          "finished_at": finished, "duration_seconds": duration,
                          "error": error}
            self._card = {"state": "error" if error else "success",
                          "operation": "scan", "started_at": now,
                          "finished_at": finished, "duration_seconds": duration,
                          "error": error}
            self._publish(ROOT + "/scan_state", self._scan)
            self._publish_card()
            self._scan_lock.release()

    def run(self) -> None:
        host, port = os.environ["MQTT_HOST"], int(os.environ["MQTT_PORT"])
        LOG.info("Starting read-only Aqara scan pilot %s", self.version)
        self.client.connect(host, port, keepalive=60)
        self.client.loop_forever(retry_first_connection=True)
