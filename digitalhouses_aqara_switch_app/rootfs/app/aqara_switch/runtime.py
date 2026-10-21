"""MQTT runtime: explicit Scan/adopt, settings Mode Keeper, bound Aqara light toggle.

No unbound device commands, physical relay ON/OFF or group changes.
"""
from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import queue
import re
import threading
import time

from .catalog import (CatalogError, candidate_from_mqtt, decode_bridge_devices,
                      resolve_hardware)
from .actions import ActionError
from .control import HAClient, light_action, settings_drift, verified_adopted_switch
from .configuration import parse_configuration
from .ha_registry import HARegistryClient
from .mqtt_ui import (
    AVAILABILITY, DISCOVERY_TOPIC, ROOT, SCAN_REQUEST, wire_payload,
)
from .scan import scan_once
from .supervisor import SupervisorOptions
from .structured_options import migrate as migrate_structured_options

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
    """Single MQTT client, manual adopt, narrow light control, settings keeper."""
    def __init__(self, mqtt_module, *, options: SupervisorOptions | None = None,
                 registry: HARegistryClient | None = None,
                 last_scan_path: Path = Path("/data/last_scan.json"),
                 version: str | None = None, ha_client: HAClient | None = None):
        self.version = version if version is not None else os.environ["APP_VERSION"]
        self.options = options or SupervisorOptions()
        self.registry = registry or HARegistryClient(os.environ.get("SUPERVISOR_TOKEN", ""))
        self.config = parse_configuration(self.options.read())
        self._previous = _load_previous(last_scan_path)
        self._previous_path = last_scan_path
        self._stop = threading.Event()
        self._ha_client = ha_client
        self._jobs = queue.Queue(maxsize=64)
        self._last_action = {"state": "idle", "at": None, "switch": None,
                             "action": None, "target": None, "error": None}
        self._last_action_at = {}
        self._last_mode_request = {}
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
        self._publish(ROOT + "/last_action", dict(self._last_action))
        self._publish_card()

    def _publish_action(self, *, state, switch, action, target, error=None):
        self._last_action = {"state": state, "at": _iso_now(),
                             "switch": switch, "action": action,
                             "target": target, "error": error}
        self._publish(ROOT + "/last_action", dict(self._last_action))

    def _publish_card(self):
        self._publish(ROOT + "/card", dict(self._card))

    def _publish_details(self):
        """Publish device identity/fingerprint problems without relay writes."""
        with self._mutex:
            config = deepcopy(self.config)
            networks = verified_snapshots(self._networks)
        problems = []
        for room in config["rooms"]:
            for switch in room["switches"]:
                peers = []
                unverified = []
                for network in networks:
                    if network["coordinator_ieee"] != switch["coordinator_ieee"]:
                        continue
                    for device in decode_bridge_devices(network["devices"]):
                        if device.get("friendly_name") != switch["logical_name"]:
                            continue
                        try:
                            candidate = candidate_from_mqtt(
                                device,
                                coordinator_ieee=network["coordinator_ieee"],
                                base_topic=network["base_topic"],
                                reported_state=network["states"].get(
                                    device["friendly_name"]
                                ),
                            )
                            if candidate is None:
                                raise CatalogError("Unsupported Aqara input profile")
                            peers.append(candidate)
                        except (CatalogError, KeyError) as exc:
                            unverified.append(str(exc))
                if not switch.get("enabled", True):
                    result = {"status": "disabled"}
                elif unverified:
                    result = {"status": "unverified", "reason": "; ".join(unverified)}
                else:
                    result = resolve_hardware(switch, peers)
                    if (result["status"] == "same" and peers
                            and peers[0]["settings"] != switch["settings"]):
                        result = {"status": "settings_mismatch",
                                  "reason": "Physical settings differ from saved baseline",
                                  "observed_ieee": peers[0]["ieee"]}
                switch["runtime"] = result
                if result["status"] not in ("same", "disabled"):
                    problems.append({
                        "object_name": switch["logical_name"],
                        "category": result["status"],
                        "reason": result.get("reason"),
                    })
        self._publish(ROOT + "/devices", {"state": "ready", "rooms": config["rooms"]})
        self._publish(ROOT + "/problems", {
            "state": "ready", "active": problems[:100], "count": len(problems)
        })

    def _on_connect(self, client, userdata, flags, rc):
        del client, userdata, flags
        if rc != 0:
            LOG.error("MQTT connect failed: %s", rc)
            return
        with self._mutex:
            self._subscribed.clear()
            self._networks.clear()
            self._last_action_at.clear()
            self._last_mode_request.clear()
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
        # Only explicit fresh Zigbee2MQTT device actions can trigger a binding.
        # Retained states and replayed frames must never toggle a lamp.
        with self._mutex:
            for base, net in self._networks.items():
                if not message.topic.startswith(base + "/") or message.topic.endswith(("/set", "/get")):
                    continue
                name = message.topic[len(base) + 1:]
                try:
                    devices = decode_bridge_devices(net["devices"])
                    device = next((d for d in devices if d.get("friendly_name") == name
                                   and d.get("type") != "Coordinator"), None)
                    if device is None:
                        continue
                    data = json.loads(bytes(message.payload))
                    if not isinstance(data, dict):
                        continue
                    previous = net["states"].get(name, {})
                    if not isinstance(previous, dict):
                        previous = {}
                    # Action is transient, never persist it as a future current state.
                    net["states"][name] = {**{k: v for k, v in previous.items()
                                               if k != "action"},
                                           **{k: v for k, v in data.items()
                                              if k != "action"}}
                    if not getattr(message, "retain", False) and not getattr(message, "dup", False):
                        self._process_adopted_event(base, net, device, data)
                except (KeyError, CatalogError, ValueError, UnicodeDecodeError, TypeError) as exc:
                    LOG.warning("Invalid Z2M state %s: %s", message.topic, exc)
                break

    def _process_adopted_event(self, base, net, device, data):
        """Requires exact logical identity and observed compatible hardware."""
        raw_info = net.get("info")
        if not isinstance(raw_info, bytes):
            return
        try:
            coordinator = json.loads(raw_info)["coordinator"]["ieee_address"].lower()
            devices = decode_bridge_devices(net["devices"])
            actual_coordinators = [d.get("ieee_address", "").lower() for d in devices
                                   if d.get("type") == "Coordinator"]
            if actual_coordinators != [coordinator]:
                return
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, CatalogError):
            return
        for room in self.config["rooms"]:
            for saved in room["switches"]:
                if not saved.get("enabled", True):
                    continue
                if not verified_adopted_switch(saved, device, coordinator, base):
                    continue
                name = saved["logical_name"]
                # Keep only the writable physical *configuration* captured at Adopt;
                # never publish state / relay ON or OFF.
                drift = settings_drift(saved, data)
                now = time.monotonic()
                if drift:
                    requested = {key: value for key, value in drift.items()
                                 if now - self._last_mode_request.get((base, name, key), -1e9) >= 60}
                    if requested:
                        for key in requested:
                            self._last_mode_request[(base, name, key)] = now
                        self._publish(base + "/" + name + "/set", requested, retain=False)
                        LOG.warning("Mode Keeper restore requested: %s / %s keys=%s",
                                    base, name, sorted(requested))
                        self._publish_details()
                action = data.get("action")
                if not isinstance(action, str) or not action:
                    continue
                dedupe_key = (coordinator, name, action)
                if now - self._last_action_at.get(dedupe_key, -1e9) < 0.35:
                    LOG.debug("Ignored duplicate action from %s: %s", name, action)
                    continue
                self._last_action_at[dedupe_key] = now
                try:
                    command = light_action(saved, action)
                except ActionError as exc:
                    LOG.error("Invalid binding %s / %s: %s", name, action, exc)
                    self._publish_action(state="error", switch=name, action=action,
                                         target=None, error=str(exc))
                    continue
                if command is None:
                    continue
                target = command["target"]["entity_id"][0]
                try:
                    self._jobs.put_nowait((name, action, target))
                    self._publish_action(state="queued", switch=name, action=action,
                                         target=target)
                except queue.Full:
                    self._publish_action(state="error", switch=name, action=action,
                                         target=target, error="Action queue is full")

    def _run_actions(self):
        """Serial HA calls preserve toggle order and avoid blocking MQTT callbacks."""
        if self._ha_client is None:
            self._ha_client = HAClient(os.environ.get("SUPERVISOR_TOKEN", ""))
        while not self._stop.is_set():
            try:
                name, action, entity = self._jobs.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._ha_client.toggle(entity)
                self._publish_action(state="accepted", switch=name, action=action,
                                     target=entity)
                LOG.info("Aqara %s / %s -> light.toggle %s accepted by HA",
                         name, action, entity)
            except Exception as exc:
                LOG.exception("Home Assistant light.toggle failed")
                self._publish_action(state="error", switch=name, action=action,
                                     target=entity, error=str(exc)[:300])
            finally:
                self._jobs.task_done()

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
        # Fail closed until old profiles and bindings have migrated safely.
        migrated = migrate_structured_options(self.options)
        with self._mutex:
            self.config = parse_configuration(migrated)
        host, port = os.environ["MQTT_HOST"], int(os.environ["MQTT_PORT"])
        LOG.info("Starting Aqara Adopt + Mode Keeper + light.toggle MVP %s", self.version)
        threading.Thread(target=self._run_actions, daemon=True,
                         name="dh-aqara-action-worker").start()
        self.client.connect(host, port, keepalive=60)
        self.client.loop_forever(retry_first_connection=True)
