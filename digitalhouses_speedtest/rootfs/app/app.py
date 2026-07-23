\
"""DigitalHouses Speedtest Home Assistant App."""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from core import (
    atomic_write_json,
    build_success_state,
    default_state,
    load_json,
    migrate_state,
    parse_server_list,
    utc_now,
)

APP_VERSION = os.getenv("APP_VERSION", "1.0.0-local")
DATA_DIR = Path("/data")
OPTIONS_FILE = DATA_DIR / "options.json"
STATE_FILE = DATA_DIR / "state.json"
SERVERS_FILE = DATA_DIR / "servers.json"

MQTT_BASE_TOPIC = "DigitalHouses/Global/speedtest"
DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = "digitalhouses_global_speedtest"
DEVICE_NAME = "Internet Speedtest"

STATE_TOPIC = f"{MQTT_BASE_TOPIC}/state"
COMMAND_TOPIC = f"{MQTT_BASE_TOPIC}/command"
AVAILABILITY_TOPIC = f"{MQTT_BASE_TOPIC}/availability"
CONNECTIVITY_TOPIC = f"{MQTT_BASE_TOPIC}/connectivity"
SERVERS_TOPIC = f"{MQTT_BASE_TOPIC}/servers"
DISCOVERY_TOPIC = f"{DISCOVERY_PREFIX}/device/{DEVICE_ID}/config"

GOOGLE_DNS = "8.8.8.8"
CLOUDFLARE_DNS = "1.1.1.1"

DEFAULT_OPTIONS: dict[str, Any] = {
    "periodic_test_enabled": True,
    "periodic_test_interval_minutes": 180,
    "server_ids": [],
    "automatic_server_fallback": True,
    "speedtest_timeout_seconds": 240,
    "connectivity_check": {
        "interval_seconds": 60,
        "attempts": 3,
        "timeout_seconds": 2,
    },
    "expire_after_seconds": 14400,
    "log_level": "info",
}


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def load_options() -> dict[str, Any]:
    raw = load_json(OPTIONS_FILE, {})
    if not isinstance(raw, dict):
        raw = {}
    connectivity = raw.get("connectivity_check")
    if not isinstance(connectivity, dict):
        connectivity = {}

    ids: list[int] = []
    for value in raw.get("server_ids", []):
        try:
            server_id = int(value)
        except (TypeError, ValueError):
            continue
        if server_id > 0 and server_id not in ids:
            ids.append(server_id)

    level = str(raw.get("log_level", "info")).lower()
    if level not in {"debug", "info", "warning", "error"}:
        level = "info"

    return {
        "periodic_test_enabled": bool(
            raw.get("periodic_test_enabled", DEFAULT_OPTIONS["periodic_test_enabled"])
        ),
        "periodic_test_interval_minutes": _bounded_int(
            raw.get("periodic_test_interval_minutes"), 5, 720, 180
        ),
        "server_ids": ids,
        "automatic_server_fallback": bool(
            raw.get(
                "automatic_server_fallback",
                DEFAULT_OPTIONS["automatic_server_fallback"],
            )
        ),
        "speedtest_timeout_seconds": _bounded_int(
            raw.get("speedtest_timeout_seconds"), 30, 600, 240
        ),
        "connectivity_check": {
            "interval_seconds": _bounded_int(
                connectivity.get("interval_seconds"), 10, 3600, 60
            ),
            "attempts": _bounded_int(connectivity.get("attempts"), 1, 10, 3),
            "timeout_seconds": _bounded_int(
                connectivity.get("timeout_seconds"), 1, 30, 2
            ),
        },
        "expire_after_seconds": _bounded_int(
            raw.get("expire_after_seconds"), 0, 86400, 14400
        ),
        "log_level": level,
    }


class SpeedtestApp:
    """Long-running MQTT bridge and scheduler."""

    def __init__(self) -> None:
        self.options = load_options()
        logging.basicConfig(
            level=getattr(logging, self.options["log_level"].upper()),
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.log = logging.getLogger("digitalhouses_speedtest")

        self.state_lock = threading.RLock()
        self.state = migrate_state(load_json(STATE_FILE, default_state()))
        self.servers = load_json(
            SERVERS_FILE,
            {"count": 0, "updated_at": None, "servers": [], "error": None},
        )
        if not isinstance(self.servers, dict):
            self.servers = {
                "count": 0,
                "updated_at": None,
                "servers": [],
                "error": None,
            }

        self.connectivity_lock = threading.RLock()
        self.connectivity_check_lock = threading.Lock()
        self.connectivity = {
            "google_dns": False,
            "cloudflare_dns": False,
            "checked_at": None,
        }
        self.connectivity_ready = threading.Event()

        self.stop_event = threading.Event()
        self.connected_event = threading.Event()
        self.command_queue: queue.Queue[str] = queue.Queue()
        self.pending_lock = threading.Lock()
        self.pending_commands: set[str] = set()

        self.mqtt = self._create_mqtt_client()
        self.threads: list[threading.Thread] = []

    def _create_mqtt_client(self) -> mqtt.Client:
        host = os.environ["MQTT_HOST"]
        port = int(os.environ.get("MQTT_PORT", "1883"))
        username = os.environ.get("MQTT_USER", "")
        password = os.environ.get("MQTT_PASSWORD", "")

        client = mqtt.Client(client_id=f"digitalhouses-speedtest-{DEVICE_ID}")
        if username:
            client.username_pw_set(username, password)
        client.will_set(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.connect_async(host, port, keepalive=60)
        return client

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict[str, Any],
        return_code: int,
    ) -> None:
        del userdata, flags
        if return_code != 0:
            self.log.error("MQTT connection failed with return code %s", return_code)
            return
        self.connected_event.set()
        self.log.info("Connected to MQTT broker")
        client.subscribe(COMMAND_TOPIC, qos=1)
        self.publish_discovery()
        self.publish_text(AVAILABILITY_TOPIC, "online", retain=True)
        self.publish_state()
        self.publish_connectivity()
        self.publish_servers()

    def _on_disconnect(
        self, client: mqtt.Client, userdata: Any, return_code: int
    ) -> None:
        del client, userdata
        self.connected_event.clear()
        if return_code:
            self.log.warning("MQTT connection lost; automatic reconnect is active")
        else:
            self.log.info("Disconnected from MQTT broker")

    def _on_message(
        self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage
    ) -> None:
        del client, userdata
        command = message.payload.decode("utf-8", errors="replace").strip().upper()
        if command not in {"RUN", "REFRESH_SERVERS"}:
            self.log.warning("Ignoring unsupported MQTT command: %s", command)
            return
        self.enqueue(command)

    def enqueue(self, command: str) -> None:
        with self.pending_lock:
            if command in self.pending_commands:
                self.log.info("Command %s is already pending or running", command)
                return
            self.pending_commands.add(command)
        self.command_queue.put(command)

    def command_finished(self, command: str) -> None:
        with self.pending_lock:
            self.pending_commands.discard(command)

    def publish_text(self, topic: str, payload: str, retain: bool = True) -> None:
        if not self.connected_event.is_set():
            return
        info = self.mqtt.publish(topic, payload, qos=1, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            self.log.warning("MQTT publish failed for %s with code %s", topic, info.rc)

    def publish_json(self, topic: str, payload: dict[str, Any], retain: bool = True) -> None:
        self.publish_text(
            topic,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=retain,
        )

    def publish_state(self) -> None:
        with self.state_lock:
            payload = dict(self.state)
        self.publish_json(STATE_TOPIC, payload)

    def save_and_publish_state(self, state: dict[str, Any]) -> None:
        with self.state_lock:
            self.state = state
            atomic_write_json(STATE_FILE, self.state)
        self.publish_state()

    def update_state(self, **changes: Any) -> None:
        with self.state_lock:
            state = dict(self.state)
            state.update(changes)
        self.save_and_publish_state(state)

    def publish_connectivity(self) -> None:
        with self.connectivity_lock:
            payload = dict(self.connectivity)
        self.publish_json(CONNECTIVITY_TOPIC, payload)

    def publish_servers(self) -> None:
        self.publish_json(SERVERS_TOPIC, self.servers)

    def publish_discovery(self) -> None:
        expire_after = self.options["expire_after_seconds"]
        measurement_expiry = {"expire_after": expire_after} if expire_after else {}
        device = {
            "identifiers": [DEVICE_ID],
            "name": DEVICE_NAME,
            "manufacturer": "DigitalHouses",
            "model": "Official Ookla Speedtest CLI",
            "sw_version": APP_VERSION,
        }
        components: dict[str, Any] = {
            "download": {
                "platform": "sensor",
                "name": "Download",
                "unique_id": f"{DEVICE_ID}_download",
                "default_entity_id": "sensor.internet_speed_download",
                "device_class": "data_rate",
                "state_class": "measurement",
                "unit_of_measurement": "Mbit/s",
                "suggested_display_precision": 1,
                "value_template": "{{ value_json.download_mbps }}",
                "icon": "mdi:download-network",
                **measurement_expiry,
            },
            "upload": {
                "platform": "sensor",
                "name": "Upload",
                "unique_id": f"{DEVICE_ID}_upload",
                "default_entity_id": "sensor.internet_speed_upload",
                "device_class": "data_rate",
                "state_class": "measurement",
                "unit_of_measurement": "Mbit/s",
                "suggested_display_precision": 1,
                "value_template": "{{ value_json.upload_mbps }}",
                "icon": "mdi:upload-network",
                **measurement_expiry,
            },
            "ping": {
                "platform": "sensor",
                "name": "Ping",
                "unique_id": f"{DEVICE_ID}_ping",
                "default_entity_id": "sensor.internet_speed_ping",
                "device_class": "duration",
                "state_class": "measurement",
                "unit_of_measurement": "ms",
                "suggested_display_precision": 1,
                "value_template": "{{ value_json.ping_ms }}",
                "icon": "mdi:timer-outline",
                **measurement_expiry,
            },
            "jitter": {
                "platform": "sensor",
                "name": "Jitter",
                "unique_id": f"{DEVICE_ID}_jitter",
                "default_entity_id": "sensor.internet_speed_jitter",
                "device_class": "duration",
                "state_class": "measurement",
                "unit_of_measurement": "ms",
                "suggested_display_precision": 1,
                "value_template": "{{ value_json.jitter_ms }}",
                "entity_category": "diagnostic",
                **measurement_expiry,
            },
            "packet_loss": {
                "platform": "sensor",
                "name": "Packet loss",
                "unique_id": f"{DEVICE_ID}_packet_loss",
                "default_entity_id": "sensor.internet_speed_packet_loss",
                "state_class": "measurement",
                "unit_of_measurement": "%",
                "suggested_display_precision": 1,
                "value_template": "{{ value_json.packet_loss }}",
                "entity_category": "diagnostic",
                "icon": "mdi:package-variant-remove",
                **measurement_expiry,
            },
            "status": {
                "platform": "sensor",
                "name": "Status",
                "unique_id": f"{DEVICE_ID}_status",
                "default_entity_id": "sensor.internet_speed_status",
                "device_class": "enum",
                "options": [
                    "Ready",
                    "Running",
                    "Success",
                    "Error",
                    "No connectivity",
                ],
                "value_template": "{{ value_json.status }}",
                "json_attributes_topic": STATE_TOPIC,
                "json_attributes_template": (
                    "{{ {'last_attempt': value_json.last_attempt, "
                    "'error': value_json.error} | tojson }}"
                ),
                "icon": "mdi:speedometer",
            },
            "server": {
                "platform": "sensor",
                "name": "Server",
                "unique_id": f"{DEVICE_ID}_server",
                "default_entity_id": "sensor.internet_speed_server",
                "value_template": "{{ value_json.server }}",
                "entity_category": "diagnostic",
                "icon": "mdi:server-network",
            },
            "server_id": {
                "platform": "sensor",
                "name": "Server ID",
                "unique_id": f"{DEVICE_ID}_server_id",
                "default_entity_id": "sensor.internet_speed_server_id",
                "value_template": "{{ value_json.server_id }}",
                "entity_category": "diagnostic",
                "icon": "mdi:identifier",
            },
            "provider": {
                "platform": "sensor",
                "name": "Provider",
                "unique_id": f"{DEVICE_ID}_provider",
                "default_entity_id": "sensor.internet_speed_provider",
                "value_template": "{{ value_json.provider }}",
                "entity_category": "diagnostic",
                "icon": "mdi:wan",
            },
            "external_ip": {
                "platform": "sensor",
                "name": "External IP",
                "unique_id": f"{DEVICE_ID}_external_ip",
                "default_entity_id": "sensor.internet_speed_external_ip",
                "value_template": "{{ value_json.external_ip }}",
                "entity_category": "diagnostic",
                "icon": "mdi:ip-network",
            },
            "last_test": {
                "platform": "sensor",
                "name": "Last successful test",
                "unique_id": f"{DEVICE_ID}_last_test",
                "default_entity_id": "sensor.internet_speed_last_test",
                "device_class": "timestamp",
                "value_template": "{{ value_json.last_success }}",
                "entity_category": "diagnostic",
                "icon": "mdi:clock-check-outline",
            },
            "result_url": {
                "platform": "sensor",
                "name": "Ookla result URL",
                "unique_id": f"{DEVICE_ID}_result_url",
                "default_entity_id": "sensor.internet_speed_result_url",
                "value_template": "{{ value_json.result_url }}",
                "entity_category": "diagnostic",
                "icon": "mdi:open-in-new",
            },
            "run_test": {
                "platform": "button",
                "name": "Run speed test",
                "unique_id": f"{DEVICE_ID}_run",
                "default_entity_id": "button.internet_speed_run",
                "command_topic": COMMAND_TOPIC,
                "payload_press": "RUN",
                "entity_category": "config",
                "icon": "mdi:play-speed",
            },
            "google_dns": {
                "platform": "binary_sensor",
                "name": "Google DNS connectivity",
                "unique_id": f"{DEVICE_ID}_google_dns_connectivity",
                "default_entity_id": "binary_sensor.internet_google_dns_connectivity",
                "device_class": "connectivity",
                "state_topic": CONNECTIVITY_TOPIC,
                "value_template": "{{ 'ON' if value_json.google_dns else 'OFF' }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "entity_category": "diagnostic",
            },
            "cloudflare_dns": {
                "platform": "binary_sensor",
                "name": "Cloudflare DNS connectivity",
                "unique_id": f"{DEVICE_ID}_cloudflare_dns_connectivity",
                "default_entity_id": "binary_sensor.internet_cloudflare_dns_connectivity",
                "device_class": "connectivity",
                "state_topic": CONNECTIVITY_TOPIC,
                "value_template": "{{ 'ON' if value_json.cloudflare_dns else 'OFF' }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "entity_category": "diagnostic",
            },
            "available_servers": {
                "platform": "sensor",
                "name": "Available Speedtest servers",
                "unique_id": f"{DEVICE_ID}_available_servers",
                "default_entity_id": "sensor.internet_speed_available_servers",
                "state_topic": SERVERS_TOPIC,
                "value_template": "{{ value_json.count }}",
                "unit_of_measurement": "servers",
                "json_attributes_topic": SERVERS_TOPIC,
                "json_attributes_template": (
                    "{{ {'updated_at': value_json.updated_at, "
                    "'servers': value_json.servers, "
                    "'error': value_json.error} | tojson }}"
                ),
                "entity_category": "diagnostic",
                "icon": "mdi:server-plus",
            },
            "server_list_updated": {
                "platform": "sensor",
                "name": "Server list updated",
                "unique_id": f"{DEVICE_ID}_server_list_updated",
                "default_entity_id": "sensor.internet_speed_server_list_updated",
                "device_class": "timestamp",
                "state_topic": SERVERS_TOPIC,
                "value_template": "{{ value_json.updated_at or '' }}",
                "entity_category": "diagnostic",
                "icon": "mdi:clock-refresh-outline",
            },
            "refresh_servers": {
                "platform": "button",
                "name": "Refresh server list",
                "unique_id": f"{DEVICE_ID}_refresh_servers",
                "default_entity_id": "button.internet_speed_refresh_servers",
                "command_topic": COMMAND_TOPIC,
                "payload_press": "REFRESH_SERVERS",
                "entity_category": "config",
                "icon": "mdi:refresh",
            },
        }

        for component in components.values():
            if component.get("platform") == "sensor":
                component.setdefault("state_topic", STATE_TOPIC)

        discovery = {
            "device": device,
            "origin": {
                "name": "DigitalHouses Speedtest App",
                "sw_version": APP_VERSION,
            },
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
            "components": components,
        }
        self.publish_json(DISCOVERY_TOPIC, discovery)

    def _ping(self, target: str) -> bool:
        settings = self.options["connectivity_check"]
        attempts = settings["attempts"]
        timeout = settings["timeout_seconds"]
        process_timeout = attempts * (timeout + 1) + 2
        try:
            result = subprocess.run(
                ["ping", "-n", "-c", str(attempts), "-W", str(timeout), target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=process_timeout,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def check_connectivity_once(self) -> dict[str, Any]:
        with self.connectivity_check_lock:
            with ThreadPoolExecutor(max_workers=2) as executor:
                google_future = executor.submit(self._ping, GOOGLE_DNS)
                cloudflare_future = executor.submit(self._ping, CLOUDFLARE_DNS)
                result = {
                    "google_dns": google_future.result(),
                    "cloudflare_dns": cloudflare_future.result(),
                    "checked_at": utc_now(),
                }
            with self.connectivity_lock:
                previous_any = bool(
                    self.connectivity["google_dns"]
                    or self.connectivity["cloudflare_dns"]
                )
                self.connectivity = result
            self.connectivity_ready.set()
            self.publish_connectivity()

            current_any = result["google_dns"] or result["cloudflare_dns"]
            if current_any != previous_any:
                self.log.info(
                    "Internet connectivity is %s",
                    "available" if current_any else "unavailable",
                )
            if current_any:
                with self.state_lock:
                    restore_ready = self.state.get("status") == "No connectivity"
                if restore_ready:
                    self.update_state(status="Ready", error=None)
            return result

    def connectivity_loop(self) -> None:
        interval = self.options["connectivity_check"]["interval_seconds"]
        while not self.stop_event.is_set():
            result = self.check_connectivity_once()
            if (
                (result["google_dns"] or result["cloudflare_dns"])
                and not self.servers.get("updated_at")
            ):
                self.enqueue("REFRESH_SERVERS")
            if self.stop_event.wait(interval):
                break

    def periodic_loop(self) -> None:
        if not self.options["periodic_test_enabled"]:
            self.log.info("Periodic speed tests are disabled")
            return
        interval = self.options["periodic_test_interval_minutes"] * 60
        self.log.info(
            "Periodic speed tests are enabled every %s minutes",
            self.options["periodic_test_interval_minutes"],
        )
        next_run = time.monotonic() + interval
        while not self.stop_event.is_set():
            remaining = max(0.0, next_run - time.monotonic())
            if self.stop_event.wait(min(remaining, 1.0)):
                break
            if time.monotonic() >= next_run:
                self.enqueue("RUN")
                next_run = time.monotonic() + interval

    def has_connectivity(self) -> bool:
        with self.connectivity_lock:
            return bool(
                self.connectivity["google_dns"]
                or self.connectivity["cloudflare_dns"]
            )

    def run_speedtest_candidate(self, server_id: int | None) -> dict[str, Any]:
        args = [
            "speedtest",
            "--accept-license",
            "--accept-gdpr",
            "--format=json",
            "--progress=no",
        ]
        if server_id is not None:
            args.append(f"--server-id={server_id}")
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.options["speedtest_timeout_seconds"],
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Ookla Speedtest timed out after {self.options['speedtest_timeout_seconds']} seconds"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Unable to start Ookla Speedtest: {exc}") from exc

        if completed.returncode != 0:
            message = " ".join(completed.stderr.split())[-900:]
            raise RuntimeError(message or f"Ookla Speedtest exited with code {completed.returncode}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ookla Speedtest returned invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("type") != "result":
            raise RuntimeError("Ookla Speedtest did not return a result object")
        for path in (("download", "bandwidth"), ("upload", "bandwidth"), ("ping", "latency")):
            section, key = path
            if not isinstance(payload.get(section), dict) or payload[section].get(key) is None:
                raise RuntimeError(f"Ookla result is missing {section}.{key}")
        return payload

    def run_speedtest(self) -> None:
        connectivity = self.check_connectivity_once()
        if not (connectivity["google_dns"] or connectivity["cloudflare_dns"]):
            attempted_at = utc_now()
            self.update_state(
                status="No connectivity",
                last_attempt=attempted_at,
                error=(
                    "Speedtest skipped because both 8.8.8.8 and 1.1.1.1 "
                    "are unreachable"
                ),
            )
            self.log.warning("Speedtest skipped: both connectivity targets are unreachable")
            return

        attempted_at = utc_now()
        self.update_state(status="Running", last_attempt=attempted_at, error=None)

        candidates: list[int | None] = list(self.options["server_ids"])
        if not candidates or self.options["automatic_server_fallback"]:
            candidates.append(None)

        errors: list[str] = []
        for candidate in candidates:
            selection = "automatic selection" if candidate is None else f"server ID {candidate}"
            self.log.info("Running Ookla Speedtest using %s", selection)
            try:
                raw = self.run_speedtest_candidate(candidate)
                state = build_success_state(raw, attempted_at)
                self.save_and_publish_state(state)
                self.log.info(
                    "Speedtest completed: download %.1f Mbit/s, upload %.1f Mbit/s, ping %.1f ms",
                    state["download_mbps"],
                    state["upload_mbps"],
                    state["ping_ms"],
                )
                return
            except RuntimeError as exc:
                error = f"{selection}: {exc}"
                errors.append(error)
                self.log.warning("Speedtest attempt failed: %s", error)

        message = " | ".join(errors)[-1800:] or "Ookla Speedtest did not return a result"
        self.update_state(status="Error", last_attempt=attempted_at, error=message)
        self.log.error("All Speedtest attempts failed")

    def refresh_servers(self) -> None:
        connectivity = self.check_connectivity_once()
        if not (connectivity["google_dns"] or connectivity["cloudflare_dns"]):
            self.log.warning("Server list refresh skipped: no connectivity")
            self.servers["error"] = (
                "Server list refresh skipped because both connectivity targets are unreachable"
            )
            atomic_write_json(SERVERS_FILE, self.servers)
            self.publish_servers()
            return

        self.log.info("Refreshing nearby Ookla Speedtest servers")
        try:
            completed = subprocess.run(
                ["speedtest", "--accept-license", "--accept-gdpr", "--servers"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._server_refresh_failed(str(exc))
            return

        if completed.returncode != 0:
            self._server_refresh_failed(
                " ".join(completed.stderr.split())[-900:]
                or f"Ookla Speedtest exited with code {completed.returncode}"
            )
            return

        servers = parse_server_list(completed.stdout)
        if not servers:
            self._server_refresh_failed("Unable to parse the Ookla server list")
            self.log.debug("Unparsed server list output:\n%s", completed.stdout)
            return

        self.servers = {
            "count": len(servers),
            "updated_at": utc_now(),
            "servers": servers,
            "error": None,
        }
        atomic_write_json(SERVERS_FILE, self.servers)
        self.publish_servers()
        self.log.info("Available Ookla Speedtest servers:")
        for server in servers:
            place = ", ".join(
                item for item in (server["location"], server["country"]) if item
            )
            self.log.info("  %s | %s | %s", server["id"], server["provider"], place)
        self.log.info("Copy the required IDs into the server_ids App option")

    def _server_refresh_failed(self, message: str) -> None:
        self.log.error("Unable to refresh the Ookla server list: %s", message)
        self.servers["error"] = message
        atomic_write_json(SERVERS_FILE, self.servers)
        self.publish_servers()

    def worker_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                command = self.command_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                if command == "RUN":
                    self.run_speedtest()
                elif command == "REFRESH_SERVERS":
                    self.refresh_servers()
            except Exception:
                self.log.exception("Unhandled error while processing command %s", command)
                if command == "RUN":
                    self.update_state(status="Error", error="Unhandled internal App error")
            finally:
                self.command_finished(command)
                self.command_queue.task_done()

    def start(self) -> None:
        self.log.info("DigitalHouses Speedtest %s starting", APP_VERSION)
        self.log.info("Configured server IDs: %s", self.options["server_ids"] or "automatic")
        self.mqtt.loop_start()

        for name, target in (
            ("connectivity", self.connectivity_loop),
            ("periodic", self.periodic_loop),
            ("worker", self.worker_loop),
        ):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self.threads.append(thread)

        while not self.stop_event.wait(1):
            pass

    def shutdown(self) -> None:
        if self.stop_event.is_set():
            return
        self.log.info("Stopping DigitalHouses Speedtest")
        self.stop_event.set()
        if self.connected_event.is_set():
            self.publish_text(AVAILABILITY_TOPIC, "offline", retain=True)
            time.sleep(0.2)
        self.mqtt.disconnect()
        self.mqtt.loop_stop()


def main() -> None:
    app = SpeedtestApp()

    def stop_handler(signum: int, frame: Any) -> None:
        del signum, frame
        app.shutdown()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    try:
        app.start()
    finally:
        app.shutdown()


if __name__ == "__main__":
    main()
