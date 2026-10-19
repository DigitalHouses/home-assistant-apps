"""DigitalHouses Zigbee Monitor - HAOS MQTT runtime entry point.

The canonical installable App metadata is a separate release-gated step.
This runtime does not alter Zigbee2MQTT configuration or issue device commands.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
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
from zigbee_monitor.agent_options import (
    SupervisorOptions, merge_new_discoveries, ping_management_ip,
)
from zigbee_monitor.discovery import APP_AVAILABILITY, PRODUCT
from zigbee_monitor.service import MonitorService
from zigbee_monitor.telemetry import TelemetryClient, TelemetryRunner
from zigbee_monitor.mqtt_compat import create_mqtt_client, connection_failed

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
        self.telemetry = TelemetryClient(enabled=True, version=version)
        self.telemetry_runner = TelemetryRunner(self.telemetry)
        self.store = ActivityStore(Path("/data/activity.sqlite3"))
        # Registry is durable. Existing 0.1.0 manual settings are accepted as a
        # migration hint, but v0.1.1 requires no network configuration at all.
        self.monitor = ZigbeeMonitor(self.store.known_networks())
        legacy = options.get("zigbee2mqtt") or []
        if legacy:
            for network in parse_networks(legacy):
                if network.network_id not in {n.network_id for n in self.monitor.networks}:
                    self.monitor.add_network(network)
        self.stop_event = threading.Event()
        self._errors_logged: dict[str, float] = {}
        self.client = create_mqtt_client(
            mqtt, client_id="dh-zigbee-monitor-app",
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
        self.service.set_agent_options(options)
        self._supervisor_options = SupervisorOptions()
        self._next_agent_sync = 0.0
        self._next_ping = 0.0
        self._sync_worker: threading.Thread | None = None
        self._ping_worker: threading.Thread | None = None

    def _publish(self, topic: str, payload: str, retain: bool) -> bool:
        result = self.client.publish(topic, payload, qos=1, retain=retain)
        return result.rc == mqtt.MQTT_ERR_SUCCESS

    def _subscribe(self, topic: str) -> bool:
        result, _mid = self.client.subscribe(topic, qos=1)
        return result == mqtt.MQTT_ERR_SUCCESS

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        # paho-mqtt 1.x calls four args, 2.x callback API v2 calls five.
        del client, userdata, flags, properties
        if connection_failed(reason_code):
            self.log.error("MQTT connect rejected: %s", reason_code)
            return
        self.service.connected()
        self.log.info("MQTT connected; observing %s Z2M networks", len(self.monitor.networks))

    def _on_disconnect(self, client, userdata, *callback_args) -> None:
        # paho-mqtt 1.x: (client, userdata, rc); v2: flags, reason, props.
        del client, userdata, callback_args
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

    def _sync_agent_options(self) -> None:
        """Append discovered IEEE once to own Supervisor Options; NEVER overwrite edits.

        This runs off the MQTT callback. A failed Supervisor request is logged
        and retried later; Zigbee Monitor keeps running with observed data.
        """
        try:
            coordinators, repeaters, legacy = self.service.agent_snapshot()
            current = self._supervisor_options.read()
            merged, changed = merge_new_discoveries(
                current, coordinators, repeaters, legacy=legacy,
            )
            if changed:
                self._supervisor_options.write(merged)
                self.log.info(
                    "Saved discovered Zigbee IEEE to own App Options: "
                    "%d coordinators, %d repeaters",
                    len(merged.get("coordinators", [])),
                    len(merged.get("repeaters", [])),
                )
            # Catch user changes made in HA Options without rebooting this App.
            self.service.set_agent_options(merged)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self.log.warning("Cannot synchronize own Zigbee App Options: %s", exc)

    def _check_agent_ips(self) -> None:
        """Bounded ICMP checks of explicit management IPs (no RF health claims)."""
        try:
            targets = dict(list(self.service.agent_ping_targets().items())[:32])
            if not targets:
                self.service.set_ping_results({})
                return
            # Never create an unbounded number of probe workers.
            with ThreadPoolExecutor(max_workers=4) as executor:
                checks = {
                    f"{ieee}@{ip}": status
                    for (ieee, ip), status in zip(
                        targets.items(), executor.map(
                            ping_management_ip, targets.values()
                        )
                    )
                }
            self.service.set_ping_results(checks)
        except Exception:
            self.log.exception("IP check failed; not interpreting it as Zigbee failure")

    def run(self) -> None:
        host = os.environ["MQTT_HOST"]
        port = int(os.getenv("MQTT_PORT", "1883"))
        self.client.connect_async(host, port, keepalive=60)
        self.client.loop_start()
        self.telemetry_runner.start()
        self.log.info("Starting %s with %d remembered networks; passive MQTT discovery enabled", PRODUCT,
                      len(self.monitor.networks))
        try:
            while not self.stop_event.wait(1):
                self.service.tick()
                now = time.monotonic()
                if now >= self._next_agent_sync:
                    self._next_agent_sync = now + 60
                    if self._sync_worker is None or not self._sync_worker.is_alive():
                        self._sync_worker = threading.Thread(
                            target=self._sync_agent_options,
                            name="dh-zigbee-agent-options-sync", daemon=True,
                        )
                        self._sync_worker.start()
                if now >= self._next_ping:
                    self._next_ping = now + 60
                    if self._ping_worker is None or not self._ping_worker.is_alive():
                        self._ping_worker = threading.Thread(
                            target=self._check_agent_ips,
                            name="dh-zigbee-management-ping", daemon=True,
                        )
                        self._ping_worker.start()
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
