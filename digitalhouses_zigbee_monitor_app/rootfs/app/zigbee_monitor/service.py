"""MQTT-facing service of Zigbee Monitor. HA remains presentation-only.

This service never sends any Zigbee2MQTT control command. Read-only refresh
re-subscribes to Z2M retained bridge state and inventory. Source state is
invalidated on every MQTT reconnect. SQLite sees only aggregated minute data.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .core import ZigbeeMonitor, ZigbeeMonitorError
from .autodiscovery import DISCOVERY_FILTERS, discovery_from_bridge
from .discovery import (
    APP_AVAILABILITY, DETAILS, DISCOVERY, HA_STATUS, HISTORY, ROOT,
    build_discovery, state_topic, validity_topic,
)
from .storage import ActivityStore

log = logging.getLogger(__name__)
Publish = Callable[[str, str, bool], bool]
Subscribe = Callable[[str], bool]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


class MonitorService:
    """Service boundary; caller serializes message, tick, and connect callbacks."""

    def __init__(
        self,
        monitor: ZigbeeMonitor,
        store: ActivityStore,
        *,
        publish: Publish,
        subscribe: Subscribe,
        version: str,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.monitor = monitor
        self.store = store
        self.publish = publish
        self.subscribe = subscribe
        self.version = version
        self.now = now
        self.started_at = _iso(now())
        self._lock = threading.RLock()
        self._connected = False
        self._published: dict[str, str] = {}
        self._valid: dict[str, bool] = {}
        self._continuous_since: float | None = None
        self._last_flush_minute: int | None = None
        self._last_trim_day: int | None = None
        self._offline_since: dict[tuple[str, str], str | None] = {}
        self._refresh_pending: set[str] | None = None
        self._refresh_started: float | None = None
        self._card_success_until: float | None = None
        self._refresh_state: dict[str, object] = {
            "state": "idle", "started_at": None, "finished_at": None,
            "duration_seconds": None, "error": None,
        }
        self._card: dict[str, object] = {
            "state": "idle", "operation": None, "started_at": None,
            "finished_at": None, "duration_seconds": None, "error": None,
        }

    def _send(self, topic: str, payload: str, *, force: bool = False) -> bool:
        if not self._connected:
            return False
        if not force and self._published.get(topic) == payload:
            return True
        if not self.publish(topic, payload, True):
            return False
        self._published[topic] = payload
        return True

    def _validity(self, key: str, valid: bool, *, force: bool = False) -> None:
        topic = validity_topic(key)
        state = "online" if valid else "offline"
        if self._send(topic, state, force=force):
            self._valid[key] = valid

    def _scalar(self, key: str, value: int | float | None) -> None:
        if value is None:
            self._validity(key, False)
            return
        # Publish state before availability so HA never exposes a stale scalar.
        if self._send(state_topic(key), str(value)):
            self._validity(key, True)

    def _detail(self, key: str, key_name: str, rows: list[dict[str, object]],
                *, valid: bool, **meta: object) -> None:
        if not valid:
            self._validity(key, False)
            return
        payload: dict[str, object] = {"state": "ready", key_name: rows, **meta}
        if self._send(state_topic(key), _json(payload)):
            self._validity(key, True)

    def _publish_card(self) -> None:
        self._send(state_topic("card"), _json(self._card))

    def _card_begin(self, name: str) -> bool:
        if self._card["state"] == "running":
            return False
        self._card = {
            "state": "running", "operation": name, "started_at": _iso(self.now()),
            "finished_at": None, "duration_seconds": None, "error": None,
        }
        self._publish_card()
        return True

    def _card_finish(self, error: str | None = None) -> None:
        started_at = self._card["started_at"]
        if not isinstance(started_at, str):
            raise RuntimeError("operation has no start timestamp")
        finished = self.now()
        duration = max(0.0, finished -
                       datetime.fromisoformat(started_at).timestamp())
        self._card = {
            "state": "error" if error else "success",
            "operation": self._card["operation"],
            "started_at": started_at,
            "finished_at": _iso(finished),
            "duration_seconds": round(duration, 3),
            "error": error,
        }
        self._publish_card()

    def connected(self) -> None:
        """Invoked exactly once per successful MQTT transport connection."""
        with self._lock:
            self._connected = True
            self.monitor.reset_sources()
            self._continuous_since = None
            self._published.clear()
            self._valid.clear()
            self._refresh_pending = None
            self._refresh_started = None
            self._offline_since.clear()
            # Persist unavailability first; stale retained data remains hidden
            # until each source is re-observed after reconnect.
            for key in (*HISTORY, *DETAILS):
                self._validity(key, False, force=True)
            self._send(DISCOVERY, _json(build_discovery(self.version)), force=True)
            self._send(state_topic("version"), self.version, force=True)
            self._send(state_topic("started_at"), self.started_at, force=True)
            self._publish_card()
            for topic_filter in DISCOVERY_FILTERS:
                if not self.subscribe(topic_filter):
                    log.error("MQTT discovery subscription failed: %s", topic_filter)
            for network in self.monitor.networks:
                if not self.subscribe(network.base_topic + "/#"):
                    log.error("Could not subscribe to %s", network.base_topic)
            self.subscribe(HA_STATUS)
            self.subscribe(f"{ROOT}/command/#")
            self._send(APP_AVAILABILITY, "online", force=True)
            self._publish_networks()

    def disconnected(self) -> None:
        with self._lock:
            self._connected = False
            self._continuous_since = None
            self._published.clear()
            self._valid.clear()

    def _all_live(self) -> bool:
        return bool(self.monitor.networks) and all(
            (status := self.monitor.network_status(n.network_id))["inventory_observed"]
            and status["bridge_state"] == "online"
            for n in self.monitor.networks
        )

    def _availability_diagnostic(
        self, network_id: str, ieee: str,
    ) -> tuple[str, str | None]:
        status = self.monitor.network_status(network_id)
        availability = self.monitor.availability(network_id, ieee)
        if status["bridge_state"] != "online":
            return availability, "bridge_unavailable"
        if not status["inventory_observed"]:
            return availability, "inventory_missing"
        if availability == "unknown":
            return availability, "availability_not_reported"
        return availability, None

    def _publish_networks(self) -> None:
        # Until a bridge is verified, zero is not a trustworthy network count.
        self._scalar("networks", len(self.monitor.networks) if self.monitor.networks else None)
        rows = []
        for config in self.monitor.networks:
            status = self.monitor.network_status(config.network_id)
            observed = [
                self._availability_diagnostic(config.network_id, d.ieee_address)
                for d in self.monitor.devices(config.network_id)
            ]
            complete = (status["inventory_observed"]
                        and status["bridge_state"] == "online"
                        and all(reason is None for _, reason in observed))
            rows.append({
                "network_id": config.network_id, "name": config.name,
                "status": status["bridge_state"], "devices": status["devices"],
                "offline": sum(a == "offline" for a, _ in observed) if complete else None,
                "availability_complete": complete,
                "availability_unknown": sum(reason is not None for _, reason in observed),
            })
        self._detail("networks_details", "networks", rows, valid=bool(self.monitor.networks))

    def _publish_inventory_and_availability(self) -> None:
        live = self._all_live()
        self._scalar("devices", self.monitor.total_devices() if live else None)
        rows: list[dict[str, object]] = []
        for config in self.monitor.networks:
            for device in self.monitor.devices(config.network_id):
                availability, reason = self._availability_diagnostic(
                    config.network_id, device.ieee_address,
                )
                rows.append({
                    "ieee_address": device.ieee_address,
                    "network_id": config.network_id,
                    "network_name": config.name,
                    "name": device.friendly_name,
                    "model": device.model,
                    "manufacturer": device.manufacturer,
                    "availability": availability,
                    "availability_reason": reason,
                })
        rows.sort(key=lambda d: (str(d["network_id"]), str(d["name"])))
        unknown = sum(row["availability_reason"] is not None for row in rows)
        self._detail(
            "inventory_details", "devices", rows[:40], valid=live,
            total=len(rows), truncated=len(rows) > 40,
            availability_complete=live and unknown == 0,
            availability_unknown=unknown,
        )
        complete = live and unknown == 0
        offline = [
            {
                "ieee_address": row["ieee_address"],
                "network_id": row["network_id"],
                "name": row["name"], "network_name": row["network_name"],
                "offline_since": self._offline_since.get(
                    (str(row["network_id"]), str(row["ieee_address"]))
                ),
            }
            for row in rows if row["availability"] == "offline"
        ] if complete else []
        self._scalar("offline", len(offline) if complete else None)
        self._detail("offline_details", "devices", offline[:40], valid=complete,
                     total=len(offline), truncated=len(offline) > 40)
        if live and self._continuous_since is None:
            self._continuous_since = self.now()
        elif not live:
            self._continuous_since = None
            self._validity("messages_rate_5m", False)

    def _publish_rankings(self, *, epoch: int) -> None:
        # Exclude incomplete current minute; reconnect gaps are shown as partial
        # coverage rather than silently accepted as full-window observations.
        until = epoch - epoch % 60
        first = self.store.first_bucket()
        for key, minutes in [
            ("top_1h_details", 60), ("top_24h_details", 1440),
            ("top_7d_details", 10080),
        ]:
            from_epoch = until - minutes * 60
            covered = first is not None and first <= from_epoch
            rows = self.store.top(from_epoch=from_epoch, until_epoch=until) if first is not None else []
            self._detail(
                key, "items", rows, valid=self._all_live() and first is not None,
                window_complete=covered,
                observation_start=_iso(first) if first is not None else None,
                period_minutes=minutes,
            )
        # A trustworthy zero requires a fully observed uninterrupted five-minute window.
        trusted = (
            self._all_live() and self._continuous_since is not None
            and epoch - self._continuous_since >= 300
        )
        if trusted:
            self._scalar(
                "messages_rate_5m",
                round(self.store.sum_messages(from_epoch=until - 300,
                                              until_epoch=until) / 5, 2),
            )
        else:
            self._validity("messages_rate_5m", False)

    def tick(self) -> None:
        """Periodic durable aggregation; call even when no MQTT messages arrive."""
        with self._lock:
            epoch = int(self.now())
            current_minute = epoch // 60
            if self._connected and self._last_flush_minute != current_minute:
                self._last_flush_minute = current_minute
                snapshot = self.monitor.counts_snapshot()
                if snapshot:
                    try:
                        self.store.commit_counts(snapshot)
                    except Exception:
                        log.exception("SQLite activity flush failed; retaining counters")
                        return
                    self.monitor.acknowledge_counts(snapshot)
                self._publish_rankings(epoch=epoch)
                if self._last_trim_day != epoch // 86400:
                    self.store.trim_minutes(before_epoch=max(0, epoch - 30 * 86400))
                    self._last_trim_day = epoch // 86400
            if (
                self._refresh_pending is not None and self._refresh_started is not None
                and self.now() - self._refresh_started > 15
            ):
                missing = sorted(self._refresh_pending)
                self._refresh_pending = None
                self._refresh_started = None
                self._card_finish("Нет свежего inventory: " + ", ".join(missing))

    def _start_refresh(self) -> None:
        if not self._card_begin("refresh"):
            return
        self._refresh_pending = (
            {n.network_id for n in self.monitor.networks}
            if self.monitor.networks else {"__discovery__"}
        )
        self._refresh_started = self.now()
        for topic_filter in DISCOVERY_FILTERS:
            self.subscribe(topic_filter)
        for n in self.monitor.networks:
            # Subscribe to retained state, NEVER send a Zigbee2MQTT operation.
            self.subscribe(n.base_topic + "/bridge/devices")
            self.subscribe(n.base_topic + "/bridge/state")

    def complete_check(self, *, latest: str | None, error: str | None = None) -> None:
        """Completion from a bounded non-MQTT release check worker."""
        with self._lock:
            if self._card.get("operation") != "check" or self._card["state"] != "running":
                return
            if error:
                self._card_finish(error)
                return
            if latest is None:
                self._card_finish("Не удалось определить версию")
                return
            self._send(state_topic("latest_version"), latest)
            self._send(state_topic("update_available"),
                       "ON" if _version_tuple(latest) > _version_tuple(self.version) else "OFF")
            self._card_finish()

    def complete_telemetry_delete(self, success: bool) -> None:
        with self._lock:
            if self._card.get("operation") != "delete_telemetry" or self._card["state"] != "running":
                return
            self._card_finish(None if success else "Не удалось удалить телеметрию")

    def receive(self, topic: str, payload: bytes, *, retain: bool = False,
                dup: bool = False, observed_at: int | None = None) -> str:
        """MQTT callback; publishes only snapshots derived from valid observations."""
        with self._lock:
            if topic == HA_STATUS:
                if payload == b"online":
                    self._send(DISCOVERY, _json(build_discovery(self.version)), force=True)
                return "ha_status"
            if topic == f"{ROOT}/command/refresh":
                if not retain and payload == b"PRESS":
                    self._start_refresh()
                return "refresh_command"
            if topic == f"{ROOT}/command/delete_telemetry":
                if not retain and payload == b"DELETE" and self._card_begin("delete_telemetry"):
                    return "delete_telemetry_requested"
                return "delete_telemetry_ignored"
            if topic == f"{ROOT}/command/check_updates":
                if not retain and payload == b"PRESS":
                    if self._card_begin("check"):
                        return "check_updates_requested"
                return "check_updates_ignored"
            discovery = discovery_from_bridge(topic, payload)
            if discovery is not None:
                preferred_id = next((
                    n.network_id for n in self.monitor.networks
                    if n.base_topic == discovery.base_topic
                ), None)
                network, changed = self.store.register_network(
                    discovery.coordinator_ieee, discovery.base_topic,
                    observed_at=int(self.now()), preferred_id=preferred_id,
                )
                if self.monitor.add_network(network):
                    log.info(
                        "Zigbee2MQTT network discovered: %s (%s)",
                        network.base_topic, network.network_id,
                    )
                    self._continuous_since = None
                    if self._refresh_pending is not None:
                        self._refresh_pending.discard("__discovery__")
                        self._refresh_pending.add(network.network_id)
                    if not self.subscribe(network.base_topic + "/#"):
                        log.error("Failed to subscribe to discovered %s", network.base_topic)
                    self._publish_networks()
                    self._publish_inventory_and_availability()
            sample = self.monitor.ingest(
                topic, payload, retain=retain, dup=dup,
                observed_at=observed_at,
            )
            if sample.inventory_changed:
                assert sample.network_id is not None
                self.store.upsert_inventory(
                    self.monitor.devices(sample.network_id),
                    observed_at=int(self.now()),
                )
            if sample.kind == "inventory":
                if self._refresh_pending is not None:
                    assert sample.network_id is not None
                    self._refresh_pending.discard(sample.network_id)
                    if not self._refresh_pending:
                        self._refresh_pending = None
                        self._refresh_started = None
                        self._send(state_topic("last_refresh"), _iso(self.now()))
                        self._card_finish()
            if sample.kind == "device_availability" and sample.network_id and sample.ieee_address:
                identity = sample.network_id, sample.ieee_address
                current = self.monitor.availability(*identity)
                if current == "offline":
                    self._offline_since.setdefault(
                        identity, None if retain else _iso(self.now())
                    )
                else:
                    self._offline_since.pop(identity, None)
            if sample.kind in ("inventory", "bridge_state", "device_availability"):
                self._publish_networks()
                self._publish_inventory_and_availability()
            return sample.kind


def _version_tuple(version: str) -> tuple[int, int, int]:
    import re
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise ValueError("expected release semver X.Y.Z")
    return tuple(int(x) for x in version.split("."))  # type: ignore[return-value]
