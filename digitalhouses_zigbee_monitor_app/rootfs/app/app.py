"""DigitalHouses Zigbee Monitor - HAOS MQTT runtime entry point.

The canonical installable App metadata is a separate release-gated step.
This runtime does not alter Zigbee2MQTT configuration or issue device commands.
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import APP_AVAILABILITY, PRODUCT
from zigbee_monitor.service import MonitorService
from zigbee_monitor.telemetry import TelemetryClient, TelemetryRunner

RELEASES_URL = "https://api.github.com/repos/DigitalHouses/home-assistant-apps/releases?per_page=100"
RELEASE_TAG = re.compile(r"^digitalhouses_zigbee_monitor_app-v(\d+\.\d+\.\d+)$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def read_options(path: Path = Path("/data/options.json")) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("options.json must be an object")
    return data


def latest_stable_release(*, url: str = RELEASES_URL) -> str | None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "DigitalHouses-Zigbee-Monitor"}
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("release response too large")
    releases = json.loads(raw.decode("utf-8"))
    if not isinstance(releases, list):
        raise ValueError("releases must be an array")
    versions = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name")
        match = RELEASE_TAG.fullmatch(tag) if isinstance(tag, str) else None
        if match:
            versions.append(tuple(int(p) for p in match.group(1).split(".")))
    if not versions:
        return None
    return ".".join(str(v) for v in max(versions))


class Application:
    def __init__(self) -> None:
        options = read_options()
        level = options.get("log_level", "info")
        if level not in ("debug", "info", "warning", "error"):
            raise ValueError("invalid log_level")
        logging.basicConfig(
            level=getattr(logging, level.upper()),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        self.log = logging.getLogger(PRODUCT)
        if options.get("telemetry_enabled") is not True:
            self.log.error("Не принято условие передачи статистики DigitalHouses — завершение работы")
            raise SystemExit(1)
        version = os.environ.get("APP_VERSION", "")
        if not VERSION_RE.fullmatch(version):
            raise ValueError("APP_VERSION must be SemVer, e.g. 0.1.0")
        networks = parse_networks(options.get("zigbee2mqtt"))
        self.telemetry = TelemetryClient(enabled=True, version=version)
        self.telemetry_runner = TelemetryRunner(self.telemetry)
        self.store = ActivityStore(Path("/data/activity.sqlite3"))
        self.monitor = ZigbeeMonitor(networks)
        self.stop_event = threading.Event()
        self._errors_logged: dict[str, float] = {}
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="dh-zigbee-monitor-app",
        )
        if os.getenv("MQTT_USER"):
            self.client.username_pw_set(
                os.environ["MQTT_USER"], os.getenv("MQTT_PASSWORD", "")
            )
        self.client.will_set(
            APP_AVAILABILITY, payload="offline", qos=1, retain=True,
        )
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.service = MonitorService(
            self.monitor, self.store,
            publish=self._publish,
            subscribe=self._subscribe,
            version=version,
        )

    def _publish(self, topic: str, payload: str, retain: bool) -> bool:
        result = self.client.publish(topic, payload, qos=1, retain=retain)
        return result.rc == mqtt.MQTT_ERR_SUCCESS

    def _subscribe(self, topic: str) -> bool:
        result, _mid = self.client.subscribe(topic, qos=1)
        return result == mqtt.MQTT_ERR_SUCCESS

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        del client, userdata, flags, properties
        if getattr(reason_code, "is_failure", False):
            self.log.error("MQTT connect rejected: %s", reason_code)
            return
        self.service.connected()
        self.log.info("MQTT connected; observing %s Z2M networks", len(self.monitor.networks))

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        del client, userdata, flags, reason_code, properties
        self.service.disconnected()
        self.log.warning("MQTT disconnected; observations invalidated")

    def _check_updates(self) -> None:
        try:
            latest = latest_stable_release()
            if latest is None:
                raise ValueError("нет опубликованного релиза приложения")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.service.complete_check(latest=None, error=str(exc))
        else:
            self.service.complete_check(latest=latest)

    def _delete_telemetry(self) -> None:
        try:
            ok = self.telemetry.delete()
        except Exception:
            self.log.exception("Telemetry deletion failed")
            ok = False
        self.service.complete_telemetry_delete(ok)

    def _on_message(self, client, userdata, message) -> None:
        del client, userdata
        try:
            kind = self.service.receive(
                message.topic, bytes(message.payload),
                retain=bool(message.retain), dup=bool(message.dup),
            )
            if kind == "check_updates_requested":
                threading.Thread(
                    target=self._check_updates,
                    name="dh-zigbee-version-check",
                    daemon=True,
                ).start()
            elif kind == "delete_telemetry_requested":
                threading.Thread(
                    target=self._delete_telemetry,
                    name="dh-zigbee-telemetry-delete",
                    daemon=True,
                ).start()
            elif kind == "inventory":
                self.log.info("Zigbee2MQTT inventory updated: %s", message.topic)
        except Exception as exc:
            now = time.monotonic()
            key = message.topic
            if now - self._errors_logged.get(key, -1e9) > 60:
                self._errors_logged[key] = now
                self.log.warning("Rejected invalid MQTT data on %s: %s", key, exc)

    def run(self) -> None:
        host = os.environ["MQTT_HOST"]
        port = int(os.getenv("MQTT_PORT", "1883"))
        self.client.connect_async(host, port, keepalive=60)
        self.client.loop_start()
        self.telemetry_runner.start()
        self.log.info("Starting %s with %d configured networks", PRODUCT,
                      len(self.monitor.networks))
        try:
            while not self.stop_event.wait(1):
                self.service.tick()
        finally:
            self.log.info("Stopping Zigbee Monitor")
            self.telemetry_runner.stop()
            try:
                if self.client.is_connected():
                    self.client.publish(APP_AVAILABILITY, "offline", qos=1, retain=True)
                    self.client.disconnect()
            finally:
                self.client.loop_stop()
                self.store.close()

    def stop(self, *_args: Any) -> None:
        self.stop_event.set()


def main() -> None:
    app = Application()
    signal.signal(signal.SIGTERM, app.stop)
    signal.signal(signal.SIGINT, app.stop)
    app.run()


if __name__ == "__main__":
    main()
