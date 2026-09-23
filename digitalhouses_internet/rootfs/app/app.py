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
from discovery import DISCOVERY_TOPIC, DEVICE_ID, TOPICS, build_discovery_payload
from ha_api import HomeAssistantApi
from recovery import (
    RecoveryExecutor,
    RecoveryStopped,
    choose_targets,
    target_by_name,
)
from state import OutageTracker, iso, now_local

APP_VERSION = os.getenv("APP_VERSION", "0.1.0-local")
OUTAGES_FILE = Path("/data/runtime/outages.json")


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

        self.snapshot = ConnectivitySnapshot(False, False)
        self.failure_count = 0
        self.incident_active = False
        self.recovery_state = "idle"
        self.recovery_cycle = 0
        self.recovery_countdown = 0

        self.outages = OutageTracker.load(OUTAGES_FILE)
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
        if int(reason_code) != 0:
            self.log.error("MQTT connection failed: %s", reason_code)
            return
        client.subscribe(TOPICS["command"], qos=1)
        client.publish(
            DISCOVERY_TOPIC,
            json.dumps(build_discovery_payload(APP_VERSION)),
            qos=1,
            retain=True,
        )
        client.publish(TOPICS["availability"], "online", qos=1, retain=True)
        self._publish_all()
        self.log.info("MQTT connected")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        del client, userdata
        if message.topic != TOPICS["command"]:
            return
        payload = message.payload.decode("utf-8", errors="replace").strip()
        if payload == "STOP_RECOVERY":
            self.stop_recovery.set()
            with self.lock:
                if self.incident_active:
                    self.recovery_state = "stopped"
            self._publish_state()
            self._event("recovery_stopped", reason="user")

    def _state_payload(self) -> dict[str, Any]:
        with self.lock:
            return {
                "internet_up": self.snapshot.internet_up,
                "router_up": self.snapshot.router_up,
                "app_version": APP_VERSION,
                "started_at": self.started_at,
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

    def _publish_all(self) -> None:
        self._publish_state()
        self._publish_outages()

    def _event(self, event_type: str, **data: Any) -> None:
        if not self.mqtt.is_connected():
            return
        payload = {
            "schema_version": 1,
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
                self.recovery_thread.join(timeout=10)
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
