"""MQTT runtime: Aqara button input, selective Mode Keeper and Z2M light output.

No unverified relay writes or individual blind toggles; six LAB lights use HA REST.
"""
from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import queue
import re
import threading
import time

from . import cover_rules, climate_rules, media_rules, profiles
from .catalog import (CatalogError, candidate_from_mqtt, decode_bridge_devices,
                      resolve_hardware, has_event_actions, has_device_power)
from .actions import ActionError
from .event_log import EventLog
from .control import HAClient, light_commands, verified_adopted_switch
from .mqtt_lights import plan_batch
from .lab_lights import (LAB_LIGHTS, authorized_ha_light_ids,
                         partition_commands, plan_lab)
from .light_routes import current_route, group_observed_state
from .keeper_runtime import run_keeper
from .mode_keeper import (capabilities, global_policy, maintained_switch,
                          mode_action_allowed, desired_mode, held_relay, action_channels)
from .configuration import parse_configuration
from .ha_registry import HARegistryClient
from .mqtt_ui import (
    AVAILABILITY, DISCOVERY_TOPIC, ROOT, SCAN_REQUEST, SYNC_TOPIC,
    sync_payload, wire_payload,
)
from .scan import scan_once
from .operation_ui import AppCard, ReleaseChecker
from .supervisor import SupervisorOptions
from .telemetry import ContractDataError, TelemetryClient, TelemetryRunner

LOG = logging.getLogger(__name__)
_IEEE = re.compile(r"^0x[0-9a-f]{16}$")
_BASE_FORBIDDEN = {"homeassistant", "DigitalHouses", "$SYS"}
_FILTERS = tuple(
    "/".join(["+"] * levels) + "/bridge/" + suffix
    for levels in (1, 2, 3) for suffix in ("info", "devices", "state", "groups")
)


def bridge_path(topic: str) -> tuple[str, str] | None:
    base, sep, suffix = topic.rpartition("/bridge/")
    if not sep or suffix not in ("info", "devices", "state", "groups"):
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
            "groups": info.get("groups"),
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
        self.auto_scan_interval = options_snapshot.get("auto_scan_interval", 60)
        # Staged migration: existing lighting controls continue with the new
        # HAOS telemetry switch unset/false. No identity or network request
        # is created without explicit opt-in.
        self.telemetry = None
        self.telemetry_runner = None
        if options_snapshot.get("telemetry_enabled") is True:
            try:
                self.telemetry = TelemetryClient(enabled=True, version=self.version)
                self.telemetry_runner = TelemetryRunner(self.telemetry)
            except (ContractDataError, OSError, ValueError) as exc:
                # A failed telemetry identity must never interrupt light
                # control or be silently replaced with a fresh identifier.
                LOG.error(
                    "Aqara telemetry unavailable (persistent state error): %s; "
                    "lighting remains operational; saved identity preserved", exc
                )
                self.telemetry = None
                self.telemetry_runner = None
        self._previous = _load_previous(last_scan_path)
        self._previous_path = last_scan_path
        self._stop = threading.Event()
        self._ha_client = ha_client
        self._jobs = queue.Queue(maxsize=64)
        self.event_log = EventLog()
        self._last_action = {"state": "idle", "at": None, "switch": None,
                             "action": None, "target": None, "error": None}
        self._last_action_at = {}
        self._last_mode_request = {}
        self._mode_pending = {}
        self._mode_probes = {}
        self._fresh_fields = set()
        self._light_availability = {}
        self._input_availability = {}
        self._last_details_payload = None
        self._last_problems_payload = None
        self._target_registries = None
        self._temperature_unit = None
        self._home_profile = None
        self._last_refresh = None
        self._light_shadows = {}
        self._ha_shadows = {}
        self._ha_registry_snapshot = None
        self._ha_registry_checked_at = -1e9
        self._light_observed_at = {}
        self._light_probe_at = {}
        self._mutex = threading.RLock()
        self._scan_lock = threading.Lock()
        self.target_catalog = {}
        self.device_details = []
        self._networks: dict[str, dict] = {}
        self._subscribed: set[str] = set()
        self._scan = {"state": "idle", "started_at": None,
                      "finished_at": None, "duration_seconds": None, "error": None}
        self._card = AppCard(lambda payload: self._publish(ROOT + "/card", payload))
        self._release = ReleaseChecker(self.version)
        self._refresh_state = {"state":"idle","started_at":None,"finished_at":None,
                               "duration_seconds":None,"error":None}
        if hasattr(mqtt_module, "CallbackAPIVersion"):
            self.client = mqtt_module.Client(
                mqtt_module.CallbackAPIVersion.VERSION1,
                client_id="dh-electrica-app",
            )
        else:
            self.client = mqtt_module.Client(client_id="dh-electrica-app")
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
        self._publish_details(force=True)
        self._publish(ROOT + "/last_action", dict(self._last_action))
        self._publish_card()
        self._publish_release()
        self._publish(ROOT + "/refresh_state", self._refresh_state)
        self._publish(ROOT + "/last_refresh", self._last_refresh or "unknown")

    def _publish_action(self, *, state, switch, action, target, error=None):
        self._last_action = {"state": state, "at": _iso_now(),
                             "switch": switch, "action": action,
                             "target": target, "error": error}
        self._publish(ROOT + "/last_action", dict(self._last_action))

    def _publish_card(self):
        self._card.publish()

    def _publish_details(self, force=False):
        """Publish device identity/fingerprint problems without relay writes."""
        with self._mutex:
            config = deepcopy(self.config)
            networks = verified_snapshots(self._networks)
            bridge_states = {base: net.get("bridge_state") for base,net in self._networks.items()}
            availability = dict(self._input_availability)
            target_catalog = deepcopy(self.target_catalog)
            routes = dict(config.get("light_routes", {}))
            light_availability = dict(self._light_availability)
            fresh = set(self._fresh_fields)
        problems = list(config.get("binding_problems", []))
        observed_targets = {}
        for room in config["rooms"]:
            for switch in room["switches"]:
                peers = []
                unverified = []
                verified_power = False
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
                            if (candidate["ieee"] == switch["ieee"] and
                                    candidate["base_topic"] == switch["base_topic"] and
                                    has_device_power(device)):
                                verified_power = True
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
                                         (None, desired_mode(switch["keep_mode"][key])) or
                                         (held_relay(switch["keep_mode"][key]) and
                                          current.get(MODE_TO_RELAY[key][1]) not in
                                          (None, held_relay(switch["keep_mode"][key])))]
                        if mismatches:
                            result = {"status":"keep_mode_mismatch",
                                      "reason":"Protected keys drifted: " + ", ".join(mismatches)}
                bridge_status = bridge_states.get(switch["base_topic"])
                input_status = availability.get((switch["base_topic"], switch["logical_name"]), "unknown")
                if result["status"] == "same" and (bridge_status == "offline" or input_status == "offline"):
                    result = {"status":"offline","reason":"Zigbee2MQTT or input reports offline"}
                elif result["status"] == "missing" and not any(
                        n["coordinator_ieee"] == switch["coordinator_ieee"] for n in networks):
                    result = {"status":"offline" if bridge_status == "offline" else "unknown",
                              "reason":"No current inventory for this coordinator"}
                if switch.get("power_meter"):
                    ident = (switch["base_topic"], switch["logical_name"])
                    reading = next((n["states"].get(ident[1],{}).get("power")
                                    for n in networks
                                    if n["base_topic"] == ident[0]
                                    and n["coordinator_ieee"] == switch["coordinator_ieee"]), None)
                    verified = resolve_hardware(switch, peers)["status"] == "same"
                    switch["power_w"] = (reading if verified and verified_power and
                        bridge_status == "online" and input_status != "offline" and
                        (*ident, "power") in fresh and type(reading) in (int,float) and
                        math.isfinite(reading) else None)
                result["availability"] = input_status
                switch["runtime"] = result
                # The public tree shows the saved choices, including disabled
                # or invalid actions; the execution tree remains fail-closed.
                effective = switch.get("bindings", {})
                switch["bindings"] = switch.get("configured_bindings",effective)
                for action, rule in switch["bindings"].items():
                    rule["enabled"] = action in effective and switch.get("enabled",False)
                    for eid in rule.get("targets",[]):
                        target = target_catalog.get(eid, {})
                        state = target.get("state", "unknown")
                        route = routes.get(eid)
                        if route:
                            ident = (route["base_topic"],route["friendly_name"])
                            if bridge_states.get(ident[0]) != "online" or light_availability.get(ident) != "online":
                                state = "unavailable" if bridge_states.get(ident[0]) == "offline" or light_availability.get(ident) == "offline" else "unknown"
                            elif route.get("kind")=="group":
                                live=next((n for n in networks if n["base_topic"]==ident[0]),{})
                                reported=group_observed_state(route,live,fresh)
                                state=reported.lower() if reported else "unknown"
                            elif (*ident,"state") in fresh:
                                reported = next((n["states"].get(ident[1],{}).get("state")
                                                 for n in networks if n["base_topic"]==ident[0]),None)
                                state = reported.lower() if reported in ("ON","OFF") else "unknown"
                        observed_targets[eid] = state
                        if state in (None,"unknown","unavailable",""):
                            problems.append({"object_name":eid,"category":"target_unavailable",
                                             "reason":"Target not found" if not target and not route else state})
                if result["status"] not in ("same", "disabled"):
                    problems.append({
                        "object_name": switch["logical_name"],
                        "category": result["status"],
                        "reason": result.get("reason"),
                    })
        from .light_rules import parse_rule
        orphan_devices = []
        for row in config.get("orphan_bindings",[]):
            bindings = {k:parse_rule(v) for k,v in row["actions"].items()}
            for rule in bindings.values():
                rule["enabled"] = False
                for eid in rule["targets"]:
                    observed_targets[eid] = target_catalog.get(eid,{}).get("state","unknown")
            orphan_devices.append({"entity_id":row["entity_id"],"logical_name":row["entity_id"],
                "base_topic":"—","fingerprint":{"model":"—","actions":[]},"settings":{},
                "bindings":bindings,"runtime":{"status":"missing","reason":"Not adopted"}})
        if orphan_devices:
            config["rooms"].append({"area_id":None,"name":"Не обнаружены","switches":orphan_devices})
        details = {"state":"ready","rooms":config["rooms"],"target_states":observed_targets}
        # Deduplicate diagnostics and avoid a 15-second Recorder event when
        # nothing changed. MQTT/HA reconnect republish is explicit.
        problems = list({(x["object_name"],x["category"],x.get("reason")):x for x in problems}.values())
        diagnostic = {"state":"ready","active":problems[:100],"count":len(problems)}
        with self._mutex:
            self.device_details = deepcopy(config["rooms"])
            if force or details != self._last_details_payload:
                if self._publish(ROOT + "/devices",details):
                    self._last_details_payload = details
            if force or diagnostic != self._last_problems_payload:
                if self._publish(ROOT + "/problems",diagnostic):
                    self._last_problems_payload = diagnostic

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
            self._input_availability.clear()
            self._light_shadows.clear()
            self._ha_shadows.clear()
            self._light_observed_at.clear()
            self._light_probe_at.clear()
            self._home_profile = None
        for topic in (*_FILTERS, SCAN_REQUEST, ROOT + "/command/refresh",
                      ROOT + "/command/check_updates", ROOT + "/command/delete_telemetry", "homeassistant/status", profiles.TOPIC):
            self._subscribe(topic)
        self._publish(AVAILABILITY, "online")
        self._publish(SYNC_TOPIC, sync_payload(self.version))
        self._publish_all()

    def _on_disconnect(self, client, userdata, rc):
        self.event_log.disconnect()
        del client, userdata
        if rc:
            LOG.warning("MQTT disconnected: %s", rc)
        with self._mutex:
            self._subscribed.clear()
            self._networks.clear()
            self._fresh_fields.clear()
            self._light_availability.clear()
            self._input_availability.clear()
            self._light_shadows.clear()
            self._ha_shadows.clear()
            self._light_observed_at.clear()
            self._light_probe_at.clear()
            self._home_profile = None

    def _on_message(self, client, userdata, message):
        del client, userdata
        if message.topic == profiles.TOPIC:
            from .binding_store import decode_json
            try:
                raw=bytes(message.payload)
                if len(raw)>4096:
                    raise CatalogError("Global profile snapshot too large")
                snapshot=profiles.validate_snapshot(decode_json(raw))
            except (CatalogError,ValueError,TypeError,KeyError):
                snapshot=None
            with self._mutex:
                self._home_profile=snapshot
            return
        if message.topic == ROOT + "/command/delete_telemetry":
            if (self.telemetry is not None and not message.retain
                    and bytes(message.payload) == b"DELETE"):
                threading.Thread(target=self._delete_telemetry, daemon=True,
                                 name="dh-electrica-telemetry-delete").start()
            return
        if message.topic in (ROOT + "/command/refresh", ROOT + "/command/check_updates"):
            operation = "refresh" if message.topic.endswith("/refresh") else "check"
            expected = b"REFRESH" if operation == "refresh" else b"CHECK"
            if not message.retain and bytes(message.payload) == expected:
                self.request_operation(operation)
            return
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
                for base, net in self._networks.items():
                    if not message.topic.startswith(base+"/"):
                        continue
                    name = message.topic[len(base)+1:-len("/availability")]
                    try:
                        inventory = decode_bridge_devices(net["devices"])
                        if not any(d.get("friendly_name")==name and
                                   has_event_actions(d)
                                   for d in inventory):
                            continue
                        raw = bytes(message.payload).decode().strip()
                        value = json.loads(raw).get("state","unknown") if raw.startswith("{") else raw
                        self._input_availability[(base,name)] = value if value in ("online","offline") else "unknown"
                        if value != "online":
                            self._fresh_fields.difference_update(
                                {field for field in self._fresh_fields if field[:2] == (base,name)})
                    except (KeyError,CatalogError,ValueError,TypeError,UnicodeError):
                        self._input_availability[(base,name)] = "unknown"
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
                        self._fresh_fields.difference_update(
                            {field for field in self._fresh_fields if field[0] == base})
                        for route in self.config.get("light_routes", {}).values():
                            if route["base_topic"] == base:
                                ident = (base, route["friendly_name"])
                                self._light_availability.pop(ident, None)
                                self._light_shadows.pop(ident, None)
                                self._fresh_fields.discard((base, ident[1], "state"))
                    return
                if suffix=="groups":
                    if node.get("groups")!=bytes(message.payload):
                        updated={**node,"groups":bytes(message.payload)}
                        for route in self.config.get("light_routes",{}).values():
                            if (route.get("kind")=="group" and route["base_topic"]==base
                                    and not current_route(route,updated)):
                                ident=(base,route["friendly_name"])
                                self._fresh_fields.discard((*ident,"state"))
                                self._light_shadows.pop(ident,None)
                                self._light_observed_at.pop(ident,None)
                                node["states"].pop(ident[1],None)
                                self.event_log.invalidate(("z2m",*ident))
                    node[suffix]=bytes(message.payload)
                    self._sync_light_topics()
                else:
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
                            if has_event_actions(device):
                                self._subscribe(base + "/" + name + "/availability")
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
                        # Never interpret group data as an input action.
                        group=next((r for r in self.config.get("light_routes",{}).values()
                                    if r.get("kind")=="group" and r["base_topic"]==base
                                    and r["friendly_name"]==name and current_route(r,net)),None)
                        if group is None:
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
                            if not getattr(message, "dup", False):
                                self.event_log.observe(("z2m", *ident), data["state"])
                            shadow = self._light_shadows.get(ident)
                            if shadow and shadow["value"] == data["state"]:
                                self._light_shadows.pop(ident, None)
                    if device is not None and not getattr(message, "retain", False) and not getattr(message, "dup", False):
                        self._process_adopted_event(base, net, device, data)
                except (KeyError, CatalogError, ValueError, UnicodeDecodeError, TypeError) as exc:
                    LOG.warning("Invalid Z2M state %s: %s", message.topic, exc)
                break

    def _input_mode_allowed(self, sw, action, net, device, maintenance):
        """Use the same observed-mode gate before queueing and dispatch."""
        base, name = sw["base_topic"], sw["logical_name"]
        if (net.get("bridge_state") == "offline" or
                self._input_availability.get((base,name)) == "offline"):
            return False
        features = capabilities(device)
        if not mode_action_allowed(sw, action, net.get("states", {}).get(name, {}),
                                   features, maintenance):
            return False
        return all((base, name, field) in self._fresh_fields
                   for key in action_channels(action, features) if key in features
                   for field in (features[key] if held_relay(sw.get("keep_mode",{}).get(key))
                                 else (features[key][0],)))

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
                if not verified_adopted_switch(saved, device, coordinator, base):
                    continue
                name = saved["logical_name"]
                # Old generic baseline restoration is intentionally disabled.
                # Only keys explicitly present in user keep_mode are repaired.
                now = time.monotonic()
                action = data.get("action")
                if not isinstance(action, str) or not action:
                    continue
                if not saved.get("enabled", True):
                    if action in saved.get("fingerprint", {}).get("actions", []):
                        rid = self.event_log.press(base,name,action)
                        self.event_log.finish(rid,"Устройство отключено")
                    continue
                maintenance = maintained_switch(saved, self.globals)
                if not self._input_mode_allowed(saved, action, net, device, maintenance):
                    if action in saved.get("fingerprint", {}).get("actions", []):
                        rid = self.event_log.press(base,name,action)
                        self.event_log.finish(rid,"Maintenance / режим клавиши не подтверждён или не разрешён")
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
                    if action in saved.get("fingerprint", {}).get("actions", []):
                        rid = self.event_log.press(base,name,action)
                        self.event_log.finish(rid,"Нет активной привязки")
                    continue
                targets = [eid for command in commands for eid in command["target"]["entity_id"]]
                target_label = ", ".join(targets)
                rid = self.event_log.press(base,name,action,targets)
                try:
                    self._jobs.put_nowait((base, coordinator, name, action, commands, rid))
                    self._publish_action(state="queued", switch=name, action=action,
                                         target=target_label)
                except queue.Full:
                    self.event_log.finish(rid,"Очередь заполнена",targets)
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

    def _ha_native_targets(self, requested: set[str]) -> set[str]:
        """Registry-verifiable HA-native light candidates with bounded caching.

        An inaccessible registry never grants the HA fallback path.
        Zigbee2MQTT devices remain MQTT-only, even when offline/unmapped.
        """
        if not requested:
            return set()
        now = time.monotonic()
        if now - self._ha_registry_checked_at >= 60:
            try:
                entities = self.registry.fetch_entities()
                if not isinstance(entities, list):
                    raise ValueError("HA entity registry is not a list")
                self._ha_registry_snapshot = entities
            except Exception as exc:
                self._ha_registry_snapshot = None
                LOG.warning("HA-native light registry unavailable: %s", exc)
            self._ha_registry_checked_at = now
        return authorized_ha_light_ids(self._ha_registry_snapshot, requested)

    def observed_target_state(self, eid, *, verify_route=False):
        """Read cached observed state under _mutex; no new HA/Z2M I/O."""
        route = self.config.get("light_routes", {}).get(eid)
        if not route:
            return self.target_catalog.get(eid, {}).get("state", "unknown")
        base, name = route["base_topic"], route["friendly_name"]
        net = self._networks.get(base, {})
        if (net.get("bridge_state") != "online" or
                self._light_availability.get((base,name)) != "online" or
                (verify_route and not current_route(route, net))):
            return "unavailable"
        if route.get("kind") == "group":
            value = group_observed_state(route, net, self._fresh_fields)
        elif (base,name,"state") in self._fresh_fields:
            value = net.get("states", {}).get(name, {}).get("state")
        else:
            value = None
        return value.lower() if value in ("ON","OFF") else "unknown"

    def _test_light_allowed(self, eid):
        return (not self._stop.is_set() and not self.globals["maintenance_mode"]
                and isinstance(eid, str) and re.fullmatch(r"light\.[a-z0-9_]+", eid)
                and eid in self.target_catalog
                and self.observed_target_state(eid, verify_route=True) in ("on","off"))

    def request_light_test(self, eid):
        """Queue exactly one engineer-requested light toggle, not a fake press."""
        with self._mutex:
            if not self._test_light_allowed(eid):
                raise CatalogError("Светильник недоступен или Maintenance активен")
            if self.event_log.active_target(eid):
                raise CatalogError("Ожидается результат предыдущей команды")
            rid = self.event_log.press("ingress", "Инженер", "TEST", [eid])
            try:
                self._jobs.put_nowait((None, None, "Инженер", "TEST",
                    [{"service":"light.toggle","target":{"entity_id":[eid]}}], rid))
            except queue.Full as exc:
                self.event_log.finish(rid, "Очередь заполнена", [eid])
                raise CatalogError("Очередь заполнена") from exc
            return rid

    def _ha_domain_commands(self, commands, base, coordinator, name, action, all_commands, rid):
        """Shared serialized HA dispatch for cover, climate and media players."""
        from collections import Counter
        sent, skipped = [], []
        try:
            entities = self.registry.fetch_entities()
            counts = Counter(e.get("entity_id") for e in entities)
            approved = {e["entity_id"] for e in entities if e.get("disabled_by") is None
                        and counts[e.get("entity_id")]==1}
        except Exception:
            approved = set()
        if self._ha_client is None:
            self._ha_client = HAClient(os.environ.get("SUPERVISOR_TOKEN", ""))
        for call in commands:
            for eid in call["target"]["entity_id"]:
                try:
                    if eid not in approved:
                        raise ActionError("Target not verified in HA registry")
                    is_cover = eid.startswith("cover.")
                    rules = cover_rules if is_cover else media_rules if eid.startswith("media_player.") else climate_rules
                    operation = next(op for op,service in rules.SERVICES.items()
                                     if service==call["service"])
                    if is_cover:
                        with self._mutex:
                            guard_ids = cover_rules.guard_ids(self.config,eid)
                        state = self._ha_client.read_cover_or_window(eid)
                        guards = {}
                        if operation!="stop":
                            for sensor in guard_ids:
                                if sensor not in approved:
                                    raise ActionError("Window guard missing: "+sensor)
                                guards[sensor] = self._ha_client.read_cover_or_window(sensor)
                        op,data,desired = rules.plan(operation,call.get("data",{}),state,guards)
                    elif rules is media_rules:
                        state = self._ha_client.read_domain_state(eid)
                        op,data,desired = rules.plan(operation,call.get("data",{}),state)
                    else:
                        unit = self.registry.fetch_temperature_unit() if operation=="temperature" else None
                        state = self._ha_client.read_domain_state(eid)
                        op,data,desired = rules.plan(operation,call.get("data",{}),state,unit)
                    with self._mutex:
                        sw = next((x for room in self.config["rooms"] for x in room["switches"]
                                   if x["logical_name"]==name and x["base_topic"]==base
                                   and x["coordinator_ieee"]==coordinator),None)
                        net=self._networks.get(base,{})
                        device=next((d for d in decode_bridge_devices(net["devices"])
                                     if d.get("friendly_name")==name),None)
                        if (not sw or not device or not sw.get("enabled",False)
                                or maintained_switch(sw,self.globals)
                                or light_commands(sw,action)!=all_commands
                                or not verified_adopted_switch(sw,device,coordinator,base)
                                or not self._input_mode_allowed(sw,action,net,device,False)
                                or (is_cover and cover_rules.guard_ids(self.config,eid)!=guard_ids)):
                            raise ActionError("Input, binding or guard changed")
                    dispatched_at=_iso_now()
                    if is_cover:
                        self._ha_client.execute_cover(eid,op,data)
                    elif rules is media_rules:
                        self._ha_client.execute_media(eid,op,data)
                    else:
                        self._ha_client.execute_climate(eid,op,data)
                    self.event_log.sent_ha_domain(rid,eid,state,desired,dispatched_at,operation=op)
                    sent.append(eid)
                except Exception as exc:
                    skipped.append({"light":eid,"reason":str(exc)[:160]})
        return sent, skipped

    def _run_actions(self):
        """Dispatch verified Z2M lights via MQTT and HA-native lights via REST."""
        while not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=1)
                base, coordinator, name, action, commands = job[:5]
                rid = job[5] if len(job)>5 else None
            except queue.Empty:
                continue
            targets = [eid for cmd in commands for eid in cmd["target"]["entity_id"]]
            try:
                all_commands = commands
                with self._mutex:
                    commands,profile_skipped,unresolved_toggles=profiles.resolve_commands(commands,self.target_catalog,self._home_profile)
                profile_lights={eid for c in all_commands if c["service"].startswith("light.")
                                and "profile" in c.get("data",{}) for eid in c["target"]["entity_id"]}
                is_test = base is None and action == "TEST"
                switch_commands = [c for c in commands if c["service"].startswith("switch.")]
                domain_commands = [c for c in commands if c["service"].startswith(("cover.","climate.","media_player."))]
                commands = [c for c in commands if c["service"].startswith("light.")]
                # A missing route is NOT permission for HA fallback.
                # HA registry platform must positively identify a native light.
                with self._mutex:
                    routes = dict(self.config.get("light_routes", {}))
                candidates = {eid for eid in targets if eid.startswith("light.")} - set(routes) - LAB_LIGHTS
                if is_test:
                    self._ha_registry_checked_at = -1e9
                ha_approved = self._ha_native_targets(candidates)
                # Read HA states outside the MQTT lock, before ANY Z2M publish.
                z2m_commands, lab_commands = partition_commands(
                    commands, routes, ha_approved)
                mixed_toggle = bool(
                    z2m_commands and lab_commands
                    and any(cmd["service"] == "light.toggle" for cmd in z2m_commands)
                    and any(cmd["service"] == "light.toggle" for cmd in lab_commands))
                original_z2m, original_lab = z2m_commands, lab_commands
                lab_state_cache = {}
                def read_lab_once(entity):
                    if entity not in lab_state_cache:
                        try:
                            lab_state_cache[entity] = (
                                True, (self._ha_client.read_lab_state(entity)
                                       if entity in LAB_LIGHTS else
                                       self._ha_client.read_light_state(entity)))
                        except Exception as exc:
                            lab_state_cache[entity] = (False, exc)
                    ok, result = lab_state_cache[entity]
                    if not ok:
                        raise result
                    return result
                lab_preview = []
                if mixed_toggle:
                    if self._ha_client is None:
                        self._ha_client = HAClient(os.environ.get("SUPERVISOR_TOKEN", ""))
                    lab_preview, _ = plan_lab(
                        [c for c in lab_commands if c["service"] == "light.toggle"],
                        read_lab_once, self._ha_shadows,
                        time.monotonic(), allowed_lights=ha_approved)

                with self._mutex:
                    if is_test:
                        if (len(targets) != 1 or not self._test_light_allowed(targets[0])
                                or self.event_log.active_target(targets[0], exclude=rid)):
                            raise ActionError("Test target unavailable or command pending")
                    else:
                        sw = next((x for room in self.config["rooms"]
                                   for x in room["switches"]
                                   if (x["logical_name"] == name and
                                       x["base_topic"] == base and
                                       x["coordinator_ieee"] == coordinator)), None)
                        if (sw is None or not sw.get("enabled", False) or
                                maintained_switch(sw, self.globals)):
                            raise ActionError("Disabled switch or Maintenance active")
                        if light_commands(sw, action) != all_commands:
                            raise ActionError("Binding changed while command was queued")
                        net = self._networks.get(base, {})
                        raw = net.get("devices")
                        if not isinstance(raw, bytes):
                            raise ActionError("Zigbee2MQTT input inventory unavailable")
                        device = next((d for d in decode_bridge_devices(raw)
                                       if d.get("friendly_name") == name), None)
                        if (device is None or not verified_adopted_switch(
                                sw, device, coordinator, base) or not self._input_mode_allowed(
                                sw, action, net, device, False)):
                            raise ActionError("Aqara key not verified in decoupled operating mode")
                    # Repartition after a possible Scan; no guessed light routes.
                    z2m_commands, lab_commands = partition_commands(
                        commands, self.config.get("light_routes", {}),
                        ha_approved)
                    if (any(cmd["service"] == "light.toggle" for cmd in commands)
                            and (z2m_commands != original_z2m
                                 or lab_commands != original_lab)):
                        raise ActionError("Light routes changed during toggle; retry")
                    toggle_override = None
                    if mixed_toggle:
                        z2m_preview, _ = plan_batch(
                            [c for c in z2m_commands if c["service"] == "light.toggle"],
                            self.config.get("light_routes", {}),
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
                    if is_test:
                        test_route = self.config.get("light_routes", {}).get(targets[0])
                        if test_route and (test_route["base_topic"],test_route["friendly_name"]) in self._light_shadows:
                            raise ActionError("Previous Zigbee command not yet observed")
                    plans, skipped = plan_batch(
                        z2m_commands, self.config.get("light_routes", {}),
                        self._networks, self._light_availability,
                        self._fresh_fields, self._light_shadows,
                        self._light_observed_at, time.monotonic(),
                        toggle_state_override=toggle_override)
                    skipped.extend(profile_skipped)
                    sent = []
                    for plan in plans:
                        if plan["state"]=="ON" and plan["light"] in unresolved_toggles:
                            skipped.append({"light":plan["light"],"reason":unresolved_toggles[plan["light"]]})
                            continue
                        if self._publish(plan["topic"], plan["payload"],
                                         retain=False):
                            ident = plan["ident"]
                            route=self.config.get("light_routes",{}).get(plan["light"],{})
                            net=self._networks.get(ident[0],{})
                            previous = (group_observed_state(route,net,self._fresh_fields)
                                        if route.get("kind")=="group" else net.get("states",{}).get(ident[1],{}).get("state"))
                            self.event_log.sent(rid,plan["light"],("z2m",*ident),previous,plan["state"],
                                accepted_only=plan["light"] in profile_lights and plan["state"]=="ON")
                            self._light_shadows[ident] = {
                                "value": plan["state"], "at": time.monotonic()}
                            sent.append(plan["light"])
                        else:
                            skipped.append({"light":plan["light"],
                                            "reason":"MQTT publish rejected"})
                # HA-native entities and six LAB lamps use HA REST only.
                # Do not hold the MQTT lock during network requests.
                if lab_commands:
                    if self._ha_client is None:
                        self._ha_client = HAClient(os.environ.get("SUPERVISOR_TOKEN", ""))
                    lab_plans, lab_skipped = plan_lab(
                        lab_commands,
                        read_lab_once, {} if is_test else self._ha_shadows, time.monotonic(),
                        toggle_state_override=toggle_override,
                        allowed_lights=ha_approved)
                    skipped.extend(lab_skipped)
                    for call in lab_plans:
                        ids = call["target"]["entity_id"]
                        if call["service"]=="light.turn_on":
                            for eid in ids:
                                if eid in unresolved_toggles:
                                    skipped.append({"light":eid,"reason":unresolved_toggles[eid]})
                            ids=[eid for eid in ids if eid not in unresolved_toggles]
                            if not ids:continue
                            call={**call,"target":{"entity_id":ids}}
                        with self._mutex:
                            if is_test:
                                authorized = (len(ids) == 1 and self._test_light_allowed(ids[0])
                                              and ids[0] not in self.config.get("light_routes", {})
                                              and not self.event_log.active_target(ids[0], exclude=rid))
                            else:
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
                                    and light_commands(current_sw, action) == all_commands
                                    and not maintained_switch(current_sw, self.globals)
                                    and verified_adopted_switch(
                                        current_sw, device, coordinator, base)
                                    and self._input_mode_allowed(
                                        current_sw, action, net, device, False))
                        if not authorized:
                            skipped.extend({"light":eid,
                                            "reason":"Test target changed or unavailable" if is_test else "Aqara key or Maintenance changed"}
                                           for eid in ids)
                            continue
                        dispatched_at = _iso_now()
                        try:
                            self._ha_client.execute(call)
                        except Exception as exc:
                            LOG.warning("Aqara HA-native light call failed: %s", exc)
                            skipped.extend({"light":eid,
                                            "reason":"HA light service call failed"}
                                           for eid in ids)
                            continue
                        value = "on" if call["service"] == "light.turn_on" else "off"
                        with self._mutex:
                            for eid in ids:
                                self.event_log.sent(rid,eid,("ha",eid),lab_state_cache.get(eid,(False,None))[1] if lab_state_cache.get(eid,(False,None))[0] else None,value, sent_at=dispatched_at,
                                    accepted_only=eid in profile_lights and value=="on")
                                self._ha_shadows[eid] = {
                                    "state":value, "at": time.monotonic()}
                        sent.extend(ids)
                if switch_commands:
                    from .ingress_catalog import safe_switch_targets
                    try:
                        approved = safe_switch_targets(self.registry.fetch(), self.config)
                    except Exception:
                        approved = set()
                    if self._ha_client is None:
                        self._ha_client = HAClient(os.environ.get("SUPERVISOR_TOKEN", ""))
                    pending_switches = []
                    for call in switch_commands:
                        for eid in call["target"]["entity_id"]:
                            try:
                                if eid not in approved:
                                    raise ActionError("Switch not verified or is an Aqara input relay")
                                state = self._ha_client.read_switch_state(eid)
                                if state not in ("on", "off"):
                                    raise ActionError("Switch unavailable")
                                pending_switches.append((eid, call["service"], state))
                            except Exception as exc:
                                skipped.append({"light":eid,"reason":str(exc)[:120]})
                    switch_toggle = "on" if any(c == "switch.toggle" and st == "off"
                                                 for _, c, st in pending_switches) else "off"
                    for eid, service, state in pending_switches:
                        try:
                            with self._mutex:
                                sw = next((x for room in self.config["rooms"] for x in room["switches"]
                                           if x["logical_name"] == name and x["base_topic"] == base
                                           and x["coordinator_ieee"] == coordinator), None)
                                net = self._networks.get(base, {})
                                device = next((d for d in decode_bridge_devices(net["devices"])
                                               if d.get("friendly_name") == name), None)
                                if (not sw or not device or not sw.get("enabled", False)
                                    or maintained_switch(sw, self.globals)
                                    or light_commands(sw, action) != all_commands
                                    or not verified_adopted_switch(sw, device, coordinator, base)
                                    or not self._input_mode_allowed(sw, action, net, device, False)):
                                    raise ActionError("Input or binding changed")
                            desired = switch_toggle if service == "switch.toggle" else service.rsplit("_", 1)[-1]
                            dispatched_at = _iso_now()
                            self._ha_client.execute_switch(eid, desired)
                            self.event_log.sent(rid,eid,("ha",eid),state,desired,sent_at=dispatched_at)
                            sent.append(eid)
                        except Exception as exc:
                            skipped.append({"light":eid,"reason":str(exc)[:120]})
                if domain_commands:
                    domain_sent, domain_skipped = self._ha_domain_commands(
                        domain_commands,base,coordinator,name,action,all_commands,rid)
                    sent.extend(domain_sent)
                    skipped.extend(domain_skipped)
                for item in skipped:
                    self.event_log.skip(rid,item["light"],item["reason"])
                self.event_log.finish(rid)
                if skipped:
                    LOG.warning("Aqara action %s %s skipped: %s", name, action, skipped)
                note = "; ".join(x["light"]+": "+x["reason"] for x in skipped)
                status = ("partial" if sent and skipped else
                          "sent" if sent else "skipped")
                self._publish_action(state=status, switch=name, action=action,
                                     target=", ".join(sent),
                                     error=note[:300] if note else None)
                LOG.info("Aqara %s/%s delivered=%d skipped=%d "
                         "(Z2M physical + authorized HA lights)",
                         name, action, len(sent), len(skipped))
            except Exception as exc:
                self.event_log.finish(rid,str(exc),targets)
                LOG.exception("Aqara MQTT light action failed")
                self._publish_action(state="error", switch=name, action=action,
                                     target=", ".join(targets), error=str(exc)[:300])
            finally:
                self._jobs.task_done()

    def request_scan(self, foreground=True) -> bool:
        if not self._scan_lock.acquire(blocking=False):
            return False
        threading.Thread(target=self._run_scan, args=(foreground,), daemon=True,
                         name="dh-electrica-manual-scan").start()
        return True

    def _run_scan(self, foreground=True) -> None:
        start = time.monotonic()
        now = _iso_now()
        with self._mutex:
            snapshots = verified_snapshots(self._networks)
        self._scan = {"state": "updating", "started_at": now,
                      "finished_at": None, "duration_seconds": None, "error": None}
        self._publish(ROOT + "/scan_state", self._scan)
        try:
            if not snapshots:
                raise CatalogError("No confirmed Zigbee2MQTT network snapshot available")
            merged, report = scan_once(snapshots, self.options, self.registry)
            _save_previous(self._previous_path, report)
            with self._mutex:
                routes_changed = self.config.get("light_routes",{}) != merged.get("light_routes",{})
                self.config = merged
                self.globals = global_policy(self.options.read())
                if routes_changed:
                    self._light_shadows.clear()
                    self._ha_shadows.clear()
                    self._light_observed_at.clear()
                    self._light_probe_at.clear()
                self._ha_registry_snapshot = None
                self._ha_registry_checked_at = -1e9
                self._sync_light_topics()
                self._previous = report
            try:
                self.refresh_targets()
            except Exception:
                LOG.warning("HA target catalog refresh after scan failed")
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
            self._publish(ROOT + "/scan_state", self._scan)
            self._scan_lock.release()

    def _publish_release(self):
        data = self._release.payload()
        self._publish(ROOT + "/latest_version", data["latest_version"])
        self._publish(ROOT + "/update_available",
                      "unknown" if data["available"] is None else "ON" if data["available"] else "OFF")
        self._publish(ROOT + "/release_check", data)

    def request_operation(self, operation):
        if not self._card.begin(operation):
            return False
        threading.Thread(target=self._run_operation, args=(operation,), daemon=True).start()
        return True

    def _run_operation(self, operation):
        error = None
        start = time.monotonic()
        started = _iso_now()
        if operation == "refresh":
            self._refresh_state = {"state":"updating","started_at":started,
                                   "finished_at":None,"duration_seconds":None,"error":None}
            self._publish(ROOT + "/refresh_state", self._refresh_state)
        try:
            if operation == "refresh":
                self.refresh_targets()
                with self._mutex:
                    if not verified_snapshots(self._networks):
                        raise CatalogError("No verified Z2M inventory")
            else:
                if not self._release.begin():
                    raise CatalogError("Release check already in progress")
                _, error = self._release.complete()
                self._publish_release()
        except Exception as exc:
            error = str(exc)[:250]
        finally:
            duration = round(time.monotonic()-start,3)
            if operation == "refresh":
                self._refresh_state = {"state":"error" if error else "idle","started_at":started,
                                       "finished_at":_iso_now(),"duration_seconds":duration,"error":error}
                self._publish(ROOT + "/refresh_state",self._refresh_state)
                if not error:
                    self._last_refresh = self._refresh_state["finished_at"]
                    self._publish(ROOT + "/last_refresh",self._last_refresh)
            self._card.finish(operation,error=error,measured_seconds=duration)

    def _scheduled_release_check(self):
        while not self._stop.wait(10):
            if self._release.begin():
                self._release.complete()
                self._publish_release()
            if self._stop.wait(86400):
                break

    def refresh_targets(self, refresh_registry=True):
        from .ingress_catalog import target_catalog
        with self._mutex:
            registry = self._target_registries
        if refresh_registry or registry is None:
            registry = self.registry.fetch()
            try:
                self._temperature_unit = self.registry.fetch_temperature_unit()
            except Exception:
                self._temperature_unit = None
        states = self.registry.fetch_states()
        self.event_log.ha_observations(states)
        if self.event_log.timezone is None and hasattr(self.registry,"fetch_timezone"):
            try:
                self.event_log.set_timezone(self.registry.fetch_timezone())
            except Exception:
                pass  # HA unavailable: keep UTC explicitly labelled in UI.
        with self._mutex:
            self._target_registries = registry
            self.target_catalog = target_catalog(registry, states, self.config, self._temperature_unit)
        self._publish_details()

    def _observe_targets(self):
        while not self._stop.is_set():
            try:
                self.refresh_targets(refresh_registry=False)
            except Exception:
                with self._mutex:
                    for entry in self.target_catalog.values():
                        entry["state"] = "unknown"
                self._publish_details()
            self._stop.wait(15)

    def _auto_scan(self):
        """Startup scan after a complete inventory; later scans use a minute interval."""
        next_due = 0.0
        completed = False
        while not self._stop.wait(5):
            try:
                interval = self.auto_scan_interval
                if type(interval) is not int or not 0 <= interval <= 1440:
                    raise ValueError("Invalid auto_scan_interval")
                if completed and (interval == 0 or time.monotonic() < next_due):
                    continue
                with self._mutex:
                    ready = bool(verified_snapshots(self._networks))
                if ready and self.request_scan(foreground=False):
                    # Allow retained inventories and states to arrive; retry a
                    # failed first scan without interrupting existing bindings.
                    while not self._stop.wait(1) and self._scan_lock.locked():
                        pass
                    completed = self._scan["state"] == "idle"
                    next_due = time.monotonic() + (interval * 60 if completed else 30)
                    if not completed:
                        self._stop.wait(30)
            except Exception:
                LOG.exception("Automatic Aqara scan scheduling failed")
                self._stop.wait(30)

    def _delete_telemetry(self) -> None:
        if self.telemetry is None:
            return
        try:
            deleted = self.telemetry.delete()
        except (ContractDataError, OSError, ValueError) as exc:
            LOG.error("Aqara telemetry deletion state error: %s", exc)
            return
        if deleted:
            LOG.info("Aqara telemetry installation and history deleted; identity rotated")
        else:
            LOG.warning("Aqara telemetry deletion failed")

    def run(self) -> None:
        host, port = os.environ["MQTT_HOST"], int(os.environ["MQTT_PORT"])
        LOG.info("Starting Aqara MQTT input, Mode Keeper and direct MQTT lights %s", self.version)
        threading.Thread(target=self._run_actions, daemon=True,
                         name="dh-electrica-action-worker").start()
        threading.Thread(target=run_keeper, args=(self,), daemon=True,
                         name="dh-electrica-mode-keeper").start()
        threading.Thread(target=self._run_light_probes, daemon=True,
                         name="dh-electrica-light-state-probes").start()
        from .ingress import start_ingress
        web = start_ingress(self)
        threading.Thread(target=web.serve_forever, daemon=True,
                         name="dh-electrica-ingress").start()
        threading.Thread(target=self._scheduled_release_check, daemon=True,
                         name="dh-electrica-release-check").start()
        threading.Thread(target=self._observe_targets, daemon=True,
                         name="dh-electrica-target-observer").start()
        threading.Thread(target=self._auto_scan, daemon=True,
                         name="dh-electrica-auto-scan").start()
        if self.telemetry_runner is None:
            LOG.info('DigitalHouses telemetry disabled (consent not enabled); '
                     'legacy lighting runtime remains active during migration')
        else:
            self.telemetry_runner.start()
        try:
            self.client.connect(host, port, keepalive=60)
            self.client.loop_forever(retry_first_connection=True)
        finally:
            self._stop.set()
            web.shutdown()
            web.server_close()
            if self.telemetry_runner is not None:
                self.telemetry_runner.stop()
