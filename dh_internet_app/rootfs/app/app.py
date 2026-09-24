"""DigitalHouses Internet App runtime."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from config import AppConfig, ConfigError, load_config
from connectivity import ConnectivitySnapshot, sample
from discovery import (
    DISCOVERY_TOPIC,
    DEVICE_ID,
    EVENT_SCHEMA_VERSION,
    TOPICS,
    build_discovery_payload,
)
from ha_api import HomeAssistantApi
from quality import (
    evaluate_performance,
    load_thresholds,
    set_threshold,
)
from recent_results import (
    append_recent_result,
    build_recent_record,
    load_recent_results,
    recent_results_payload,
    save_recent_results,
)
from recovery import (
    RecoveryExecutor,
    RecoveryStopped,
    choose_targets,
    target_by_name,
)
from speedtest import (
    list_servers,
    load_last_result,
    load_servers_state,
    run_speedtest,
    save_last_result,
    save_servers_state,
)
from state import (
    OutageTracker,
    atomic_write_json,
    iso,
    load_recovery_stopped,
    now_local,
    save_recovery_stopped,
)
from traffic import (
    entity_rate_mbps,
    entity_total_bytes,
    load_traffic_state,
    save_traffic_state,
    traffic_payload,
    update_traffic,
)

APP_VERSION = os.getenv("APP_VERSION", "0.1.0-local")
OUTAGES_FILE = Path("/data/runtime/outages.json")
SPEEDTEST_FILE = Path("/data/runtime/speedtest.json")
THRESHOLDS_FILE = Path("/data/runtime/thresholds.json")
TRAFFIC_FILE = Path("/data/runtime/traffic.json")
TRAFFIC_POLL_SECONDS = 60
RECENT_RESULTS_FILE = Path("/data/runtime/recent_results.json")
SERVERS_FILE = Path("/data/runtime/servers.json")
RECOVERY_STATE_FILE = Path("/data/runtime/recovery.json")


class InternetApp:
    def __init__(self) -> None:
        self.config: AppConfig = load_config()
        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper()),
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.log = logging.getLogger("digitalhouses_internet")
        self.started_at = iso(now_local())

        self.stop_app = threading.Event()
        self.stop_recovery = threading.Event()
        self.recovery_thread: threading.Thread | None = None
        self.lock = threading.RLock()
        self.speedtest_lock = threading.Lock()

        self.snapshot = ConnectivitySnapshot(False, False)
        self.failure_count = 0
        self.incident_active = False
        self.recovery_state = "idle"
        self.recovery_cycle = 0
        self.recovery_countdown = 0

        self.outages = OutageTracker.load(OUTAGES_FILE)
        self.incident_active = self.outages.active_from is not None
        recovery_stopped = load_recovery_stopped(RECOVERY_STATE_FILE)
        if self.incident_active and recovery_stopped:
            self.stop_recovery.set()
            self.recovery_state = "stopped"
        elif recovery_stopped:
            save_recovery_stopped(RECOVERY_STATE_FILE, False)
        self.speedtest = load_last_result(SPEEDTEST_FILE)
        self.thresholds = load_thresholds(THRESHOLDS_FILE)
        self.recent_results = load_recent_results(RECENT_RESULTS_FILE)
        self.servers = load_servers_state(SERVERS_FILE)
        self.performance = evaluate_performance(
            self.speedtest, self.thresholds
        )
        self.traffic = load_traffic_state(
            TRAFFIC_FILE,
            self.config.traffic.traffic_download_total,
            self.config.traffic.traffic_upload_total,
        )
        self.traffic_available = False
        self.router_telemetry: dict[str, Any] = {
            "wan_status": None,
            "download_rate_mbps": None,
            "upload_rate_mbps": None,
        }
        self.ha_api = HomeAssistantApi()

        self.mqtt = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=DEVICE_ID,
        )
        username = os.getenv("MQTT_USER", "")
        password = os.getenv("MQTT_PASSWORD", "")
        if username:
            self.mqtt.username_pw_set(username, password)
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message
        self.mqtt.will_set(
            TOPICS["availability"], payload="offline", qos=1, retain=True
        )

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        del userdata, flags, properties
        if reason_code != 0:
            self.log.error("MQTT connection failed: %s", reason_code)
            return
        client.subscribe(TOPICS["command"], qos=1)
        client.subscribe(TOPICS["minimum_download_command"], qos=1)
        client.subscribe(TOPICS["minimum_upload_command"], qos=1)
        client.subscribe(TOPICS["maximum_ping_command"], qos=1)
        client.publish(
            DISCOVERY_TOPIC,
            json.dumps(
                build_discovery_payload(
                    APP_VERSION,
                    traffic_enabled=self.config.traffic.enabled,
                    wan_enabled=bool(self.config.traffic.router_wan_status),
                    download_rate_enabled=bool(
                        self.config.traffic.router_download_rate
                    ),
                    upload_rate_enabled=bool(
                        self.config.traffic.router_upload_rate
                    ),
                )
            ),
            qos=1,
            retain=True,
        )
        client.publish(TOPICS["availability"], "online", qos=1, retain=True)
        client.publish(
            TOPICS["traffic_availability"],
            "online" if self.traffic_available else "offline",
            qos=1,
            retain=True,
        )
        client.publish(
            TOPICS["result_availability"],
            "online" if self.performance["available"] else "offline",
            qos=1,
            retain=True,
        )
        self._publish_all()
        self.log.info("MQTT connected")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        del client, userdata
        threshold_topics = {
            TOPICS["minimum_download_command"]: "minimum_download_mbps",
            TOPICS["minimum_upload_command"]: "minimum_upload_mbps",
            TOPICS["maximum_ping_command"]: "maximum_ping_ms",
        }
        if message.topic in threshold_topics:
            self._handle_threshold_command(
                threshold_topics[message.topic],
                message.payload,
            )
            return
        if message.topic != TOPICS["command"]:
            return
        payload = message.payload.decode("utf-8", errors="replace").strip()
        if payload == "STOP_RECOVERY":
            self.stop_recovery.set()
            with self.lock:
                if self.incident_active:
                    self.recovery_state = "stopped"
                    save_recovery_stopped(RECOVERY_STATE_FILE, True)
            self._publish_state()
            self._publish_problems()
            self._event("recovery_stopped", reason="user")
        elif payload == "RUN_SPEEDTEST":
            threading.Thread(
                target=self._run_speedtest,
                name="speedtest-manual",
                daemon=True,
            ).start()
        elif payload == "REFRESH_SERVERS":
            threading.Thread(
                target=self._refresh_servers,
                name="speedtest-servers",
                daemon=True,
            ).start()

    def _state_payload(self) -> dict[str, Any]:
        with self.lock:
            return {
                "internet_up": self.snapshot.internet_up,
                "google_up": self.snapshot.google_up,
                "cloudflare_up": self.snapshot.cloudflare_up,
                "router_up": self.snapshot.router_up,
                "app_version": APP_VERSION,
                "started_at": self.started_at,
                "speedtest": dict(self.speedtest),
                "recovery": {
                    "enabled": self.config.recovery.enabled,
                    "mode": self.config.recovery.mode,
                    "state": self.recovery_state,
                    "cycle": self.recovery_cycle,
                    "countdown_seconds": self.recovery_countdown,
                },
            }

    def _publish_state(self) -> None:
        if not self.mqtt.is_connected():
            return
        self.mqtt.publish(
            TOPICS["state"],
            json.dumps(self._state_payload()),
            qos=1,
            retain=True,
        )

    def _publish_outages(self) -> None:
        if not self.mqtt.is_connected():
            return
        self.mqtt.publish(
            TOPICS["outages"],
            json.dumps(self.outages.payload()),
            qos=1,
            retain=True,
        )

    def _publish_thresholds(self) -> None:
        if not self.mqtt.is_connected():
            return
        self.mqtt.publish(
            TOPICS["thresholds"],
            json.dumps(self.thresholds),
            qos=1,
            retain=True,
        )

    def _publish_servers(self) -> None:
        if not self.mqtt.is_connected():
            return
        payload = dict(self.servers)
        payload["configured_server_ids"] = list(self.config.speedtest.server_ids)
        payload["automatic_server_fallback"] = (
            self.config.speedtest.automatic_server_fallback
        )
        self.mqtt.publish(
            TOPICS["servers"],
            json.dumps(payload),
            qos=1,
            retain=True,
        )

    def _publish_recent_results(self) -> None:
        if not self.mqtt.is_connected():
            return
        self.mqtt.publish(
            TOPICS["recent_results"],
            json.dumps(recent_results_payload(self.recent_results)),
            qos=1,
            retain=True,
        )

    def _publish_performance(self) -> None:
        if not self.mqtt.is_connected():
            return
        self.mqtt.publish(
            TOPICS["performance"],
            json.dumps(self.performance),
            qos=1,
            retain=True,
        )

    def _problems_payload(self) -> dict[str, Any]:
        with self.lock:
            problems: list[str] = []
            if not self.snapshot.internet_up:
                problems.append("internet_unavailable")
            if not self.snapshot.router_up:
                problems.append("router_unavailable")
            if self.recovery_state == "error":
                problems.append("recovery_error")
            if self.performance.get("available"):
                problems.extend(self.performance.get("problem_reasons", []))
        return {
            "state": len(problems),
            "problems": problems,
            "updated_at": iso(now_local()),
        }

    def _traffic_payload(self) -> dict[str, Any]:
        payload = traffic_payload(self.traffic)
        payload["router"] = dict(self.router_telemetry)
        return payload

    def _publish_traffic(self) -> None:
        if not self.mqtt.is_connected():
            return
        configured = self.config.traffic.configured
        self.mqtt.publish(
            TOPICS["traffic_availability"],
            "online" if configured and self.traffic_available else "offline",
            qos=1,
            retain=True,
        )
        self.mqtt.publish(
            TOPICS["traffic"],
            json.dumps(self._traffic_payload()),
            qos=1,
            retain=True,
        )

    def _optional_router_state(self, entity_id: str) -> str | None:
        if not entity_id:
            return None
        try:
            payload = self.ha_api.get_state(entity_id)
        except Exception as exc:
            self.log.debug(
                "Optional router state unavailable (%s): %s",
                entity_id,
                exc,
            )
            return None
        state = str(payload.get("state", "")).strip()
        if state.lower() in {"", "unknown", "unavailable", "none"}:
            return None
        return state

    def _optional_router_rate(self, entity_id: str) -> float | None:
        if not entity_id:
            return None
        try:
            return entity_rate_mbps(self.ha_api.get_state(entity_id))
        except Exception as exc:
            self.log.debug(
                "Optional router rate unavailable (%s): %s",
                entity_id,
                exc,
            )
            return None

    def _traffic_sample_once(self) -> None:
        cfg = self.config.traffic
        self.router_telemetry = {
            "wan_status": self._optional_router_state(cfg.router_wan_status),
            "download_rate_mbps": self._optional_router_rate(
                cfg.router_download_rate
            ),
            "upload_rate_mbps": self._optional_router_rate(
                cfg.router_upload_rate
            ),
        }

        if cfg.enabled:
            try:
                download = entity_total_bytes(
                    self.ha_api.get_state(cfg.traffic_download_total)
                )
                upload = entity_total_bytes(
                    self.ha_api.get_state(cfg.traffic_upload_total)
                )
            except Exception as exc:
                if self.traffic_available:
                    self.log.warning(
                        "Traffic sources became unavailable: %s", exc
                    )
                else:
                    self.log.debug("Traffic sources unavailable: %s", exc)
                self.traffic_available = False
            else:
                update_traffic(self.traffic, download, upload)
                save_traffic_state(TRAFFIC_FILE, self.traffic)
                if not self.traffic_available:
                    self.log.info("Traffic sources are available")
                self.traffic_available = True
        else:
            self.traffic_available = False

        self._publish_traffic()

    def _traffic_loop(self) -> None:
        if not self.config.traffic.has_bindings:
            self.log.info("Router telemetry is not configured")
            self._publish_traffic()
            return
        while not self.stop_app.is_set():
            self._traffic_sample_once()
            if self.stop_app.wait(TRAFFIC_POLL_SECONDS):
                break

    def _publish_problems(self) -> None:
        if not self.mqtt.is_connected():
            return
        self.mqtt.publish(
            TOPICS["problems"],
            json.dumps(self._problems_payload()),
            qos=1,
            retain=True,
        )

    def _publish_all(self) -> None:
        self._publish_state()
        self._publish_outages()
        self._publish_thresholds()
        self._publish_servers()
        self._publish_recent_results()
        self._publish_performance()
        self._publish_traffic()
        self._publish_problems()

    def _event(self, event_type: str, **data: Any) -> None:
        if not self.mqtt.is_connected():
            return
        payload = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_type": event_type,
            "timestamp": iso(now_local()),
            **data,
        }
        self.mqtt.publish(
            TOPICS["event"],
            json.dumps(payload),
            qos=1,
            retain=False,
        )

    def _set_recovery_state(
        self, state: str, *, cycle: int | None = None, countdown: int | None = None
    ) -> None:
        with self.lock:
            self.recovery_state = state
            if cycle is not None:
                self.recovery_cycle = cycle
            if countdown is not None:
                self.recovery_countdown = countdown
        self._publish_state()
        self._publish_problems()

    def _countdown(self, state: str, seconds: int) -> bool:
        for remaining in range(max(0, seconds), 0, -1):
            if (
                self.stop_app.is_set()
                or self.stop_recovery.is_set()
                or not self.incident_active
            ):
                return False
            self._set_recovery_state(state, countdown=remaining)
            if self.stop_app.wait(1):
                return False
        self._set_recovery_state(state, countdown=0)
        return True

    def _refresh_performance(self, *, emit_events: bool) -> None:
        previous = dict(self.performance)
        current = evaluate_performance(self.speedtest, self.thresholds)
        self.performance = current

        if self.mqtt.is_connected():
            self.mqtt.publish(
                TOPICS["result_availability"],
                "online" if current["available"] else "offline",
                qos=1,
                retain=True,
            )
        self._publish_performance()
        self._publish_problems()

        if not emit_events or not current["available"]:
            return

        was_problem = bool(
            previous.get("available")
            and previous.get("performance_problem")
        )
        is_problem = bool(current["performance_problem"])
        old_reasons = list(previous.get("problem_reasons") or [])
        new_reasons = list(current.get("problem_reasons") or [])

        if is_problem and not was_problem:
            self._event(
                "performance_problem_started",
                reasons=new_reasons,
                download_mbps=current["download_mbps"],
                upload_mbps=current["upload_mbps"],
                ping_ms=current["ping_ms"],
                minimum_download_mbps=current["minimum_download_mbps"],
                minimum_upload_mbps=current["minimum_upload_mbps"],
                maximum_ping_ms=current["maximum_ping_ms"],
            )
        elif was_problem and not is_problem:
            self._event(
                "performance_problem_recovered",
                previous_reasons=old_reasons,
                download_mbps=current["download_mbps"],
                upload_mbps=current["upload_mbps"],
                ping_ms=current["ping_ms"],
            )
        elif is_problem and old_reasons != new_reasons:
            self._event(
                "performance_problem_updated",
                previous_reasons=old_reasons,
                reasons=new_reasons,
                download_mbps=current["download_mbps"],
                upload_mbps=current["upload_mbps"],
                ping_ms=current["ping_ms"],
            )

    def _handle_threshold_command(self, key: str, payload: bytes) -> None:
        raw = payload.decode("utf-8", errors="replace").strip()
        try:
            updated = set_threshold(self.thresholds, key, raw)
        except ValueError as exc:
            self.log.warning("Ignoring invalid threshold: %s", exc)
            self._publish_thresholds()
            return
        self.thresholds = updated
        atomic_write_json(THRESHOLDS_FILE, self.thresholds)
        self.log.info("Quality threshold changed: %s=%s", key, self.thresholds[key])
        self._publish_thresholds()
        self._refresh_performance(emit_events=True)

    def _set_speedtest_status(
        self, status: str, *, error: str | None = None
    ) -> None:
        with self.lock:
            self.speedtest["status"] = status
            self.speedtest["error"] = error
        self._publish_state()

    def _refresh_servers(self) -> None:
        if not self.speedtest_lock.acquire(blocking=False):
            self.log.info("Speedtest operation is already running")
            return
        try:
            latest = sample(
                self.config.router_ip,
                self.config.connectivity.timeout_seconds,
            )
            if not latest.internet_up:
                self.servers["error"] = "Internet unavailable"
                self._publish_servers()
                return
            try:
                servers = list_servers()
            except RuntimeError as exc:
                self.servers["error"] = str(exc)
                save_servers_state(SERVERS_FILE, self.servers)
                self._publish_servers()
                self.log.error("Ookla server refresh failed: %s", exc)
                return
            self.servers = {
                "count": len(servers),
                "updated_at": iso(now_local()),
                "servers": servers,
                "error": None,
            }
            save_servers_state(SERVERS_FILE, self.servers)
            self._publish_servers()
            self.log.info("Ookla server list refreshed: %s servers", len(servers))
        finally:
            self.speedtest_lock.release()

    def _run_speedtest(self) -> None:
        if not self.speedtest_lock.acquire(blocking=False):
            self.log.info("Speedtest is already running")
            return
        try:
            latest = sample(
                self.config.router_ip,
                self.config.connectivity.timeout_seconds,
            )
            with self.lock:
                self.snapshot = latest
            if not latest.internet_up:
                self._set_speedtest_status(
                    "no_connectivity", error="Internet unavailable"
                )
                self.log.warning("Speedtest skipped: Internet unavailable")
                return

            self._set_speedtest_status("running", error=None)
            candidates: list[int | None] = list(self.config.speedtest.server_ids)
            if not candidates or self.config.speedtest.automatic_server_fallback:
                candidates.append(None)

            errors: list[str] = []
            result: dict[str, Any] | None = None
            for server_id in candidates:
                selection = "automatic" if server_id is None else f"server {server_id}"
                self.log.info("Running Ookla Speedtest: %s", selection)
                try:
                    result = run_speedtest(
                        self.config.speedtest.timeout_seconds,
                        server_id=server_id,
                    )
                    break
                except RuntimeError as exc:
                    errors.append(f"{selection}: {exc}")
                    self.log.warning(
                        "Speedtest attempt failed: %s: %s",
                        selection,
                        exc,
                    )
            if result is None:
                message = " | ".join(errors)[-1800:]
                self._set_speedtest_status("error", error=message)
                self._event("speedtest_failed", reason=message)
                return

            with self.lock:
                self.speedtest = result
                save_last_result(SPEEDTEST_FILE, result)
            self._publish_state()
            self._refresh_performance(emit_events=True)
            record = build_recent_record(
                self.speedtest,
                self.thresholds,
                self.performance,
            )
            self.recent_results = append_recent_result(
                self.recent_results,
                record,
            )
            save_recent_results(RECENT_RESULTS_FILE, self.recent_results)
            self._publish_recent_results()
            self._event(
                "speedtest_completed",
                download_mbps=result["download_mbps"],
                upload_mbps=result["upload_mbps"],
                ping_ms=result["ping_ms"],
                jitter_ms=result["jitter_ms"],
                packet_loss_pct=result["packet_loss_pct"],
            )
            self.log.info(
                "Speedtest completed: download %.1f Mbit/s, "
                "upload %.1f Mbit/s, ping %.1f ms",
                result["download_mbps"],
                result["upload_mbps"],
                result["ping_ms"],
            )
        finally:
            self.speedtest_lock.release()

    def _periodic_speedtest_loop(self) -> None:
        if not self.config.speedtest.periodic_enabled:
            self.log.info("Periodic Speedtest is disabled")
            return
        interval = self.config.speedtest.interval_seconds
        self.log.info("Periodic Speedtest interval: %s minutes", interval // 60)
        while not self.stop_app.wait(interval):
            self._run_speedtest()

    def _recovery_worker(self) -> None:
        cfg = self.config.recovery
        executor = RecoveryExecutor(self.ha_api, self.stop_recovery)
        try:
            while (
                self.incident_active
                and not self.stop_app.is_set()
                and not self.stop_recovery.is_set()
            ):
                for cycle in range(1, cfg.max_cycles + 1):
                    if (
                        not self.incident_active
                        or self.stop_app.is_set()
                        or self.stop_recovery.is_set()
                    ):
                        return

                    latest = sample(
                        self.config.router_ip,
                        self.config.connectivity.timeout_seconds,
                    )
                    with self.lock:
                        self.snapshot = latest
                    if latest.internet_up:
                        return

                    selection = choose_targets(
                        mode=cfg.mode,
                        internet_up=latest.internet_up,
                        router_up=latest.router_up,
                    )
                    self._set_recovery_state(
                        "running", cycle=cycle, countdown=0
                    )
                    self._event(
                        "recovery_started",
                        cycle=cycle,
                        mode=cfg.mode,
                        targets=list(selection.targets),
                        reason=selection.reason,
                    )

                    for name in selection.targets:
                        target = target_by_name(cfg, name)
                        self._event(
                            "recovery_action",
                            cycle=cycle,
                            target=name,
                            action=target.action,
                            entity_id=target.entity_id,
                        )
                        executor.execute(target)

                    if not self._countdown("boot_wait", cfg.boot_wait_seconds):
                        return

                    latest = sample(
                        self.config.router_ip,
                        self.config.connectivity.timeout_seconds,
                    )
                    with self.lock:
                        self.snapshot = latest
                    self._publish_state()
                    if latest.internet_up:
                        return

                    if cycle < cfg.max_cycles:
                        if not self._countdown(
                            "retry_wait", cfg.retry_interval_seconds
                        ):
                            return

                self._set_recovery_state(
                    "cooldown", cycle=cfg.max_cycles, countdown=cfg.cooldown_seconds
                )
                self._event(
                    "recovery_exhausted",
                    cycles=cfg.max_cycles,
                    cooldown_seconds=cfg.cooldown_seconds,
                )
                if not self._countdown("cooldown", cfg.cooldown_seconds):
                    return
                self._set_recovery_state("running", cycle=0, countdown=0)

        except RecoveryStopped:
            self._set_recovery_state("stopped", countdown=0)
        except Exception as exc:
            self.log.exception("Recovery failed")
            self._set_recovery_state("error", countdown=0)
            self._event("recovery_error", error=str(exc))
        finally:
            with self.lock:
                self.recovery_thread = None
                if not self.incident_active:
                    self.recovery_state = "idle"
                    self.recovery_cycle = 0
                    self.recovery_countdown = 0
            self._publish_state()

    def _ensure_recovery(self) -> None:
        if not self.config.recovery.enabled or self.stop_recovery.is_set():
            return
        with self.lock:
            if self.recovery_thread is not None:
                return
            self.recovery_thread = threading.Thread(
                target=self._recovery_worker,
                name="recovery",
                daemon=True,
            )
            self.recovery_thread.start()

    def _observe(self, snapshot: ConnectivitySnapshot) -> None:
        with self.lock:
            self.snapshot = snapshot

        if snapshot.internet_up:
            self.failure_count = 0
            if self.incident_active:
                record = self.outages.recover()
                self.incident_active = False
                save_recovery_stopped(RECOVERY_STATE_FILE, False)
                self.stop_recovery.set()
                self._event(
                    "connection_restored",
                    duration_seconds=(
                        record["duration_seconds"] if record is not None else 0
                    ),
                )
                self._set_recovery_state("idle", cycle=0, countdown=0)
                self._publish_outages()
            return

        self.failure_count += 1
        if self.failure_count < self.config.connectivity.attempts:
            return

        if not self.incident_active:
            self.incident_active = True
            self.stop_recovery.clear()
            save_recovery_stopped(RECOVERY_STATE_FILE, False)
            self.outages.start()
            self._event(
                "connection_lost",
                router_up=snapshot.router_up,
                attempts=self.failure_count,
            )
            self._publish_outages()

        self._ensure_recovery()

    def run(self) -> None:
        host = os.environ["MQTT_HOST"]
        port = int(os.getenv("MQTT_PORT", "1883"))
        self.mqtt.connect(host, port, keepalive=60)
        self.mqtt.loop_start()
        periodic_speedtest = threading.Thread(
            target=self._periodic_speedtest_loop,
            name="speedtest-periodic",
            daemon=True,
        )
        periodic_speedtest.start()
        traffic_thread = threading.Thread(
            target=self._traffic_loop,
            name="traffic-accounting",
            daemon=True,
        )
        traffic_thread.start()
        try:
            while not self.stop_app.is_set():
                snapshot = sample(
                    self.config.router_ip,
                    self.config.connectivity.timeout_seconds,
                )
                self._observe(snapshot)
                self._publish_all()
                self.stop_app.wait(self.config.connectivity.interval_seconds)
        finally:
            self.stop_recovery.set()
            if self.recovery_thread is not None:
                # A stopped switch recovery may need to finish both HA API
                # service calls before the process exits.
                self.recovery_thread.join(
                    timeout=(self.ha_api.timeout_seconds * 2) + 5
                )
            if self.mqtt.is_connected():
                self.mqtt.publish(
                    TOPICS["availability"], "offline", qos=1, retain=True
                ).wait_for_publish()
            self.mqtt.loop_stop()
            self.mqtt.disconnect()

    def stop(self, *_args: Any) -> None:
        self.stop_app.set()
        self.stop_recovery.set()


def main() -> None:
    try:
        app = InternetApp()
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    signal.signal(signal.SIGTERM, app.stop)
    signal.signal(signal.SIGINT, app.stop)
    app.run()


if __name__ == "__main__":
    main()
