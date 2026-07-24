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
    append_recent_result,
    atomic_write_json,
    build_recent_record,
    build_success_state,
    default_recent_results,
    default_state,
    evaluate_performance,
    is_result_fresh,
    load_json,
    migrate_recent_results,
    migrate_state,
    normalize_thresholds,
    parse_server_list,
    recent_results_payload,
    update_runtime_status,
    utc_now,
)
from discovery import build_discovery_payload

APP_VERSION = os.getenv("APP_VERSION", "1.1.0-local")

DATA_DIR = Path("/data")
OPTIONS_FILE = DATA_DIR / "options.json"
STATE_FILE = DATA_DIR / "state.json"
SERVERS_FILE = DATA_DIR / "servers.json"
THRESHOLDS_FILE = DATA_DIR / "thresholds.json"
RECENT_RESULTS_FILE = DATA_DIR / "recent_results.json"

MQTT_BASE_TOPIC = "DigitalHouses/Global/speedtest"
DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = "digitalhouses_global_speedtest"

STATE_TOPIC = f"{MQTT_BASE_TOPIC}/state"
COMMAND_TOPIC = f"{MQTT_BASE_TOPIC}/command"
APP_AVAILABILITY_TOPIC = f"{MQTT_BASE_TOPIC}/availability"
RESULT_AVAILABILITY_TOPIC = f"{MQTT_BASE_TOPIC}/result_availability"
CONNECTIVITY_TOPIC = f"{MQTT_BASE_TOPIC}/connectivity"
SERVERS_TOPIC = f"{MQTT_BASE_TOPIC}/servers"
THRESHOLDS_TOPIC = f"{MQTT_BASE_TOPIC}/thresholds"
PROBLEMS_TOPIC = f"{MQTT_BASE_TOPIC}/problems"
RECENT_RESULTS_TOPIC = f"{MQTT_BASE_TOPIC}/recent_results"

MINIMUM_DOWNLOAD_COMMAND_TOPIC = f"{THRESHOLDS_TOPIC}/minimum_download/set"
MINIMUM_UPLOAD_COMMAND_TOPIC = f"{THRESHOLDS_TOPIC}/minimum_upload/set"
MAXIMUM_PING_COMMAND_TOPIC = f"{THRESHOLDS_TOPIC}/maximum_ping/set"

DISCOVERY_TOPIC = f"{DISCOVERY_PREFIX}/device/{DEVICE_ID}/config"

GOOGLE_DNS = "8.8.8.8"
CLOUDFLARE_DNS = "1.1.1.1"

DEFAULT_OPTIONS: dict[str, Any] = {
    "periodic_test_enabled": True,
    "periodic_test_interval_minutes": 30,
    "server_ids": [],
    "automatic_server_fallback": True,
    "speedtest_timeout_seconds": 240,
    "connectivity_check": {
        "interval_seconds": 60,
        "attempts": 3,
        "timeout_seconds": 2,
    },
    "expire_after_seconds": 14400,
    "recent_results_limit": 20,
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
    server_values = raw.get("server_ids", [])
    if not isinstance(server_values, list):
        server_values = []
    for value in server_values:
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
            raw.get(
                "periodic_test_enabled",
                DEFAULT_OPTIONS["periodic_test_enabled"],
            )
        ),
        "periodic_test_interval_minutes": _bounded_int(
            raw.get("periodic_test_interval_minutes"),
            5,
            720,
            30,
        ),
        "server_ids": ids,
        "automatic_server_fallback": bool(
            raw.get(
                "automatic_server_fallback",
                DEFAULT_OPTIONS["automatic_server_fallback"],
            )
        ),
        "speedtest_timeout_seconds": _bounded_int(
            raw.get("speedtest_timeout_seconds"),
            30,
            600,
            240,
        ),
        "connectivity_check": {
            "interval_seconds": _bounded_int(
                connectivity.get("interval_seconds"),
                10,
                3600,
                60,
            ),
            "attempts": _bounded_int(
                connectivity.get("attempts"),
                1,
                10,
                3,
            ),
            "timeout_seconds": _bounded_int(
                connectivity.get("timeout_seconds"),
                1,
                30,
                2,
            ),
        },
        "expire_after_seconds": _bounded_int(
            raw.get("expire_after_seconds"),
            0,
            86400,
            14400,
        ),
        "recent_results_limit": _bounded_int(
            raw.get("recent_results_limit"),
            5,
            50,
            20,
        ),
        "log_level": level,
    }


class SpeedtestApp:
    """Long-running MQTT bridge, scheduler, persistence and interpretation."""

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

        self.servers_lock = threading.RLock()
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

        self.thresholds_lock = threading.RLock()
        self.thresholds = normalize_thresholds(load_json(THRESHOLDS_FILE, {}))
        atomic_write_json(THRESHOLDS_FILE, self.thresholds)

        self.recent_results_lock = threading.RLock()
        self.recent_results = migrate_recent_results(
            load_json(RECENT_RESULTS_FILE, default_recent_results()),
            self.options["recent_results_limit"],
        )
        atomic_write_json(RECENT_RESULTS_FILE, self.recent_results)

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

        self.result_availability_lock = threading.Lock()
        self.last_result_availability: bool | None = None

        self.mqtt = self._create_mqtt_client()
        self.threads: list[threading.Thread] = []

    @property
    def topics(self) -> dict[str, str]:
        return {
            "state": STATE_TOPIC,
            "command": COMMAND_TOPIC,
            "app_availability": APP_AVAILABILITY_TOPIC,
            "result_availability": RESULT_AVAILABILITY_TOPIC,
            "connectivity": CONNECTIVITY_TOPIC,
            "servers": SERVERS_TOPIC,
            "thresholds": THRESHOLDS_TOPIC,
            "problems": PROBLEMS_TOPIC,
            "recent_results": RECENT_RESULTS_TOPIC,
            "minimum_download_command": MINIMUM_DOWNLOAD_COMMAND_TOPIC,
            "minimum_upload_command": MINIMUM_UPLOAD_COMMAND_TOPIC,
            "maximum_ping_command": MAXIMUM_PING_COMMAND_TOPIC,
        }

    def _create_mqtt_client(self) -> mqtt.Client:
        host = os.environ["MQTT_HOST"]
        port = int(os.environ.get("MQTT_PORT", "1883"))
        username = os.environ.get("MQTT_USER", "")
        password = os.environ.get("MQTT_PASSWORD", "")

        client = mqtt.Client(client_id=f"digitalhouses-speedtest-{DEVICE_ID}")
        if username:
            client.username_pw_set(username, password)

        client.will_set(
            APP_AVAILABILITY_TOPIC,
            "offline",
            qos=1,
            retain=True,
        )
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
            self.log.error(
                "MQTT connection failed with return code %s",
                return_code,
            )
            return

        self.connected_event.set()
        self.log.info("Connected to MQTT broker")

        client.subscribe(COMMAND_TOPIC, qos=1)
        client.subscribe(MINIMUM_DOWNLOAD_COMMAND_TOPIC, qos=1)
        client.subscribe(MINIMUM_UPLOAD_COMMAND_TOPIC, qos=1)
        client.subscribe(MAXIMUM_PING_COMMAND_TOPIC, qos=1)

        # Publish all retained data while global availability is still offline.
        # This prevents stale values briefly appearing as current after restart.
        self.publish_discovery()
        self.publish_state()
        self.publish_connectivity()
        self.publish_servers()
        self.publish_thresholds()
        self.publish_recent_results()
        self.publish_evaluation(force_availability=True)
        self.publish_text(APP_AVAILABILITY_TOPIC, "online", retain=True)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        return_code: int,
    ) -> None:
        del client, userdata
        self.connected_event.clear()
        if return_code:
            self.log.warning(
                "MQTT connection lost; automatic reconnect is active"
            )
        else:
            self.log.info("Disconnected from MQTT broker")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        del client, userdata

        if message.topic in {
            MINIMUM_DOWNLOAD_COMMAND_TOPIC,
            MINIMUM_UPLOAD_COMMAND_TOPIC,
            MAXIMUM_PING_COMMAND_TOPIC,
        }:
            self.handle_threshold_command(message.topic, message.payload)
            return

        command = (
            message.payload.decode("utf-8", errors="replace").strip().upper()
        )
        if command not in {"RUN", "REFRESH_SERVERS"}:
            self.log.warning("Ignoring unsupported MQTT command: %s", command)
            return
        self.enqueue(command)

    def enqueue(self, command: str) -> None:
        with self.pending_lock:
            if command in self.pending_commands:
                self.log.info(
                    "Command %s is already pending or running",
                    command,
                )
                return
            self.pending_commands.add(command)
        self.command_queue.put(command)

    def command_finished(self, command: str) -> None:
        with self.pending_lock:
            self.pending_commands.discard(command)

    def publish_text(
        self,
        topic: str,
        payload: str,
        retain: bool = True,
    ) -> None:
        if not self.connected_event.is_set():
            return
        info = self.mqtt.publish(
            topic,
            payload,
            qos=1,
            retain=retain,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            self.log.warning(
                "MQTT publish failed for %s with code %s",
                topic,
                info.rc,
            )

    def publish_json(
        self,
        topic: str,
        payload: dict[str, Any],
        retain: bool = True,
    ) -> None:
        self.publish_text(
            topic,
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            retain=retain,
        )

    def publish_discovery(self) -> None:
        discovery = build_discovery_payload(
            app_version=APP_VERSION,
            expire_after_seconds=self.options["expire_after_seconds"],
            topics=self.topics,
        )
        self.publish_json(DISCOVERY_TOPIC, discovery)

    def publish_state(self) -> None:
        with self.state_lock:
            payload = dict(self.state)
        self.publish_json(STATE_TOPIC, payload)

    def save_and_publish_state(self, state: dict[str, Any]) -> None:
        with self.state_lock:
            self.state = migrate_state(state)
            atomic_write_json(STATE_FILE, self.state)
            payload = dict(self.state)
        self.publish_json(STATE_TOPIC, payload)

    def update_status(
        self,
        status: str,
        *,
        attempted_at: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.state_lock:
            updated = update_runtime_status(
                self.state,
                status,
                attempted_at,
                error,
            )
        self.save_and_publish_state(updated)

    def publish_connectivity(self) -> None:
        with self.connectivity_lock:
            payload = dict(self.connectivity)
        self.publish_json(CONNECTIVITY_TOPIC, payload)

    def publish_servers(self) -> None:
        with self.servers_lock:
            payload = dict(self.servers)
        self.publish_json(SERVERS_TOPIC, payload)

    def publish_thresholds(self) -> None:
        with self.thresholds_lock:
            payload = dict(self.thresholds)
        self.publish_json(THRESHOLDS_TOPIC, payload)

    def publish_recent_results(self) -> None:
        with self.recent_results_lock:
            payload = recent_results_payload(
                self.recent_results,
                self.options["recent_results_limit"],
            )
        self.publish_json(RECENT_RESULTS_TOPIC, payload)

    def current_result_is_fresh(self) -> bool:
        with self.state_lock:
            last_success = self.state.get("last_success")
        return is_result_fresh(
            last_success,
            self.options["expire_after_seconds"],
        )

    def publish_evaluation(
        self,
        *,
        force_availability: bool = False,
    ) -> None:
        fresh = self.current_result_is_fresh()
        with self.state_lock:
            state = dict(self.state)
        with self.thresholds_lock:
            thresholds = dict(self.thresholds)

        evaluation = evaluate_performance(
            state,
            thresholds,
            available=fresh,
        )
        self.publish_json(PROBLEMS_TOPIC, evaluation)

        result_available = bool(evaluation["available"])
        with self.result_availability_lock:
            changed = self.last_result_availability is not result_available
            if changed or force_availability:
                self.publish_text(
                    RESULT_AVAILABILITY_TOPIC,
                    "online" if result_available else "offline",
                    retain=True,
                )
                self.last_result_availability = result_available

    def current_result_is_available(self) -> bool:
        """Return whether the persisted result is both complete and fresh."""
        fresh = self.current_result_is_fresh()
        with self.state_lock:
            state = dict(self.state)
        with self.thresholds_lock:
            thresholds = dict(self.thresholds)
        evaluation = evaluate_performance(
            state,
            thresholds,
            available=fresh,
        )
        return bool(evaluation["available"])

    def freshness_loop(self) -> None:
        while not self.stop_event.wait(15):
            current = self.current_result_is_available()
            with self.result_availability_lock:
                changed = self.last_result_availability is not current
            if changed:
                self.publish_evaluation(force_availability=True)
                if not current:
                    self.log.info(
                        "Last successful Speedtest result expired or is incomplete; "
                        "measurement and problem entities are unavailable"
                    )

    def handle_threshold_command(
        self,
        topic: str,
        raw_payload: bytes,
    ) -> None:
        mapping = {
            MINIMUM_DOWNLOAD_COMMAND_TOPIC: (
                "minimum_download_mbps",
                1.0,
                10_000.0,
            ),
            MINIMUM_UPLOAD_COMMAND_TOPIC: (
                "minimum_upload_mbps",
                1.0,
                10_000.0,
            ),
            MAXIMUM_PING_COMMAND_TOPIC: (
                "maximum_ping_ms",
                1.0,
                1_000.0,
            ),
        }
        key, minimum, maximum = mapping[topic]

        try:
            value = float(
                raw_payload.decode("utf-8", errors="strict").strip()
            )
        except (UnicodeDecodeError, ValueError):
            self.log.warning(
                "Ignoring invalid threshold payload on %s",
                topic,
            )
            self.publish_thresholds()
            return

        if not minimum <= value <= maximum:
            self.log.warning(
                "Ignoring out-of-range threshold %s=%s",
                key,
                value,
            )
            self.publish_thresholds()
            return

        compact: int | float = int(value) if value.is_integer() else round(value, 3)
        with self.thresholds_lock:
            self.thresholds[key] = compact
            atomic_write_json(THRESHOLDS_FILE, self.thresholds)

        self.log.info("Threshold changed: %s=%s", key, compact)
        self.publish_thresholds()

        # Immediate recalculation against the last successful measurement.
        # Historical Recent Results are deliberately not rewritten.
        self.publish_evaluation(force_availability=True)

    def _ping(self, target: str) -> bool:
        settings = self.options["connectivity_check"]
        attempts = settings["attempts"]
        timeout = settings["timeout_seconds"]
        process_timeout = attempts * (timeout + 1) + 2

        try:
            result = subprocess.run(
                [
                    "ping",
                    "-n",
                    "-c",
                    str(attempts),
                    "-W",
                    str(timeout),
                    target,
                ],
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
                cloudflare_future = executor.submit(
                    self._ping,
                    CLOUDFLARE_DNS,
                )
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

            current_any = bool(
                result["google_dns"] or result["cloudflare_dns"]
            )
            if current_any != previous_any:
                self.log.info(
                    "Internet connectivity is %s",
                    "available" if current_any else "unavailable",
                )

            if current_any:
                with self.state_lock:
                    restore_ready = (
                        self.state.get("status") == "No connectivity"
                    )
                if restore_ready:
                    self.update_status("Ready", error=None)

            return result

    def connectivity_loop(self) -> None:
        interval = self.options["connectivity_check"]["interval_seconds"]
        while not self.stop_event.is_set():
            result = self.check_connectivity_once()

            with self.servers_lock:
                servers_missing = not self.servers.get("updated_at")

            if (
                result["google_dns"] or result["cloudflare_dns"]
            ) and servers_missing:
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

    def run_speedtest_candidate(
        self,
        server_id: int | None,
    ) -> dict[str, Any]:
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
                "Ookla Speedtest timed out after "
                f"{self.options['speedtest_timeout_seconds']} seconds"
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"Unable to start Ookla Speedtest: {exc}"
            ) from exc

        if completed.returncode != 0:
            message = " ".join(completed.stderr.split())[-900:]
            raise RuntimeError(
                message
                or (
                    "Ookla Speedtest exited with code "
                    f"{completed.returncode}"
                )
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Ookla Speedtest returned invalid JSON"
            ) from exc

        if not isinstance(payload, dict) or payload.get("type") != "result":
            raise RuntimeError(
                "Ookla Speedtest did not return a result object"
            )

        for section, key in (
            ("download", "bandwidth"),
            ("upload", "bandwidth"),
            ("ping", "latency"),
        ):
            if (
                not isinstance(payload.get(section), dict)
                or payload[section].get(key) is None
            ):
                raise RuntimeError(
                    f"Ookla result is missing {section}.{key}"
                )

        return payload

    def run_speedtest(self) -> None:
        connectivity = self.check_connectivity_once()
        if not (
            connectivity["google_dns"]
            or connectivity["cloudflare_dns"]
        ):
            attempted_at = utc_now()
            self.update_status(
                "No connectivity",
                attempted_at=attempted_at,
                error=(
                    "Speedtest skipped because both 8.8.8.8 and "
                    "1.1.1.1 are unreachable"
                ),
            )
            self.log.warning(
                "Speedtest skipped: both connectivity targets are unreachable"
            )
            # Existing measurements and problem evaluation are preserved.
            return

        attempted_at = utc_now()
        self.update_status(
            "Running",
            attempted_at=attempted_at,
            error=None,
        )

        candidates: list[int | None] = list(self.options["server_ids"])
        if (
            not candidates
            or self.options["automatic_server_fallback"]
        ):
            candidates.append(None)

        errors: list[str] = []
        for candidate in candidates:
            selection = (
                "automatic selection"
                if candidate is None
                else f"server ID {candidate}"
            )
            self.log.info(
                "Running Ookla Speedtest using %s",
                selection,
            )
            try:
                raw = self.run_speedtest_candidate(candidate)
                state = build_success_state(raw, attempted_at)
                self.save_and_publish_state(state)

                with self.thresholds_lock:
                    threshold_snapshot = dict(self.thresholds)
                record = build_recent_record(
                    state,
                    threshold_snapshot,
                )
                with self.recent_results_lock:
                    self.recent_results = append_recent_result(
                        self.recent_results,
                        record,
                        self.options["recent_results_limit"],
                    )
                    atomic_write_json(
                        RECENT_RESULTS_FILE,
                        self.recent_results,
                    )

                self.publish_recent_results()
                self.publish_evaluation(force_availability=True)

                self.log.info(
                    "Speedtest completed: download %.1f Mbit/s, "
                    "upload %.1f Mbit/s, ping %.1f ms",
                    state["download_mbps"],
                    state["upload_mbps"],
                    state["ping_ms"],
                )
                return
            except RuntimeError as exc:
                error = f"{selection}: {exc}"
                errors.append(error)
                self.log.warning(
                    "Speedtest attempt failed: %s",
                    error,
                )

        message = (
            " | ".join(errors)[-1800:]
            or "Ookla Speedtest did not return a result"
        )
        self.update_status(
            "Error",
            attempted_at=attempted_at,
            error=message,
        )
        self.log.error("All Speedtest attempts failed")
        # Failed tests do not add Recent Results and do not invent a new
        # performance evaluation.

    def refresh_servers(self) -> None:
        connectivity = self.check_connectivity_once()
        if not (
            connectivity["google_dns"]
            or connectivity["cloudflare_dns"]
        ):
            self.log.warning(
                "Server list refresh skipped: no connectivity"
            )
            with self.servers_lock:
                self.servers["error"] = (
                    "Server list refresh skipped because both "
                    "connectivity targets are unreachable"
                )
                atomic_write_json(SERVERS_FILE, self.servers)
            self.publish_servers()
            return

        self.log.info("Refreshing nearby Ookla Speedtest servers")
        try:
            completed = subprocess.run(
                [
                    "speedtest",
                    "--accept-license",
                    "--accept-gdpr",
                    "--servers",
                ],
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
                or (
                    "Ookla Speedtest exited with code "
                    f"{completed.returncode}"
                )
            )
            return

        servers = parse_server_list(completed.stdout)
        if not servers:
            self._server_refresh_failed(
                "Unable to parse the Ookla server list"
            )
            self.log.debug(
                "Unparsed server list output:\n%s",
                completed.stdout,
            )
            return

        with self.servers_lock:
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
                item
                for item in (
                    server["location"],
                    server["country"],
                )
                if item
            )
            self.log.info(
                "  %s | %s | %s",
                server["id"],
                server["provider"],
                place,
            )
        self.log.info(
            "Copy the required IDs into the server_ids App option"
        )

    def _server_refresh_failed(self, message: str) -> None:
        self.log.error(
            "Unable to refresh the Ookla server list: %s",
            message,
        )
        with self.servers_lock:
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
                self.log.exception(
                    "Unhandled error while processing command %s",
                    command,
                )
                if command == "RUN":
                    self.update_status(
                        "Error",
                        error="Unhandled internal App error",
                    )
            finally:
                self.command_finished(command)
                self.command_queue.task_done()

    def start(self) -> None:
        self.log.info(
            "DigitalHouses Speedtest %s starting",
            APP_VERSION,
        )
        self.log.info(
            "Configured server IDs: %s",
            self.options["server_ids"] or "automatic",
        )
        self.log.info(
            "Thresholds: download >= %s Mbit/s, "
            "upload >= %s Mbit/s, ping <= %s ms",
            self.thresholds["minimum_download_mbps"],
            self.thresholds["minimum_upload_mbps"],
            self.thresholds["maximum_ping_ms"],
        )

        self.mqtt.loop_start()

        for name, target in (
            ("connectivity", self.connectivity_loop),
            ("periodic", self.periodic_loop),
            ("freshness", self.freshness_loop),
            ("worker", self.worker_loop),
        ):
            thread = threading.Thread(
                target=target,
                name=name,
                daemon=True,
            )
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
            self.publish_text(
                APP_AVAILABILITY_TOPIC,
                "offline",
                retain=True,
            )
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
