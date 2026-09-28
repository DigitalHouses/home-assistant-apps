from __future__ import annotations

import json
import logging
import os
import re
import signal
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

from backblaze import BackblazeClient
from config import AppConfig, load_config
from discovery import (
    API_OBSERVED_TOPIC,
    APP_AVAILABILITY_TOPIC,
    DATA_AVAILABILITY_TOPIC,
    DISCOVERY_SCHEMA_VERSION,
    DISCOVERY_TOPIC,
    HA_STATUS_TOPIC,
    REFRESH_COMMAND_TOPIC,
    STATE_RETAIN,
    STATE_TOPIC,
    TELEMETRY_DELETE_COMMAND_TOPIC,
    build_discovery_payload,
    discovery_cleanup_payload,
    dynamic_discovery_manifest,
    load_discovery_manifest,
    mark_discovery_schema,
    needs_discovery_reset,
    removed_discovery_components,
    save_discovery_manifest,
    bucket_state_topic,
)
from telemetry import TelemetryClient, TelemetryRunner

APP_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
APP_VERSION = os.environ.get("APP_VERSION")
if not APP_VERSION or APP_VERSION_RE.fullmatch(APP_VERSION) is None:
    raise RuntimeError("APP_VERSION must be a valid semantic version")


class BackblazeMonitorApp:
    def __init__(self) -> None:
        self.config: AppConfig = load_config()
        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper()),
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.log = logging.getLogger("digitalhouses_backblaze")
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.api = BackblazeClient(
            self.config.application_key_id,
            self.config.application_key,
        )
        self.stop_event = threading.Event()
        self.mqtt_connected = threading.Event()
        self.refresh_requested = threading.Event()
        self.refresh_in_progress = threading.Event()
        self.state_lock = threading.RLock()
        self.discovery_sync_lock = threading.RLock()
        self.buckets: list[dict[str, Any]] = []
        self.has_scan_result = False
        self.last_scan_succeeded = False
        self.discovery_manifest_invalid = False
        try:
            loaded_manifest = load_discovery_manifest()
        except ValueError as exc:
            self.log.warning("Discovery manifest is invalid; reset required: %s", exc)
            loaded_manifest = None
            self.discovery_manifest_invalid = True
        self.discovery_manifest_missing = loaded_manifest is None
        self.discovery_manifest = loaded_manifest or {}

        self.state: dict[str, Any] = {
            "api_connected": False,
            "bucket_count": 0,
            "stored_bytes": 0,
            "current_bytes": 0,
            "current_files": 0,
            "versions": 0,
            "last_update": None,
            "app_version": APP_VERSION,
            "app_started_at": self.started_at,
        }
        self.telemetry = TelemetryClient(
            enabled=self.config.telemetry_enabled,
            version=APP_VERSION,
        )
        self.telemetry_runner = TelemetryRunner(self.telemetry)
        self.client = self._build_mqtt_client()

    def _build_mqtt_client(self) -> mqtt.Client:
        client = mqtt.Client(client_id="digitalhouses-backblaze")
        username = os.getenv("MQTT_USER", "")
        if username:
            client.username_pw_set(username, os.getenv("MQTT_PASSWORD", ""))
        client.will_set(APP_AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    def _on_connect(self, client, userdata, flags, return_code) -> None:
        del userdata, flags
        if return_code != 0:
            self.log.error("MQTT connection failed with code %s", return_code)
            return
        self.mqtt_connected.set()
        client.subscribe(HA_STATUS_TOPIC, qos=1)
        client.subscribe(REFRESH_COMMAND_TOPIC, qos=1)
        client.subscribe(TELEMETRY_DELETE_COMMAND_TOPIC, qos=1)
        self.publish_text(APP_AVAILABILITY_TOPIC, "online", retain=True)
        self.publish_text(DATA_AVAILABILITY_TOPIC, "offline", retain=True)
        self.publish_text(API_OBSERVED_TOPIC, "offline", retain=True)
        threading.Thread(
            target=self._sync_discovery_after_connect,
            name="dh-backblaze-discovery-sync",
            daemon=True,
        ).start()

    def _sync_discovery_after_connect(self) -> None:
        with self.discovery_sync_lock:
            reset = (
                needs_discovery_reset()
                or self.discovery_manifest_missing
                or self.discovery_manifest_invalid
            )
            if reset:
                if not self.publish_text(
                    DISCOVERY_TOPIC,
                    "",
                    retain=True,
                    confirm=True,
                ):
                    self.log.warning(
                        "MQTT discovery migration could not clear old config"
                    )
                    return
                self.discovery_manifest = {}
                self.log.info(
                    "MQTT discovery migration: old retained device config cleared"
                )

            self.publish_state()

            if self.has_scan_result and self.last_scan_succeeded:
                if not self.sync_discovery():
                    return
                self.publish_buckets()
                self.publish_text(API_OBSERVED_TOPIC, "online", retain=True)
                self.publish_text(DATA_AVAILABILITY_TOPIC, "online", retain=True)
            elif self.has_scan_result:
                self.publish_text(API_OBSERVED_TOPIC, "online", retain=True)
                self.publish_text(DATA_AVAILABILITY_TOPIC, "offline", retain=True)
            elif reset:
                payload = build_discovery_payload(APP_VERSION)
                if not self.publish_json(
                    DISCOVERY_TOPIC,
                    payload,
                    retain=True,
                    confirm=True,
                ):
                    return
                try:
                    save_discovery_manifest({})
                except OSError as exc:
                    self.log.warning(
                        "Unable to persist empty discovery manifest: %s",
                        exc,
                    )
                    return
                self.discovery_manifest = {}
                self.discovery_manifest_missing = False
                self.discovery_manifest_invalid = False

            if reset:
                try:
                    mark_discovery_schema()
                except OSError as exc:
                    self.log.warning(
                        "Unable to persist discovery schema version: %s",
                        exc,
                    )
                else:
                    self.log.info(
                        "MQTT discovery migration complete: schema=%s",
                        DISCOVERY_SCHEMA_VERSION,
                    )

            self.log.info("MQTT connected; retained state synchronized")

    def _on_disconnect(self, client, userdata, return_code) -> None:
        del client, userdata
        self.mqtt_connected.clear()
        if return_code:
            self.log.warning("MQTT connection lost; reconnect is active")

    def _on_message(self, client, userdata, message) -> None:
        del client, userdata
        if message.topic == REFRESH_COMMAND_TOPIC:
            if not self.refresh_in_progress.is_set():
                self.refresh_requested.set()
                self.log.info("Manual refresh requested")
            return
        if message.topic == TELEMETRY_DELETE_COMMAND_TOPIC:
            threading.Thread(
                target=self._delete_telemetry,
                name="dh-backblaze-telemetry-delete",
                daemon=True,
            ).start()
            return
        if message.topic == HA_STATUS_TOPIC:
            payload = message.payload.decode("utf-8", errors="replace").strip().lower()
            if payload == "online":
                threading.Thread(
                    target=self._republish_current_snapshot,
                    name="dh-backblaze-ha-republish",
                    daemon=True,
                ).start()

    def _republish_current_snapshot(self) -> None:
        with self.discovery_sync_lock:
            self.publish_state()
            if self.has_scan_result and self.last_scan_succeeded:
                if self.sync_discovery():
                    self.publish_buckets()
                    self.publish_text(API_OBSERVED_TOPIC, "online", retain=True)
                    self.publish_text(DATA_AVAILABILITY_TOPIC, "online", retain=True)
            elif self.has_scan_result:
                self.publish_text(API_OBSERVED_TOPIC, "online", retain=True)
                self.publish_text(DATA_AVAILABILITY_TOPIC, "offline", retain=True)

    def _delete_telemetry(self) -> None:
        if self.telemetry.delete():
            self.log.info("Retained DigitalHouses telemetry record deleted")
        else:
            self.log.warning("Unable to delete retained DigitalHouses telemetry record")

    def publish_text(
        self,
        topic: str,
        payload: str,
        *,
        retain: bool,
        confirm: bool = False,
    ) -> bool:
        if not self.mqtt_connected.is_set():
            return False
        info = self.client.publish(topic, payload, qos=1, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            self.log.warning("MQTT publish failed for %s: rc=%s", topic, info.rc)
            return False
        if not confirm:
            return True
        try:
            info.wait_for_publish(timeout=5.0)
        except (RuntimeError, ValueError) as exc:
            self.log.warning("MQTT publish was not confirmed for %s: %s", topic, exc)
            return False
        if not info.is_published():
            self.log.warning("MQTT publish timed out for %s", topic)
            return False
        return True

    def publish_json(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        retain: bool = True,
        confirm: bool = False,
    ) -> bool:
        return self.publish_text(
            topic,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=retain,
            confirm=confirm,
        )

    def publish_state(self) -> bool:
        with self.state_lock:
            payload = dict(self.state)
        return self.publish_json(STATE_TOPIC, payload, retain=STATE_RETAIN)

    def publish_buckets(self) -> bool:
        with self.state_lock:
            buckets = [dict(item) for item in self.buckets]
        ok = True
        for bucket in buckets:
            ok = self.publish_json(
                bucket_state_topic(str(bucket["bucket_id"])),
                bucket,
                retain=True,
            ) and ok
        return ok

    def sync_discovery(self) -> bool:
        with self.discovery_sync_lock:
            if not self.mqtt_connected.is_set():
                return False
            with self.state_lock:
                buckets = [
                    {
                        "bucket_id": item["bucket_id"],
                        "bucket_name": item["bucket_name"],
                    }
                    for item in self.buckets
                ]

            payload = build_discovery_payload(APP_VERSION, buckets)
            current_manifest = dynamic_discovery_manifest(payload)
            try:
                removals, retained_topics = removed_discovery_components(
                    self.discovery_manifest,
                    current_manifest,
                )
            except ValueError as exc:
                self.log.warning("Discovery reconciliation failed: %s", exc)
                return False

            if removals:
                cleanup = discovery_cleanup_payload(payload, removals)
                if not self.publish_json(
                    DISCOVERY_TOPIC,
                    cleanup,
                    retain=True,
                    confirm=True,
                ):
                    return False
                for topic in retained_topics:
                    if not self.publish_text(
                        topic,
                        "",
                        retain=True,
                        confirm=True,
                    ):
                        return False

            if not self.publish_json(
                DISCOVERY_TOPIC,
                payload,
                retain=True,
                confirm=True,
            ):
                return False

            try:
                save_discovery_manifest(current_manifest)
            except OSError as exc:
                self.log.warning("Unable to persist discovery manifest: %s", exc)
                return False

            self.discovery_manifest = current_manifest
            self.discovery_manifest_missing = False
            self.discovery_manifest_invalid = False

            if removals:
                self.log.info(
                    "Removed stale Backblaze discovery components: %s",
                    ", ".join(sorted(removals)),
                )
            return True

    def refresh(self) -> bool:
        if self.refresh_in_progress.is_set():
            return False
        self.refresh_in_progress.set()
        self.refresh_requested.clear()
        try:
            usage = self.api.scan_all()
            now = datetime.now(timezone.utc).isoformat()
            buckets = [asdict(item) for item in usage.buckets]
            with self.state_lock:
                self.buckets = buckets
                self.state.update({
                    "api_connected": True,
                    "bucket_count": len(buckets),
                    "stored_bytes": usage.stored_bytes,
                    "current_bytes": usage.current_bytes,
                    "current_files": usage.current_files,
                    "versions": usage.versions,
                    "last_update": now,
                })
            self.has_scan_result = True
            self.last_scan_succeeded = True

            if self.mqtt_connected.is_set():
                if not self.sync_discovery():
                    self.publish_text(DATA_AVAILABILITY_TOPIC, "offline", retain=True)
                    self.log.warning(
                        "Backblaze refresh collected data but MQTT discovery sync failed"
                    )
                    return False
                self.publish_state()
                self.publish_buckets()
                self.publish_text(API_OBSERVED_TOPIC, "online", retain=True)
                self.publish_text(DATA_AVAILABILITY_TOPIC, "online", retain=True)

            self.log.info(
                "Backblaze refresh complete: buckets=%s stored_bytes=%s versions=%s",
                len(buckets),
                usage.stored_bytes,
                usage.versions,
            )
            return True
        except Exception as exc:
            with self.state_lock:
                self.state["api_connected"] = False
            self.has_scan_result = True
            self.last_scan_succeeded = False
            if self.mqtt_connected.is_set():
                self.publish_state()
                self.publish_text(API_OBSERVED_TOPIC, "online", retain=True)
                self.publish_text(DATA_AVAILABILITY_TOPIC, "offline", retain=True)
            self.log.warning("Backblaze refresh failed: %s", exc)
            return False
        finally:
            self.refresh_in_progress.clear()

    def run(self) -> None:
        interval_seconds = self.config.refresh_interval_hours * 3600
        self.log.info("Starting DigitalHouses Backblaze %s", APP_VERSION)
        self.log.info(
            "Refresh interval: %s hour(s)",
            self.config.refresh_interval_hours,
        )
        host = os.environ["MQTT_HOST"]
        port = int(os.getenv("MQTT_PORT", "1883"))
        self.client.connect_async(host, port, keepalive=60)
        self.client.loop_start()
        self.telemetry_runner.start()
        next_refresh = 0.0
        try:
            while not self.stop_event.is_set():
                now = time.monotonic()
                if self.refresh_requested.is_set() or now >= next_refresh:
                    self.refresh()
                    next_refresh = time.monotonic() + interval_seconds
                self.stop_event.wait(1.0)
        finally:
            self.telemetry_runner.stop()
            self.publish_text(DATA_AVAILABILITY_TOPIC, "offline", retain=True)
            self.publish_text(API_OBSERVED_TOPIC, "offline", retain=True)
            self.publish_text(APP_AVAILABILITY_TOPIC, "offline", retain=True)
            self.client.disconnect()
            self.client.loop_stop()

    def stop(self, *_args: object) -> None:
        self.stop_event.set()


def main() -> None:
    app = BackblazeMonitorApp()
    signal.signal(signal.SIGTERM, app.stop)
    signal.signal(signal.SIGINT, app.stop)
    app.run()


if __name__ == "__main__":
    main()
