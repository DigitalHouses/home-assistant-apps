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
    APP_AVAILABILITY, DETAILS, DISCOVERY, EVENT_TOPIC, HA_STATUS, HISTORY, ROOT,
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
        # Separate event baselines. Retained MQTT is authoritative state
        # recovery, not evidence of a new transition; never emit on cold boot.
        self._event_bridge_state: dict[str, str] = {}
        self._event_device_state: dict[tuple[str, str], str] = {}
        self._refresh_pending: set[str] | None = None
        self._refresh_bridge_pending: set[str] | None = None
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

    def _emit_event(self, event_type: str, **facts: object) -> None:
        """Transient machine fact after the retained source state is published.

        MQTT transport uses QoS 1. Event payloads are never retained, never
        localized and never used as substitutes for durable current state.
        """
        event = {
            "schema_version": 1, "event_type": event_type,
            "observed_at": _iso(self.now()), **facts,
        }
        if not self.publish(EVENT_TOPIC, _json(event), False):
            log.warning("Failed to publish Zigbee Monitor machine event: %s", event_type)

    def _publish_card(self) -> None:
        self._send(state_topic("card"), _json(self._card))

    def _publish_refresh_state(self) -> None:
        self._send(state_topic("refresh_state"), _json(self._refresh_state))

    def _finish_refresh(self, error: str | None = None) -> None:
        if self._refresh_state["state"] != "updating":
            return
        started = str(self._refresh_state["started_at"])
        finished = self.now()
        duration = max(0.0, finished - datetime.fromisoformat(started).timestamp())
        self._refresh_state = {
            "state": "error" if error else "idle",
            "started_at": started, "finished_at": _iso(finished),
            "duration_seconds": round(duration, 3), "error": error,
        }
        self._publish_refresh_state()
        self._card_finish(error)

    def _try_complete_refresh(self) -> None:
        """Complete after fresh bridge and inventory snapshots, even if Z2M availability is disabled.

        Internet App's product-level Refresh reports success when it has
        republished its valid current observational state; a missing optional
        health source does not retroactively fail the whole user action.
        Zigbee2MQTT availability is independent of inventory and MQTT activity.
        Its dedicated offline sensors remain unavailable until proven valid.
        """
        if (self._refresh_pending is None or
                self._refresh_bridge_pending is None or self._refresh_started is None):
            return
        if self._refresh_pending or self._refresh_bridge_pending:
            return
        if not self.monitor.networks or not self._all_live():
            return
        # Discovery/inventory are required and must be published. Offline data
        # are optional: they MUST remain unavailable without per-device samples.
        if (self._valid.get("networks_details") is not True or
                self._valid.get("inventory_details") is not True):
            return
        if not self._send(state_topic("last_refresh"), _iso(self.now())):
            self._refresh_pending = None
            self._refresh_bridge_pending = None
            self._refresh_started = None
            self._finish_refresh("Не удалось опубликовать последнее обновление")
            return
        self._refresh_pending = None
        self._refresh_bridge_pending = None
        self._refresh_started = None
        self._finish_refresh()

    def _card_begin(self, name: str) -> bool:
        if self._card["state"] == "running":
            return False
        self._card_success_until = None
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
        self._card_success_until = None if error else self.now() + 5
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
            self._refresh_bridge_pending = None
            self._refresh_started = None
            if self._refresh_state["state"] == "updating":
                self._refresh_state = {
                    **self._refresh_state, "state": "error",
                    "finished_at": _iso(self.now()),
                    "error": "MQTT отключился во время обновления",
                }
                self._card = {
                    **self._card, "state": "error",
                    "finished_at": _iso(self.now()),
                    "error": "MQTT отключился во время обновления",
                }
                self._card_success_until = None
            self._offline_since.clear()
            self._event_bridge_state.clear()
            self._event_device_state.clear()
            # Persist unavailability first; stale retained data remains hidden
            # until each source is re-observed after reconnect.
            for key in (*HISTORY, *DETAILS):
                self._validity(key, False, force=True)
            self._send(DISCOVERY, _json(build_discovery(self.version)), force=True)
            self._send(state_topic("version"), self.version, force=True)
            self._send(state_topic("started_at"), self.started_at, force=True)
            self._publish_card()
            self._publish_refresh_state()
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
            self._event_bridge_state.clear()
            self._event_device_state.clear()

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
            confirmed_offline = sum(a == "offline" and reason is None
                                    for a, reason in observed)
            rows.append({
                "network_id": config.network_id, "name": config.name,
                "status": status["bridge_state"], "devices": status["devices"],
                # A positive value is a guaranteed lower bound, even with
                # unknown peers. Zero is only valid with complete coverage.
                "offline": confirmed_offline if complete or confirmed_offline else None,
                "availability_complete": complete,
                "availability_unknown": sum(reason is not None for _, reason in observed),
            })
        self._detail("networks_details", "networks", rows, valid=bool(self.monitor.networks))

    def _publish_inventory_and_availability(self) -> None:
        live = self._all_live()
        self._scalar("devices", self.monitor.total_devices() if live else None)
        # SQLite holds durable timestamps; pending in-memory observations cover
        # the current incomplete minute. Neither is a Zigbee RF availability
        # assertion, and retained payloads never produce a timestamp.
        last_seen = self.store.last_mqtt_messages()
        for identity, epoch in self.monitor.mqtt_activity_snapshot().items():
            last_seen[identity] = max(last_seen.get(identity, 0), epoch)
        rows: list[dict[str, object]] = []
        for config in self.monitor.networks:
            for device in self.monitor.devices(config.network_id):
                availability, reason = self._availability_diagnostic(
                    config.network_id, device.ieee_address,
                )
                labels = {"online": "В сети", "offline": "Не в сети", "unknown": "Нет данных"}
                reasons = {
                    "bridge_unavailable": "Zigbee2MQTT недоступен",
                    "inventory_missing": "Нет инвентаризации Zigbee2MQTT",
                    "availability_not_reported": "Нет сообщения availability",
                }
                power = device.power_source
                power_class = (
                    "battery" if power == "Battery" else
                    "mains" if power and power.startswith("Mains") else
                    "external" if power == "DC Source" else "unknown"
                )
                identity = (config.network_id, device.ieee_address)
                mqtt_seen = last_seen.get(identity)
                rows.append({
                    # Power is authoritative inventory metadata from Z2M,
                    # not a conclusion from Router / EndDevice role.
                    "device_type": device.device_type,
                    "power_source": power,
                    "power_class": power_class,
                    "power_label": {
                        "battery": "Батарея", "mains": "Сеть",
                        "external": "Внешнее питание", "unknown": "Неизвестно",
                    }[power_class],
                    "last_mqtt_message_at": _iso(mqtt_seen) if mqtt_seen is not None else None,
                    "availability_label": labels.get(availability, "Нет данных"),
                    "availability_reason_label": reasons.get(reason) if reason else None,
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
            for row in rows
            if row["availability"] == "offline" and row["availability_reason"] is None
        ] if live else []
        # A confirmed offline remains visible even if another device has not
        # reported availability. Unknown-only still never becomes fake zero.
        self._scalar("offline", len(offline) if complete or offline else None)
        self._detail(
            "offline_details", "devices", offline[:40], valid=live,
            total=len(offline), truncated=len(offline) > 40,
            availability_complete=complete, availability_unknown=unknown,
        )
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
                last_messages = self.monitor.mqtt_activity_snapshot()
                if snapshot or last_messages:
                    try:
                        self.store.commit_counts(snapshot, last_messages=last_messages)
                    except Exception:
                        log.exception("SQLite activity flush failed; retaining counters")
                        return
                    self.monitor.acknowledge_counts(snapshot)
                    self.monitor.acknowledge_mqtt_activity(last_messages)
                    # Bounded details entity, explicitly excluded from Recorder.
                    # Update once per minute, not on every MQTT message.
                    if self._all_live():
                        self._publish_inventory_and_availability()
                self._publish_rankings(epoch=epoch)
                if self._last_trim_day != epoch // 86400:
                    self.store.trim_minutes(before_epoch=max(0, epoch - 30 * 86400))
                    self._last_trim_day = epoch // 86400
            if (
                self._card_success_until is not None
                and self.now() >= self._card_success_until
                and self._card["state"] == "success"
            ):
                self._card_success_until = None
                self._card = {
                    "state": "idle", "operation": None,
                    "started_at": None, "finished_at": None,
                    "duration_seconds": None, "error": None,
                }
                self._publish_card()
            if (
                self._refresh_pending is not None and self._refresh_started is not None
                and self.now() - self._refresh_started > 15
            ):
                missing_inventory = sorted(self._refresh_pending)
                missing_bridge = sorted(self._refresh_bridge_pending or ())
                unavailable_bridge = [
                    n.network_id for n in self.monitor.networks
                    if self.monitor.network_status(n.network_id)["bridge_state"] != "online"
                    and n.network_id not in missing_bridge
                ]
                self._refresh_pending = None
                self._refresh_bridge_pending = None
                self._refresh_started = None
                problems = []
                if missing_inventory:
                    problems.append("inventory: " + ", ".join(missing_inventory))
                if missing_bridge or unavailable_bridge:
                    problems.append("bridge: " + ", ".join(sorted(
                        set(missing_bridge + unavailable_bridge))))
                self._finish_refresh(
                    "Не получены данные Zigbee2MQTT (" + "; ".join(problems or ["MQTT"]) + ")"
                )

    def _start_refresh(self) -> None:
        if not self._card_begin("refresh"):
            return
        self._refresh_state = {
            "state": "updating", "started_at": _iso(self.now()),
            "finished_at": None, "duration_seconds": None, "error": None,
        }
        self._publish_refresh_state()
        self._refresh_pending = (
            {n.network_id for n in self.monitor.networks}
            if self.monitor.networks else {"__discovery__"}
        )
        self._refresh_bridge_pending = {
            n.network_id for n in self.monitor.networks
        }
        self._refresh_started = self.now()
        subscriptions = list(DISCOVERY_FILTERS)
        for n in self.monitor.networks:
            # Retained read only. No Zigbee2MQTT control, reporting, interview or ping.
            subscriptions.extend((
                n.base_topic + "/bridge/devices",
                n.base_topic + "/bridge/state",
            ))
        for topic_filter in subscriptions:
            if not self.subscribe(topic_filter):
                self._refresh_pending = None
                self._refresh_bridge_pending = None
                self._refresh_started = None
                self._finish_refresh("Не удалось подписаться на MQTT: " + topic_filter)
                return

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
                        if self._refresh_bridge_pending is not None:
                            self._refresh_bridge_pending.add(network.network_id)
                    # The new route needs a fresh event baseline.
                    self._event_bridge_state.pop(network.network_id, None)
                    for identity in list(self._event_device_state):
                        if identity[0] == network.network_id:
                            self._event_device_state.pop(identity, None)
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
            if sample.kind == "inventory" and self._refresh_pending is not None:
                assert sample.network_id is not None
                self._refresh_pending.discard(sample.network_id)
            if sample.kind == "bridge_state" and self._refresh_bridge_pending is not None:
                assert sample.network_id is not None
                self._refresh_bridge_pending.discard(sample.network_id)
            event: tuple[str, dict[str, object]] | None = None
            if sample.kind == "bridge_state" and sample.network_id:
                network_id = sample.network_id
                current = str(self.monitor.network_status(network_id)["bridge_state"])
                previous = self._event_bridge_state.get(network_id)
                self._event_bridge_state[network_id] = current
                if current == "offline":
                    # Prevent a bridge restart from creating hundreds of
                    # synthetic device "recovered" transitions.
                    for identity in list(self._event_device_state):
                        if identity[0] == network_id:
                            self._event_device_state.pop(identity, None)
                if previous in ("online", "offline") and previous != current and not retain and not dup:
                    net = next(n for n in self.monitor.networks if n.network_id == network_id)
                    event = (
                        "zigbee2mqtt_online" if current == "online" else "zigbee2mqtt_offline",
                        {
                            "network_id": network_id, "base_topic": net.base_topic,
                            "previous_state": previous, "current_state": current,
                            "severity": "info" if current == "online" else "warning",
                        },
                    )
            if sample.kind == "device_availability" and sample.network_id and sample.ieee_address:
                identity = sample.network_id, sample.ieee_address
                current = self.monitor.availability(*identity)
                if current == "offline":
                    self._offline_since.setdefault(
                        identity, None if retain else _iso(self.now())
                    )
                else:
                    self._offline_since.pop(identity, None)
                status = self.monitor.network_status(identity[0])
                if status["bridge_state"] == "online" and status["inventory_observed"]:
                    previous = self._event_device_state.get(identity)
                    self._event_device_state[identity] = current
                    if previous in ("online", "offline") and previous != current and not retain and not dup:
                        device = self.monitor.get_device(*identity)
                        assert device is not None
                        event = (
                            "device_online" if current == "online" else "device_offline",
                            {
                                "network_id": identity[0],
                                "ieee_address": identity[1],
                                "friendly_name": device.friendly_name,
                                "previous_state": previous, "current_state": current,
                                "severity": "info" if current == "online" else "warning",
                            },
                        )
            if sample.kind in ("inventory", "bridge_state", "device_availability"):
                self._publish_networks()
                self._publish_inventory_and_availability()
                self._try_complete_refresh()
                if event is not None:
                    self._emit_event(event[0], **event[1])
            return sample.kind


def _version_tuple(version: str) -> tuple[int, int, int]:
    import re
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise ValueError("expected release semver X.Y.Z")
    return tuple(int(x) for x in version.split("."))  # type: ignore[return-value]
