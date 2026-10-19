#!/usr/bin/env python3
"""Experimental Home Assistant App runtime: GPS-based safe presence via MQTT."""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import signal
import threading
import time
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import paho.mqtt.client as mqtt
from dh_presence.core import Engine, Mode, Status, haversine_km, validate_tracker
from dh_presence.discovery import DISCOVERY, discovery, topic, with_cleanup
from dh_presence.storage import load, save
from dh_presence.modes import ModeSelection
from dh_presence.notifications import NotificationSelection, NOTIFICATION_KEYS
from dh_presence.zones import ZoneMonitor, zone_catalog, zone_key
from dh_presence.history import EventHistory, DEFAULT_LIMIT, MAX_LIMIT
from dh_presence.operations import Operations, fetch_latest_release, is_newer
from dh_presence.registration import REGISTRY_LOCK, delete_registration, load_registry_state
from dh_presence.phone_removal import EMPTY, PhoneRemovalSelection, phone_removal_choices
from dh_presence.phone_tree import registered_phones_tree
from dh_presence.router import poll_router_trackers
from dh_presence.ui import start_ingress_ui

LOG = logging.getLogger("dh_presence_app")
OPTIONS = "/data/options.json"
STATE = "/data/presence_state.json"
DISCOVERY_FILE = "/data/presence_discovery.json"
MODE_FILE = "/data/presence_mode.json"
NOTIFICATIONS_FILE = "/data/presence_notifications.json"
ZONES_FILE = "/data/presence_zones.json"
HISTORY_FILE = "/data/presence_event_history.json"
OPERATIONS_FILE = "/data/presence_refresh.json"
REGISTRATIONS_FILE = "/data/presence_registrations.json"
EVENT_NAMES = {"arrival", "departure", "gps_in", "gps_out", "wifi_in", "wifi_out", "wifi_lost", "zone_enter", "zone_leave"}
STOP = threading.Event()
WAKE = threading.Event()


def parsed_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timezone-aware source timestamp required")
    return dt


def gps_from_ha_state(state: dict, now: datetime, freshness: int, home: tuple) -> tuple[Status, float | None, datetime | None]:
    """Read the last actual HA GPS report; elapsed time alone never invalidates it."""
    if not isinstance(state, dict) or not isinstance(state.get("state"), str):
        return Status.UNAVAILABLE, None, None
    # last_updated does not change on repeated identical HA reports.
    # Keep the actual last_reported (or fallback) timestamp: an App poll
    # must not fabricate a new phone observation.
    observed_at_raw = state.get("last_reported") or state.get("last_updated")
    if not isinstance(observed_at_raw, str):
        return Status.UNAVAILABLE, None, None
    try:
        when = parsed_datetime(observed_at_raw)
    except ValueError:
        return Status.UNAVAILABLE, None, None
    age = (now-when).total_seconds()
    # iOS may stay motionless for days without a new GPS report.
    # Freshness is diagnostic only; reject impossible future timestamps.
    if age < -30:
        return Status.UNAVAILABLE, None, None
    raw = state["state"]
    if raw in ("unavailable", "unknown", ""):
        return Status.UNAVAILABLE, None, None
    status = Status.HOME if raw == "home" else Status.NOT_HOME
    distance = None
    attrs = state.get("attributes")
    if isinstance(attrs, dict) and all(type(attrs.get(k)) in (float, int) for k in ("latitude", "longitude")):
        try:
            distance = round(haversine_km(*home, attrs["latitude"], attrs["longitude"]), 3)
        except ValueError:
            pass
    return status, distance, when


def load_options(path=OPTIONS) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Options must be a map")
    mode = Mode(data["presence_mode"])
    timeout = data["wifi_absence_minutes"]
    freshness = data["gps_freshness_seconds"]
    poll = data["gps_poll_interval_seconds"]
    history_limit = data.get("events_history_limit", DEFAULT_LIMIT)
    if type(history_limit) is not int or not 1 <= history_limit <= MAX_LIMIT:
        raise ValueError("Invalid events_history_limit")
    data["events_history_limit"] = history_limit
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError("Invalid Wi-Fi timeout")
    if type(freshness) is not int or not 30 <= freshness <= 3600:
        raise ValueError("Invalid GPS freshness")
    if type(poll) is not int or not 10 <= poll <= 300:
        raise ValueError("Invalid GPS poll interval")
    excludes = data["exclude_users"]
    residents = data["residents"]
    if not isinstance(excludes, list) or not all(isinstance(s, str) and s for s in excludes):
        raise ValueError("Invalid excluded users")
    if not isinstance(residents, list):
        raise ValueError("Invalid resident list")
    for resident in residents:
        if isinstance(resident, str):
            validate_tracker(resident)
        elif isinstance(resident, dict):
            # Allow pre-0.1.1 stored config for a controlled migration.
            if (set(resident) != {"user_id", "name", "device_id", "gps_tracker"}
                    or any(not isinstance(v, str) or not v for v in resident.values())):
                raise ValueError("Invalid legacy resident specification")
            validate_tracker(resident["gps_tracker"])
        else:
            raise ValueError("Resident must contain one device_tracker entity ID")
    tracker_ids = [r if isinstance(r, str) else r["gps_tracker"] for r in residents]
    if len(tracker_ids) != len(set(tracker_ids)):
        raise ValueError("Each device_tracker may be registered only once")
    # Optional one-time resident identity mapping, stored by HA Supervisor in
    # the App's own persistent options alongside the registered trackers.
    # Do not infer household person identity from a tracker's friendly_name.
    resident_names = data.get("resident_names", [])
    if not isinstance(resident_names, list):
        raise ValueError("resident_names must be a list")
    seen_names = set()
    for entry in resident_names:
        if not isinstance(entry, dict) or set(entry) != {"device_tracker", "user_name"}:
            raise ValueError("Each resident_names entry requires device_tracker and user_name")
        tracker = validate_tracker(entry["device_tracker"])
        name = entry["user_name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise ValueError("Invalid resident user_name")
        if tracker not in tracker_ids:
            raise ValueError("resident_names contains an unregistered device_tracker")
        if tracker in seen_names:
            raise ValueError("Duplicate resident_names device_tracker")
        seen_names.add(tracker)
    data["resident_names"] = resident_names
    # Tracker-only residents without a verified user link are handled
    # fail-closed by build_engine when exclude_users is set.
    data["presence_mode"] = mode
    return data


def api_error_detail(exc: Exception) -> str:
    """Report API failure class/status without logging bearer tokens or response bodies."""
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code} ({exc.reason})"
    return type(exc).__name__



def audit_ha_discovery(token: str) -> tuple[str, str]:
    """Read only: check HA MQTT integration and expected entity IDs.

    Entity IDs can be renamed by the user. A negative result does not prove
    HA rejected the device, and broker PUBACK never proves HA acceptance.
    """
    config = http_json("http://supervisor/core/api/config", token)
    components = config.get("components")
    if isinstance(components, list) and "mqtt" not in components:
        return ("mqtt_not_loaded",
                "Home Assistant Core /config does not list the MQTT integration. "
                "A running MQTT broker App is not the same as a configured HA MQTT integration.")
    states = http_json("http://supervisor/core/api/states", token)
    if not isinstance(states, list):
        raise ValueError("HA /api/states response is not a list")
    entity_ids = {entry["entity_id"] for entry in states
                  if isinstance(entry, dict) and isinstance(entry.get("entity_id"), str)}
    expected = {
        "sensor.dh_presence_app_version",
        "select.dh_presence_app_mode",
        "binary_sensor.dh_presence_app_residents_home",
    }
    observed = sorted(expected.intersection(entity_ids))
    if observed:
        return ("found", "Expected Presence MQTT entities visible in HA: "
                + ", ".join(observed))
    mqtt_hint = "mqtt" if isinstance(components, list) and "mqtt" in components else "unknown"
    return ("not_found",
            "No expected Presence MQTT entity IDs in HA state registry (mqtt component=%s). "
            "Entities could be renamed; inspect HA Core log for MQTT Discovery schema errors, "
            "and compare MQTT broker/discovery prefix. Do not delete MQTT devices." % mqtt_hint)


def http_json(url: str, token: str, timeout: int = 8):
    req = Request(url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.load(r)


class MqttOutput:
    def __init__(self, version: str):
        callback_api = getattr(mqtt, "CallbackAPIVersion", None)
        self.client = mqtt.Client(callback_api.VERSION2, client_id="dh_presence_app") if callback_api else mqtt.Client(client_id="dh_presence_app")
        user = os.environ["MQTT_USER"]
        if user:
            self.client.username_pw_set(user, os.environ["MQTT_PASSWORD"])
        self.connected = threading.Event()
        self.cache: dict[str, str] = {}
        self.client.on_connect = self._connected
        self.client.on_disconnect = self._disconnected
        self.client.on_message = self._message
        self.mode_commands = queue.SimpleQueue()
        self.notification_commands = queue.SimpleQueue()
        self.discovery_requests = queue.SimpleQueue()
        self.operation_commands = queue.SimpleQueue()
        self.phone_commands = queue.SimpleQueue()
        self.client.will_set(topic("availability"), "offline", retain=True, qos=1)
        self.client.connect_async(os.environ["MQTT_HOST"], int(os.environ["MQTT_PORT"]), keepalive=60)
        self.client.loop_start()
        self.version = version

    def _connected(self, client, userdata, flags, reason_code, *args):
        if reason_code == 0:
            self.cache.clear()
            self.connected.set()
            mode_result = client.subscribe(topic("mode/set"), qos=1)
            birth_result = client.subscribe("homeassistant/status", qos=1)
            command_result = client.subscribe(topic("command"), qos=1)
            notification_results = [
                client.subscribe(topic("notifications/" + key + "/set"), qos=1)[0]
                for key in NOTIFICATION_KEYS
            ]
            client.subscribe(topic("notifications/zones/+/set"), qos=1)
            client.subscribe(topic("registrations/remove/select/set"), qos=1)
            client.subscribe(topic("registrations/remove/press"), qos=1)
            LOG.info("MQTT connected; mode=%s birth=%s commands=%s notifications=%s",
                     mode_result[0], birth_result[0], command_result[0],
                     notification_results)
        else:
            self.connected.clear()
            LOG.error("MQTT rejected connection: %s", reason_code)

    def _disconnected(self, client, userdata, *args):
        self.connected.clear()
        LOG.warning("MQTT disconnected")

    def _message(self, client, userdata, msg):
        if msg.topic == "homeassistant/status":
            if msg.payload == b"online" and not getattr(msg, "retain", False):
                self.discovery_requests.put("ha_birth")
                WAKE.set()
            return
        if msg.topic == topic("registrations/remove/select/set"):
            if getattr(msg, "retain", False):
                LOG.warning("Ignoring retained phone removal selection")
                return
            if not 0 < len(msg.payload) <= 512:
                LOG.warning("Invalid phone selection size")
                return
            try:
                selected = msg.payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                LOG.warning("Invalid phone selection encoding")
                return
            self.phone_commands.put(("select", selected))
            WAKE.set()
            return
        if msg.topic == topic("registrations/remove/press"):
            if getattr(msg, "retain", False):
                LOG.warning("Ignoring retained phone removal button")
            elif msg.payload == b"DELETE":
                self.phone_commands.put(("delete", None))
                WAKE.set()
            else:
                LOG.warning("Invalid phone removal button payload")
            return
        if msg.topic == topic("command"):
            if getattr(msg, "retain", False):
                LOG.warning("Ignoring retained MQTT operation command")
                return
            if msg.payload in (b"REFRESH", b"CHECK_UPDATES"):
                self.operation_commands.put(msg.payload.decode("ascii"))
                WAKE.set()
            else:
                LOG.warning("Ignoring invalid MQTT operation command")
            return
        key = next((k for k in NOTIFICATION_KEYS
                    if msg.topic == topic("notifications/" + k + "/set")), None)
        prefix = topic("notifications/zones/")
        if key is None and msg.topic.startswith(prefix) and msg.topic.endswith("/set"):
            candidate = msg.topic[len(prefix):-4]
            if len(candidate) == 16 and all(c in "0123456789abcdef" for c in candidate):
                key = "zones/" + candidate
        if key is not None:
            if getattr(msg, "retain", False):
                LOG.warning("Ignoring retained MQTT notification command")
            elif msg.payload in (b"ON", b"OFF"):
                self.notification_commands.put((key, msg.payload.decode("ascii")))
                WAKE.set()
            else:
                LOG.warning("Ignoring invalid MQTT notification command key=%s", key)
            return
        if msg.topic != topic("mode/set"):
            return
        if getattr(msg, "retain", False):
            LOG.warning("Ignoring retained MQTT mode command")
            return
        try:
            requested = msg.payload.decode("ascii", errors="strict")
            if len(msg.payload) > 16 or requested not in {m.value for m in Mode}:
                raise ValueError("invalid mode")
        except (UnicodeDecodeError, ValueError):
            LOG.warning("Ignoring invalid MQTT mode command")
            return
        self.mode_commands.put(requested)
        WAKE.set()

    def publish(self, destination: str, payload, *, retain=True, force=False) -> bool:
        if not self.connected.is_set():
            return False
        message = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if isinstance(payload, (dict, list)) else str(payload)
        if retain and not force and self.cache.get(destination) == message:
            return True
        info = self.client.publish(destination, message, qos=1, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            LOG.error("MQTT publish rejected topic=%s rc=%s", destination, info.rc)
            self.connected.clear()
            return False
        try:
            info.wait_for_publish(timeout=6)
        except (RuntimeError, ValueError) as exc:
            LOG.error("MQTT publish acknowledgment failed topic=%s error=%s", destination, type(exc).__name__)
            return False
        if not info.is_published():
            LOG.error("MQTT publish not acknowledged topic=%s", destination)
            return False
        if retain:
            self.cache[destination] = message
        return True

    def stop(self):
        if self.connected.is_set():
            self.publish(topic("availability"), "offline", force=True)
        self.client.disconnect()
        self.client.loop_stop()


def build_engine(options: dict, saved: dict, registrations: list[dict] | None = None,
                 suppressed_trackers: set[str] | None = None) -> Engine:
    engine = Engine(mode=options["presence_mode"], wifi_absence_minutes=options["wifi_absence_minutes"],
                    freshness_seconds=options["gps_freshness_seconds"])
    # Tracker identity is deliberately different from HA User identity. We
    # cannot infer user ownership from the tracker or assume the iPad is a phone.
    previous = {r["tracker"]: r for r in saved["residents"]} if saved["schema_version"] == 2 else {}
    legacy = {r["user_id"]: r for r in saved["residents"]} if saved["schema_version"] == 1 else {}
    excludes = set(options["exclude_users"])
    names = {entry["device_tracker"]: entry["user_name"]
             for entry in options.get("resident_names", [])}
    registered = {r["tracker"]: r for r in (registrations or [])}
    suppressed = suppressed_trackers or set()
    for item in options["residents"]:
        if isinstance(item, str):
            if item in suppressed:
                continue
            # No authenticated user-id for a legacy tracker-only entry:
            # never count it when an HA User exclusion must be enforced.
            if excludes and item not in registered:
                continue
            tracker, name, old_state = item, friendly_tracker_name(item), previous.get(item)
        else:
            if item["user_id"] in excludes or item["gps_tracker"] in suppressed:
                continue
            tracker, name = item["gps_tracker"], item["name"]
            old_state = previous.get(tracker) or legacy.get(item["user_id"])
        link = registered.get(tracker)
        if link and link["user_id"] in excludes:
            continue
        engine.add(tracker, link["device_name"] if link else name, old_state,
                   user_name=link["user_name"] if link else names.get(tracker),
                   registered=link is not None)
    # Dynamic enrollment is durable and independent of the App config's old
    # residents list. A new resident starts unknown, without synthetic events.
    for tracker, link in registered.items():
        if (tracker not in suppressed and tracker not in engine.residents
                and link["user_id"] not in excludes):
            engine.add(tracker, link["device_name"], previous.get(tracker),
                       user_name=link["user_name"], registered=True)
    # The roster is also an inventory source for Lovelace. Include the
    # persistent router association before the first successful HA poll.
    for tracker, link in registered.items():
        if tracker in engine.residents:
            engine.residents[tracker].wifi_tracker_id = link.get("wifi_tracker")
    return engine



def reconcile_registration_roster(engine: Engine, options: dict,
                                  registrations: list[dict],
                                  suppressed_trackers: set[str]) -> bool:
    """Synchronize live membership after administrator removal/re-registration.

    Existing source/confirmed evidence is preserved for unchanged trackers;
    removed trackers cannot emit departure and new phones start UNKNOWN.
    """
    expected = build_engine(options, {"schema_version": 2, "residents": []},
                            registrations, suppressed_trackers).residents
    changed = False
    for tracker in list(engine.residents):
        if tracker not in expected:
            del engine.residents[tracker]
            changed = True
    for tracker, candidate in expected.items():
        current = engine.residents.get(tracker)
        if current is None:
            engine.add(tracker, candidate.name, user_name=candidate.user_name,
                       registered=candidate.registered)
            engine.residents[tracker].wifi_tracker_id = candidate.wifi_tracker_id
            changed = True
            continue
        for field in ("name", "user_name", "registered", "wifi_tracker_id"):
            wanted = getattr(candidate, field)
            if getattr(current, field) != wanted:
                setattr(current, field, wanted)
                changed = True
    return changed



def execute_mqtt_phone_deletion(selection: PhoneRemovalSelection, engine: Engine,
                                options: dict, path: str, registrations: list[dict],
                                suppressed: set[str]) -> tuple[bool, bool, list[dict], set[str]]:
    """Delete only a currently selected, registered resident in this App.

    The same module-level lock protects the private Ingress registration
    transaction. Selection is cleared *before* any I/O, so even a duplicate
    MQTT QoS1 press cannot cascade into another deletion.
    """
    choices = phone_removal_choices(registrations, list(engine.residents.values()))
    target = selection.target(choices)
    selection.clear()
    if not target:
        return False, False, registrations, suppressed
    with REGISTRY_LOCK:
        latest, disabled = load_registry_state(path)
        if not any(row["tracker"] == target for row in latest):
            changed = reconcile_registration_roster(engine, options, latest, disabled)
            return False, changed, latest, disabled
        delete_registration(path, target)
        latest, disabled = load_registry_state(path)
    changed = reconcile_registration_roster(engine, options, latest, disabled)
    return True, changed, latest, disabled


def friendly_tracker_name(tracker: str) -> str:
    return tracker.removeprefix("device_tracker.").replace("_", " ").strip()


def observe_friendly_name(resident, state: dict) -> bool:
    attrs = state.get("attributes")
    label = attrs.get("friendly_name") if isinstance(attrs, dict) else None
    if isinstance(label, str) and label.strip() and label.strip() != resident.name:
        resident.name = label.strip()
        return True
    return False

def load_discovery() -> dict:
    try:
        content = Path(DISCOVERY_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"components": {}}
    data = json.loads(content)
    if not isinstance(data, dict) or not isinstance(data.get("components"), dict):
        raise ValueError("Corrupt discovery cache")
    return data


def synchronize_discovery(output: MqttOutput, version: str, engine: Engine, *,
                          zones: dict[str, str] | None = None, routine: bool = False,
                          registrations: list[dict] | None = None) -> bool:
    choices = phone_removal_choices(registrations or [], list(engine.residents.values()))
    current = discovery(version, list(engine.residents.values()), zones,
                        phone_options=[EMPTY, *choices])
    old = load_discovery()
    if old.get("components") and not output.publish(DISCOVERY, with_cleanup(old, current), force=True):
        LOG.error("MQTT Discovery cleanup publish failed topic=%s", DISCOVERY)
        return False
    if not output.publish(DISCOVERY, current, force=True):
        LOG.error("MQTT Discovery config publish failed topic=%s", DISCOVERY)
        return False
    # Config is stored separately from logical resident state.
    save_discovery(current)
    # Retained re-announcements are routine broker maintenance, not state changes.
    LOG.log(logging.DEBUG if routine else logging.INFO,
            "MQTT Discovery published topic=%s components=%d device=%s (QoS1, retained)",
            DISCOVERY, len(current["components"]), current["device"]["name"])
    return True


def save_discovery(value: dict):
    path = Path(DISCOVERY_FILE)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def publish_snapshot(output: MqttOutput, engine: Engine, version: str, started: str,
                     operations: Operations, latest_version: str | None,
                     notifications: NotificationSelection | None = None,
                     zones: dict[str, str] | None = None,
                     history: EventHistory | None = None,
                     registrations: list[dict] | None = None,
                     phone_selection: PhoneRemovalSelection | None = None,
                     phone_time_zone: tzinfo | None = None) -> bool:
    snapshot = engine.snapshot()
    if not output.publish(topic("mode/state"), engine.mode.value):
        return False
    if notifications is not None:
        for key in NOTIFICATION_KEYS:
            if not output.publish(topic("notifications/" + key + "/state"),
                                  notifications.mqtt_state(key)):
                return False
        for entity_id in (zones or {}):
            key = "zones/" + zone_key(entity_id)
            if not output.publish(topic("notifications/" + key + "/state"),
                                  notifications.mqtt_state(key)):
                return False
    # Source/aggregate availability must be committed BEFORE the retained
    # snapshot. Otherwise an invalid/unconfirmed GPS or sleeping iPhone first
    # renders as OFF and only afterwards becomes unavailable in HA Recorder.
    # Publish after the availability update to avoid spurious false OFF edges.
    if not output.publish(topic("presence_observed"),
                          "offline" if snapshot["status"] == Status.UNAVAILABLE.value else "online"):
        return False
    for r in engine.residents.values():
        ok = output.publish(topic("gps/"+r.key+"/availability"),
                            "online" if r.gps is not Status.UNAVAILABLE else "offline")
        ok = output.publish(topic("wifi/"+r.key+"/availability"),
                            "online" if r.wifi is not Status.UNAVAILABLE else "offline") and ok
        ok = output.publish(topic("distance/"+r.key+"/availability"),
                            "online" if r.distance is not None else "offline") and ok
        if not ok:
            return False
    if not output.publish(topic("state"), snapshot):
        return False
    if not output.publish(topic("diagnostics"), {
        "version": version, "started_at": started,
        "source_status": "router_tracker" if engine.mode is Mode.WIFI
                         else "gps_with_router_tracker",
    }):
        return False
    if history is not None and not output.publish(topic("events/history"), history.snapshot()):
        return False
    # Dedicated UI topic avoids repeating enrollment-time IP/MAC in the
    # standard presence sensor attributes and Recorder history.
    # MQTT output.cache deduplicates unchanged registration trees.
    if registrations is not None and not output.publish(
            topic("registrations/tree"),
            registered_phones_tree(registrations, list(engine.residents.values()),
                                   local_tz=phone_time_zone)):
        return False
    if phone_selection is not None and not output.publish(
            topic("registrations/remove/select/state"), phone_selection.selected):
        return False
    for r in engine.residents.values():
        if r.distance is not None and not output.publish(topic("distance/"+r.key), r.distance):
            return False
    if not publish_controls(output, operations, version, latest_version):
        return False
    return output.publish(topic("availability"), "online")


def publish_controls(output: MqttOutput, operations: Operations,
                     installed_version: str, latest_version: str | None) -> bool:
    if not output.publish(topic("operations"), operations.snapshot()):
        return False
    if not output.publish(topic("release"), {
        "latest_version": latest_version,
        "update_available": is_newer(installed_version, latest_version),
    }):
        return False
    return output.publish(topic("release/availability"), "online" if latest_version else "offline")


def run():
    version = os.environ["APP_VERSION"]
    options = load_options()
    saved = load(STATE)
    registrations, suppressed_trackers = load_registry_state(REGISTRATIONS_FILE)
    engine = build_engine(options, saved, registrations, suppressed_trackers)
    modes = ModeSelection(MODE_FILE, options["presence_mode"])
    notifications = NotificationSelection(NOTIFICATIONS_FILE)
    zone_monitor = ZoneMonitor(ZONES_FILE)
    history = EventHistory(HISTORY_FILE, options["events_history_limit"])
    phone_selection = PhoneRemovalSelection()
    history.prune_residents({r.key for r in engine.residents.values()})
    zones: dict[str, str] = {}
    zones_loaded = False
    engine.set_mode(modes.selected)
    operations = Operations(OPERATIONS_FILE)
    latest_version = None
    last_release_check = None
    last_registration_check = None
    token = os.environ["SUPERVISOR_TOKEN"]
    ingress = start_ingress_ui(token, REGISTRATIONS_FILE, options["exclude_users"])
    started = datetime.now(timezone.utc).isoformat()
    mqtt_out = MqttOutput(version)
    home = None
    phone_time_zone: tzinfo | None = None
    last_zone_retry = None
    discovery_ready = False
    previous_mqtt_connection = False
    last_discovery_attempt = None
    last_discovery_session = None
    previous_core_error = None
    published_state_logged = False
    reported_gps_status = {}
    last_discovery_audit = None
    last_discovery_audit_status = None
    LOG.info("Starting %s version %s mode=%s residents=%d Wi-Fi source=HA router tracker",
             "DigitalHouses Presence App", version, engine.mode.value,
             len(engine.residents))
    if options["telemetry_enabled"]:
        LOG.warning("Experimental pilot: telemetry_enabled=true, but there is no telemetry sender; no statistics are transmitted.")
    if not engine.residents:
        LOG.info("No residents registered yet; use the DH Presence Ingress UI on a local phone")
    try:
        while not STOP.is_set():
            connected = mqtt_out.connected.is_set()
            if not connected:
                discovery_ready = False
                last_discovery_session = None
                published_state_logged = False
            if connected and not previous_mqtt_connection:
                # Do not announce online until retained discovery and live states
                # have been published successfully.
                mqtt_out.publish(topic("availability"), "offline", force=True)
                discovery_ready = False
                last_discovery_session = None
            previous_mqtt_connection = connected
            ha_birth = False
            while not mqtt_out.discovery_requests.empty():
                mqtt_out.discovery_requests.get_nowait()
                ha_birth = True
            now_monotonic = time.monotonic()
            try:
                new_zones = zone_catalog(http_json("http://supervisor/core/api/states", token))
                zones_loaded = True
                if new_zones != zones:
                    zones = new_zones
                    notifications.sync_zones(zones)
                    last_discovery_session = None
            except (URLError, OSError, ValueError, TypeError, KeyError) as exc:
                LOG.debug("HA zones temporarily unavailable: %s", type(exc).__name__)
            if connected and zones_loaded and (ha_birth or last_discovery_session is None
                              or now_monotonic - last_discovery_session >= 300):
                # Retry a failed Discovery every GPS polling interval, and
                # re-announce after HA starts and every 5 minutes.
                if last_discovery_attempt is None or ha_birth or now_monotonic - last_discovery_attempt >= max(10, options["gps_poll_interval_seconds"]):
                    last_discovery_attempt = now_monotonic
                    routine = last_discovery_session is not None and not ha_birth and discovery_ready
                    discovery_ready = synchronize_discovery(mqtt_out, version, engine, zones=zones, routine=routine,
                                                            registrations=registrations)
                    if discovery_ready:
                        last_discovery_session = now_monotonic
                    else:
                        LOG.error("MQTT Discovery not synchronized; retrying automatically, retained topic=%s", DISCOVERY)
            operations.tick()
            pending_operations = set()
            while not mqtt_out.operation_commands.empty():
                pending_operations.add(mqtt_out.operation_commands.get_nowait())
            refresh_requested = "REFRESH" in pending_operations
            check_requested = "CHECK_UPDATES" in pending_operations
            if refresh_requested and operations.begin("refresh"):
                publish_controls(mqtt_out, operations, version, latest_version)
            while not mqtt_out.notification_commands.empty():
                key, requested = mqtt_out.notification_commands.get_nowait()
                try:
                    if notifications.change(key, requested):
                        LOG.info("Notification channel %s set to %s", key, requested)
                except (OSError, ValueError) as exc:
                    LOG.error("Notification setting not saved: %s", type(exc).__name__)
            while not mqtt_out.mode_commands.empty():
                requested = mqtt_out.mode_commands.get_nowait()
                if modes.change(requested):
                    engine.set_mode(modes.selected)
                    # Switching the decision source must not synthesize a
                    # departure/arrival from the same GPS observation.
                    for resident in engine.residents.values():
                        resident.initialized = False
                    LOG.info("Presence mode changed from HA UI to %s", engine.mode.value)
            # Ingress writes the private registration database atomically.
            # One engine observes the new roster without a service restart,
            # without a second Core adapter, and without synthetic events.
            if (last_registration_check is None
                    or time.monotonic() - last_registration_check >= 5):
                last_registration_check = time.monotonic()
                latest, disabled = load_registry_state(REGISTRATIONS_FILE)
                if latest != registrations or disabled != suppressed_trackers:
                    # One app-owned registry is authoritative even if a legacy
                    # Supervisor residents option still names a removed phone.
                    registrations, suppressed_trackers = latest, disabled
                    changed = reconcile_registration_roster(
                        engine, options, registrations, suppressed_trackers)
                    if changed:
                        discovery_ready = (synchronize_discovery(
                            mqtt_out, version, engine, zones=zones, registrations=registrations)
                            if mqtt_out.connected.is_set() else False)
                        LOG.info("DH Presence phone registry synchronized: active=%d",
                                 len(engine.residents))
                    phone_selection.refresh(phone_removal_choices(
                        registrations, list(engine.residents.values())))
            # Ordered commands: a select immediately followed by button
            # press always targets that exact selection. The MQTT broker
            # provides no HA-user admin attestation; Lovelace hides this UI
            # from ordinary users as presentation, not authorization.
            roster_changed = False
            for _ in range(64):
                try:
                    action, value = mqtt_out.phone_commands.get_nowait()
                except queue.Empty:
                    break
                choices = phone_removal_choices(registrations, list(engine.residents.values()))
                if action == "select":
                    if not phone_selection.select(value, choices):
                        LOG.warning("Ignoring invalid MQTT removal selection")
                    continue
                if action != "delete":
                    continue
                target = phone_selection.target(choices)
                try:
                    deleted, changed, registrations, suppressed_trackers = execute_mqtt_phone_deletion(
                        phone_selection, engine, options, REGISTRATIONS_FILE,
                        registrations, suppressed_trackers)
                    roster_changed = changed or roster_changed
                    if deleted:
                        LOG.info("Phone registration removed by MQTT: tracker=%s", target)
                    else:
                        LOG.warning("Phone removal skipped: missing or stale selection")
                except (OSError, ValueError, LookupError) as exc:
                    LOG.error("MQTT phone removal failed for %s: %s",
                              target or "none", type(exc).__name__)
            phone_selection.refresh(phone_removal_choices(
                registrations, list(engine.residents.values())))
            if roster_changed:
                eligible_keys = {r.key for r in engine.residents.values()}
                history.prune_residents(eligible_keys)
                zone_monitor.prune_residents(eligible_keys)
                discovery_ready = (synchronize_discovery(
                    mqtt_out, version, engine, zones=zones,
                    registrations=registrations) if mqtt_out.connected.is_set() else False)
            now = datetime.now(timezone.utc)
            name_changed = False
            if home is None or (phone_time_zone is None and
                                (last_zone_retry is None or time.monotonic() - last_zone_retry >= 300)):
                # HA config is authoritative; never infer local time from the
                # App container (which can run in UTC). Retry missing zone.
                last_zone_retry = time.monotonic()
                try:
                    conf = http_json("http://supervisor/core/api/config", token)
                    coordinates = (float(conf["latitude"]), float(conf["longitude"]))
                    if home is None:
                        LOG.info("Home Assistant Core API connected; home coordinates resolved for GPS distance")
                    home = coordinates
                    tz_name = conf.get("time_zone")
                    try:
                        phone_time_zone = ZoneInfo(tz_name) if isinstance(tz_name, str) else None
                    except (ZoneInfoNotFoundError, ValueError):
                        phone_time_zone = None
                    if phone_time_zone is None:
                        LOG.warning("HA timezone unavailable; status tree local times omitted until resolved")
                    previous_core_error = None
                except (URLError, OSError, KeyError, ValueError, TypeError) as exc:
                    problem = api_error_detail(exc)
                    if problem != previous_core_error:
                        LOG.error("Home Assistant Core API /config unavailable: %s", problem)
                        previous_core_error = problem
            events = []
            # GPS and router polling share one logical decision point.
            # Source wifi_in/out and gps_in/out remain independent diagnostics.
            engine.begin_observation_cycle()
            zone_monitor.prune_residents({r.key for r in engine.residents.values()})
            history.prune_residents({r.key for r in engine.residents.values()})
            for r in engine.residents.values():
                try:
                    data = http_json("http://supervisor/core/api/states/" + r.tracker, token)
                    # A WebSocket-enrolled resident's device name is
                    # registered once from the selected Mobile Companion entry,
                    # not inferred from a possibly renamed GPS entity.
                    if not any(x["tracker"] == r.tracker for x in registrations):
                        name_changed = observe_friendly_name(r, data) or name_changed
                    status, distance, observed = gps_from_ha_state(data, now, options["gps_freshness_seconds"], home) if home else (Status.UNAVAILABLE, None, None)
                    if observed is not None and status is not Status.UNAVAILABLE:
                        if reported_gps_status.get(r.tracker) != status.value:
                            recovered = str(reported_gps_status.get(r.tracker, "")).startswith("error:")
                            LOG.info("GPS tracker %s: %s (%s)", r.tracker, status.value,
                                     "Core API recovered" if recovered else "source available")
                            reported_gps_status[r.tracker] = status.value
                        events.extend(engine.gps_observation(r.tracker, status, observed, distance, decision_at=now))
                        if zones_loaded:
                            events.extend(zone_monitor.observe(r.key, data['state'], observed, zones))
                    else:
                        if reported_gps_status.get(r.tracker) != "unavailable":
                            LOG.warning("GPS tracker %s: source unavailable/stale; last confirmed presence preserved", r.tracker)
                            reported_gps_status[r.tracker] = "unavailable"
                        engine.gps_unavailable(r.tracker, now)
                except (URLError, OSError, ValueError, TypeError, KeyError) as exc:
                    engine.gps_unavailable(r.tracker, now)
                    problem = api_error_detail(exc)
                    if reported_gps_status.get(r.tracker) != "error:" + problem:
                        log_method = LOG.warning if isinstance(exc, HTTPError) and exc.code in (502, 503, 504) else LOG.error
                        log_method("Home Assistant Core API tracker %s unavailable: %s; last confirmed presence preserved", r.tracker, problem)
                        reported_gps_status[r.tracker] = "error:" + problem
            # Router associations are the sole Wi-Fi truth; no periodic LAN probes.
            try:
                router_states = http_json("http://supervisor/core/api/states", token)
                if not isinstance(router_states, list):
                    raise ValueError("Invalid HA state registry response")
            except (URLError, OSError, ValueError, TypeError) as exc:
                LOG.warning("Router tracker API unavailable: %s", api_error_detail(exc))
                router_states = None
            if router_states is not None:
                events.extend(poll_router_trackers(
                    engine,
                    [x for x in registrations if x["user_id"] not in options["exclude_users"]],
                    router_states, now,
                ))
            else:
                for resident in engine.residents.values():
                    resident.wifi_source = "router"
                    engine.wifi_observation(
                        resident.tracker, Status.UNAVAILABLE, now, verified=False)
                    resident.wifi_last_probe_at = now
                    resident.wifi_probe_result = "router_api_error"
            # The complete GPS/Wi-Fi snapshot, not an intermediate source,
            # determines arrival/departure (one decision per resident/poll).
            events.extend(engine.finish_observation_cycle(now))
            if name_changed and mqtt_out.connected.is_set():
                discovery_ready = synchronize_discovery(mqtt_out, version, engine, zones=zones,
                                                        registrations=registrations)
            # Commit durable current state BEFORE sending retained MQTT state and events.
            save(STATE, engine.persistent())
            published = (mqtt_out.connected.is_set() and discovery_ready
                         and publish_snapshot(mqtt_out, engine, version, started,
                                              operations, latest_version, notifications, zones, history,
                                              registrations, phone_selection,
                                              phone_time_zone))
            if published:
                if not published_state_logged:
                    LOG.info("MQTT presence state published topic=%s residents=%d mode=%s",
                             topic("state"), len(engine.residents), engine.mode.value)
                    published_state_logged = True
                for event in events:
                    if event["event_type"] not in EVENT_NAMES:
                        raise ValueError("Invalid internal event")
                    resident = next(r for r in engine.residents.values() if r.key == event["resident_id"])
                    machine_event = {
                        "schema_version": 2, "mode": engine.mode.value,
                        "resident_name": resident.name,
                        "device_name": resident.name,
                        "user_name": resident.user_name,
                        "device_tracker": resident.tracker,
                        **event
                    }
                    if mqtt_out.publish(topic("event"), machine_event, retain=False, force=True):
                        # Only acknowledged machine events enter the durable UI history.
                        history.record(machine_event)
                        LOG.info("MQTT presence event published type=%s tracker=%s mode=%s",
                                 event["event_type"], resident.tracker, engine.mode.value)
                # The retained read-only snapshot is separate from transient events.
                # On broker failure it is retried from the durable ring on the next poll.
                if events and not mqtt_out.publish(topic("events/history"), history.snapshot()):
                    LOG.warning("MQTT event history not synchronized; will retry")
            if refresh_requested:
                error = None
                if not published:
                    error = "MQTT snapshot not acknowledged"
                elif not engine.residents:
                    error = "No registered phone trackers"
                elif engine.mode is Mode.WIFI and not any(
                        r.wifi is Status.HOME for r in engine.residents.values()):
                    error = "No currently verified HA router Wi-Fi tracker"
                elif any(r.gps is Status.UNAVAILABLE for r in engine.residents.values()):
                    error = "One or more GPS trackers have no valid last-known observation"
                try:
                    operations.finish(error, refresh_succeeded=(error is None))
                except (OSError, ValueError) as exc:
                    operations.finish("Could not persist refresh: " + type(exc).__name__)
                publish_controls(mqtt_out, operations, version, latest_version)

            if check_requested and operations.begin("check"):
                publish_controls(mqtt_out, operations, version, latest_version)
                last_release_check = time.monotonic()
                try:
                    latest_version = fetch_latest_release()
                    operations.finish()
                except (URLError, OSError, ValueError, TypeError, KeyError) as exc:
                    operations.finish("Release check failed: " + api_error_detail(exc))
                publish_controls(mqtt_out, operations, version, latest_version)
            elif last_release_check is None or time.monotonic() - last_release_check >= 86400:
                last_release_check = time.monotonic()
                try:
                    latest_version = fetch_latest_release()
                except (URLError, OSError, ValueError, TypeError, KeyError) as exc:
                    LOG.warning("Background stable release check unavailable: %s", api_error_detail(exc))
                publish_controls(mqtt_out, operations, version, latest_version)

            # Broker QoS1 acknowledgment is not evidence that HA accepted
            # Discovery. After HA has time to process it, verify read-only via
            # Core REST; log only on change and recheck at a bounded interval.
            if (discovery_ready and last_discovery_session is not None
                    and time.monotonic() - last_discovery_session >= 10
                    and (last_discovery_audit is None
                         or time.monotonic() - last_discovery_audit >= 180)):
                last_discovery_audit = time.monotonic()
                try:
                    audit_status, audit_detail = audit_ha_discovery(token)
                except (URLError, OSError, ValueError, TypeError, KeyError) as exc:
                    audit_status = "audit_error:" + api_error_detail(exc)
                    audit_detail = "HA discovery read-only audit failed: " + api_error_detail(exc)
                if audit_status != last_discovery_audit_status:
                    if audit_status == "found":
                        LOG.info("HA MQTT Discovery acceptance check: %s", audit_detail)
                    else:
                        LOG.warning("HA MQTT Discovery acceptance check: %s", audit_detail)
                    last_discovery_audit_status = audit_status
            # Clear BEFORE checking pending commands to avoid a lost wake-up.
            WAKE.clear()
            if (not STOP.is_set() and mqtt_out.mode_commands.empty()
                    and mqtt_out.notification_commands.empty()
                    and mqtt_out.phone_commands.empty()
                    ):
                WAKE.wait(min(options["gps_poll_interval_seconds"],
                              5 if operations.state == "success" else options["gps_poll_interval_seconds"]))
    finally:
        mqtt_out.stop()
        ingress.shutdown()
        ingress.server_close()


def main():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    def stop_signal(*_):
        STOP.set()
        WAKE.set()

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    run()


if __name__ == "__main__":
    main()
