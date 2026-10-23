"""MQTT runtime: Aqara button input, selective Mode Keeper and Z2M light output.

No unverified relay writes or individual blind toggles; six LAB lights use HA REST.
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
from .control import HAClient, light_commands, verified_adopted_switch
from .mqtt_lights import plan_batch
from .lab_lights import partition_commands, plan_lab
from .light_routes import current_route
from .keeper_runtime import run_keeper
from .mode_keeper import (capabilities, global_policy, maintained_switch,
                          mode_action_allowed)
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
    for levels in (1, 2, 3) for suffix in ("info", "devices", "state")
)


def bridge_path(topic: str) -> tuple[str, str] | None:
    base, sep, suffix = topic.rpartition("/bridge/")
    if not sep or suffix not in ("info", "devices", "state"):
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
        options_snapshot = self.options.read()
        self.config = parse_configuration(options_snapshot)
        self.globals = global_policy(options_snapshot)
        self._previous = _load_previous(last_scan_path)
        self._previous_path = last_scan_path
        self._stop = threading.Event()
        self._ha_client = ha_client
        self._jobs = queue.Queue(maxsize=64)
        self._last_action = {"state": "idle", "at": None, "switch": None,
                             "action": None, "target": None, "error": None}
        self._last_action_at = {}
        self._last_mode_request = {}
        self._mode_pending = {}
        self._mode_probes = {}
        self._fresh_fields = set()
        self._light_availability = {}
        self._light_shadows = {}
        self._lab_shadows = {}
        self._light_observed_at = {}
        self._light_probe_at = {}
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
            return False
        return True

    def _subscribe(self, topic: str) -> None:
        with self._mutex:
            if topic in self._subscribed:
                return
            result = self.client.subscribe(topic, qos=1)
            if result[0] == 0:
                self._subscribed.add(topic)
            else:
                LOG.error("MQTT subscription failed: %s", topic)

    def _sync_light_topics(self):
        """Subscribe to verified route availability and Z2M state topics."""
        for route in self.config.get("light_routes", {}).values():
            base, name = route["base_topic"], route["friendly_name"]
            if base not in self._networks:
                continue
            self._subscribe(base + "/" + name)
            self._subscribe(base + "/" + name + "/availability")

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
                    # Only explicit keep_mode is a contract. Captured
                    # non-managed factory settings must never be compared
                    # against the current state as an error.
                    if (result["status"] == "same" and switch.get("keep_mode")
                            and not maintained_switch(switch, self.globals)):
                        current = next((n["states"].get(switch["logical_name"], {})
                                        for n in networks
                                        if n["coordinator_ieee"] == switch["coordinator_ieee"]
                                        and n["base_topic"] == switch["base_topic"]), {})
                        from .mode_keeper import MODE_TO_RELAY
                        mismatches = [key for key in switch["keep_mode"]
                                      if current.get(MODE_TO_RELAY[key][0]) not in
                                         (None, "decoupled") or
                                         current.get(MODE_TO_RELAY[key][1]) == "OFF"]
                        if mismatches:
                            result = {"status":"keep_mode_mismatch",
                                      "reason":"Protected keys drifted: " + ", ".join(mismatches)}
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
            self._mode_pending.clear()
            self._mode_probes.clear()
            self._fresh_fields.clear()
            self._light_availability.clear()
            self._light_shadows.clear()
            self._lab_shadows.clear()
            self._light_observed_at.clear()
            self._light_probe_at.clear()
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
            self._fresh_fields.clear()
            self._light_availability.clear()
            self._light_shadows.clear()
            self._lab_shadows.clear()
            self._light_observed_at.clear()
            self._light_probe_at.clear()

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
        if message.topic.endswith("/availability"):
            with self._mutex:
                for route in self.config.get("light_routes", {}).values():
                    base, name = route["base_topic"], route["friendly_name"]
                    if message.topic != base + "/" + name + "/availability":
                        continue
                    try:
                        payload = bytes(message.payload).decode("utf-8")
                        status = payload.strip().lower()
                        if status.startswith("{"):
                            status = str(json.loads(payload).get("state", "")).lower()
                        if status not in ("online", "offline"):
                            status = "unknown"
                    except (UnicodeDecodeError, ValueError, TypeError):
                        status = "unknown"
                    ident = (base, name)
                    self._light_availability[ident] = status
                    if status != "online":
                        self._light_shadows.pop(ident, None)
                        self._light_observed_at.pop(ident, None)
                        self._fresh_fields.discard((base, name, "state"))
            return
        parsed = bridge_path(message.topic)
        if parsed:
            base, suffix = parsed
            with self._mutex:
                node = self._networks.setdefault(base, {"states": {}})
                if suffix == "state":
                    try:
                        reported = json.loads(bytes(message.payload))
                        node["bridge_state"] = (
                            reported.get("state") if isinstance(reported, dict)
                            else reported if isinstance(reported, str) else "unknown")
                    except (TypeError, ValueError):
                        node["bridge_state"] = "unknown"
                    if node["bridge_state"] != "online":
                        for route in self.config.get("light_routes", {}).values():
                            if route["base_topic"] == base:
                                ident = (base, route["friendly_name"])
                                self._light_availability.pop(ident, None)
                                self._light_shadows.pop(ident, None)
                                self._fresh_fields.discard((base, ident[1], "state"))
                    return
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
                    self._sync_light_topics()
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
                    if not getattr(message, "retain", False):
                        for field in data:
                            if field != "action":
                                self._fresh_fields.add((base, name, field))
                        if data.get("state") in ("ON", "OFF"):
                            ident = (base, name)
                            self._light_observed_at[ident] = time.monotonic()
                            shadow = self._light_shadows.get(ident)
                            if shadow and shadow["value"] == data["state"]:
                                self._light_shadows.pop(ident, None)
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
                # Old generic baseline restoration is intentionally disabled.
                # Only keys explicitly present in user keep_mode are repaired.
                now = time.monotonic()
                action = data.get("action")
                if not isinstance(action, str) or not action:
                    continue
                maintenance = maintained_switch(saved, self.globals)
                state = net.get("states", {}).get(name, {})
                features = capabilities(device)
                if not mode_action_allowed(saved, action, state, features, maintenance):
                    continue
                # Wired key mode must be freshly confirmed after reconnect.
                if features:
                    keys = (("left", "right") if action.endswith("_both")
                            else (action.rsplit("_", 1)[-1],)
                            if action.rsplit("_", 1)[-1] in features
                            else tuple(features))
                    if any((base, name, features[k][0]) not in self._fresh_fields
                           for k in keys if k in features):
                        continue
                dedupe_key = (coordinator, name, action)
                if now - self._last_action_at.get(dedupe_key, -1e9) < 0.35:
                    LOG.debug("Ignored duplicate action from %s: %s", name, action)
                    continue
                self._last_action_at[dedupe_key] = now
                try:
                    commands = light_commands(saved, action)
                except ActionError as exc:
                    LOG.error("Invalid binding %s / %s: %s", name, action, exc)
                    self._publish_action(state="error", switch=name, action=action,
                                         target=None, error=str(exc))
                    continue
                if commands is None:
                    continue
                targets = [eid for command in commands for eid in command["target"]["entity_id"]]
                target_label = ", ".join(targets)
                try:
                    self._jobs.put_nowait((base, coordinator, name, action, commands))
                    self._publish_action(state="queued", switch=name, action=action,
                                         target=target_label)
                except queue.Full:
                    self._publish_action(state="error", switch=name, action=action,
                                         target=target_label, error="Action queue is full")

    def _run_light_probes(self):
        """Rate-limited Z2M state reads so restart never trusts retained state.

        At most two GET requests per Zigbee network per second. Only mapped
        online lights with a verified read capability may be queried.
        """
        while not self._stop.wait(1):
            with self._mutex:
                per_network = {}
                now = time.monotonic()
                for route in self.config.get("light_routes", {}).values():
                    base, name = route["base_topic"], route["friendly_name"]
                    ident = (base, name)
                    if (per_network.get(base, 0) >= 2 or
                            self._light_availability.get(ident) != "online" or
                            (base, name, "state") in self._fresh_fields or
                            not route.get("features", {}).get("state", {}).get("readable") or
                            now - self._light_probe_at.get(ident, -1e9) < 30):
                        continue
                    net = self._networks.get(base, {})
                    if (net.get("bridge_state") != "online" or
                            not current_route(route, net)):
                        continue
                    self._light_probe_at[ident] = now
                    if self._publish(base + "/" + name + "/get",
                                     {"state": ""}, retain=False):
                        per_network[base] = per_network.get(base, 0) + 1

    def _run_actions(self):
        """Execute direct Z2M /set and allowlisted virtual LAB light commands."""
        while not self._stop.is_set():
            try:
                base, coordinator, name, action, commands = self._jobs.get(timeout=1)
            except queue.Empty:
                continue
            targets = [eid for cmd in commands for eid in cmd["target"]["entity_id"]]
            try:
                # Preflight LAB outside the MQTT lock, before ANY Z2M publish.
                z2m_commands, lab_commands = partition_commands(
                    commands, self.config.get("light_routes", {}))
                mixed_toggle = bool(
                    z2m_commands and lab_commands
                    and all(cmd["service"] == "light.toggle" for cmd in commands))
                lab_state_cache = {}
                def read_lab_once(entity):
                    if entity not in lab_state_cache:
                        lab_state_cache[entity] = self._ha_client.read_lab_state(entity)
                    return lab_state_cache[entity]
                lab_preview = []
                if mixed_toggle:
                    if self._ha_client is None:
                        self._ha_client = HAClient(os.environ.get("SUPERVISOR_TOKEN", ""))
                    lab_preview, _ = plan_lab(
                        lab_commands, read_lab_once, self._lab_shadows,
                        time.monotonic())

                with self._mutex:
                    sw = next((x for room in self.config["rooms"]
                               for x in room["switches"]
                               if (x["logical_name"] == name and
                                   x["base_topic"] == base and
                                   x["coordinator_ieee"] == coordinator)), None)
                    if (sw is None or not sw.get("enabled", False) or
                            maintained_switch(sw, self.globals)):
                        raise ActionError("Disabled switch or Maintenance active")
                    net = self._networks.get(base, {})
                    raw = net.get("devices")
                    if not isinstance(raw, bytes):
                        raise ActionError("Zigbee2MQTT input inventory unavailable")
                    device = next((d for d in decode_bridge_devices(raw)
                                   if d.get("friendly_name") == name), None)
                    if (device is None or not verified_adopted_switch(
                            sw, device, coordinator, base) or not mode_action_allowed(
                            sw, action, net.get("states", {}).get(name, {}),
                            capabilities(device), False)):
                        raise ActionError("Aqara key not verified in decoupled/ON operating mode")
                    # Repartition after a possible Scan; no guessed light routes.
                    z2m_commands, lab_commands = partition_commands(
                        commands, self.config.get("light_routes", {}))
                    toggle_override = None
                    if mixed_toggle:
                        z2m_preview, _ = plan_batch(
                            z2m_commands, self.config.get("light_routes", {}),
                            self._networks, self._light_availability,
                            self._fresh_fields, self._light_shadows,
                            self._light_observed_at, time.monotonic())
                        # Only eligible, state-known targets influence the decision.
                        if z2m_preview or lab_preview:
                            toggle_override = (
                                "ON" if (
                                    any(p["state"] == "ON" for p in z2m_preview)
                                    or any(p["service"] == "light.turn_on"
                                           for p in lab_preview)
                                ) else "OFF")
                    plans, skipped = plan_batch(
                        z2m_commands, self.config.get("light_routes", {}),
                        self._networks, self._light_availability,
                        self._fresh_fields, self._light_shadows,
                        self._light_observed_at, time.monotonic(),
                        toggle_state_override=toggle_override)
                    sent = []
                    for plan in plans:
                        if self._publish(plan["topic"], plan["payload"],
                                         retain=False):
                            ident = plan["ident"]
                            self._light_shadows[ident] = {
                                "value": plan["state"], "at": time.monotonic()}
                            sent.append(plan["light"])
                        else:
                            skipped.append({"light":plan["light"],
                                            "reason":"MQTT publish rejected"})
                # The only HA-dependent path is the six named virtual LAB
                # lamps. Leave the mutex free while reading HA REST states.
                if lab_commands:
                    if self._ha_client is None:
                        self._ha_client = HAClient(os.environ.get("SUPERVISOR_TOKEN", ""))
                    lab_plans, lab_skipped = plan_lab(
                        lab_commands,
                        read_lab_once if mixed_toggle else self._ha_client.read_lab_state,
                        self._lab_shadows, time.monotonic(),
                        toggle_state_override=toggle_override)
                    skipped.extend(lab_skipped)
                    for call in lab_plans:
                        ids = call["target"]["entity_id"]
                        with self._mutex:
                            current_sw = next(
                                (x for room in self.config["rooms"]
                                 for x in room["switches"]
                                 if x["logical_name"] == name and
                                 x["base_topic"] == base and
                                 x["coordinator_ieee"] == coordinator), None)
                            net = self._networks.get(base, {})
                            device = None
                            if isinstance(net.get("devices"), bytes):
                                device = next(
                                    (d for d in decode_bridge_devices(net["devices"])
                                     if d.get("friendly_name") == name), None)
                            authorized = (
                                current_sw is not None and device is not None
                                and current_sw.get("enabled", False)
                                and not maintained_switch(current_sw, self.globals)
                                and verified_adopted_switch(
                                    current_sw, device, coordinator, base)
                                and mode_action_allowed(
                                    current_sw, action,
                                    net.get("states", {}).get(name, {}),
                                    capabilities(device), False))
                        if not authorized:
                            skipped.extend({"light":eid,
                                            "reason":"Aqara key or Maintenance changed"}
                                           for eid in ids)
                            continue
                        try:
                            self._ha_client.execute(call)
                        except Exception as exc:
                            LOG.warning("AQARA LAB HA call failed: %s", exc)
                            skipped.extend({"light":eid,
                                            "reason":"LAB HA service call failed"}
                                           for eid in ids)
                            continue
                        value = "on" if call["service"] == "light.turn_on" else "off"
                        with self._mutex:
                            for eid in ids:
                                self._lab_shadows[eid] = {
                                    "state":value, "at": time.monotonic()}
                        sent.extend(ids)
                if skipped:
                    LOG.warning("Aqara action %s %s skipped: %s", name, action, skipped)
                note = "; ".join(x["light"]+": "+x["reason"] for x in skipped)
                status = ("partial" if sent and skipped else
                          "sent" if sent else "skipped")
                self._publish_action(state=status, switch=name, action=action,
                                     target=", ".join(sent),
                                     error=note[:300] if note else None)
                LOG.info("Aqara %s/%s delivered=%d skipped=%d "
                         "(Z2M physical + HA-only virtual LAB)",
                         name, action, len(sent), len(skipped))
            except Exception as exc:
                LOG.exception("Aqara MQTT light action failed")
                self._publish_action(state="error", switch=name, action=action,
                                     target=", ".join(targets), error=str(exc)[:300])
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
                self.globals = global_policy(self.options.read())
                self._light_shadows.clear()
                self._lab_shadows.clear()
                self._light_observed_at.clear()
                self._light_probe_at.clear()
                self._sync_light_topics()
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
        LOG.info("Starting Aqara MQTT input, Mode Keeper and direct MQTT lights %s", self.version)
        threading.Thread(target=self._run_actions, daemon=True,
                         name="dh-aqara-action-worker").start()
        threading.Thread(target=run_keeper, args=(self,), daemon=True,
                         name="dh-aqara-mode-keeper").start()
        threading.Thread(target=self._run_light_probes, daemon=True,
                         name="dh-aqara-light-state-probes").start()
        self.client.connect(host, port, keepalive=60)
        self.client.loop_forever(retry_first_connection=True)
