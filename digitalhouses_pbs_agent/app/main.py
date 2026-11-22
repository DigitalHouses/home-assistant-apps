"""PBS Agent entry point: read-only polling and retained state before Events."""
from __future__ import annotations

import argparse
import json
import queue
import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .collector import collect
from .control import Controller
from .config import DEFAULT_CONFIG, load_config
from .events import transitions
from .mqtt import Publisher, _read_version, host_ip
from .state import StateStore, ViewLimits
from .telemetry import TelemetryClient, TelemetryRunner

STATE_DIR = Path("/var/lib/digitalhouses_pbs_agent")
LOG = logging.getLogger("digitalhouses_pbs_agent")


def display_state(sample: dict, config, ip: str | None) -> dict:
    data = dict(sample)
    data["agent_version"] = _read_version()
    for store in data.get("datastores", []):
        name = store.get("name", "PBS")
        backend = store.get("backend")
        health = store.get("health")
        percent = store.get("used_percent")
        if backend == "S3":
            store.update(card_name=name, card_secondary="S3 · объём не определён",
                         card_percent=0, card_color="grey", card_icon="mdi:cloud-outline")
        elif type(percent) in (int, float):
            store["card_name"] = f"{name} · занято {percent:.1f}%"
            total = store.get("total_bytes")
            used = store.get("used_bytes")
            store["card_secondary"] = (
                f"Занято {used/1073741824:.2f} / {total/1073741824:.2f} GiB"
                if type(total) in (int, float) and type(used) in (int, float)
                else f"Занято {percent:.1f}%"
            )
            store["card_percent"] = percent
            store["card_color"] = {"HEALTHY": "green",
                                   "DEGRADED": "orange",
                                   "CRITICAL": "red"}.get(health, "grey")
            store["card_icon"] = ("mdi:database-check" if health == "HEALTHY"
                                  else "mdi:database-alert" if health in ("DEGRADED", "CRITICAL")
                                  else "mdi:database")
        else:
            store.update(card_name=name, card_secondary="Данные недоступны",
                         card_percent=0, card_color="grey", card_icon="mdi:database")
    import socket
    data["hostname"] = socket.gethostname()
    data["ip"] = ip or "unknown"
    completed = [x for x in data.get("backups", [])
                 if x.get("last_success_at") is not None]
    if not completed:
        completed = [{
            "last_success_at": g.get("last_backup_at"),
            "age_hours": g.get("age_hours"),
        } for g in data.get("backup_groups", []) if g.get("last_backup_at")]
    latest = max(completed, key=lambda x: x["last_success_at"]) if completed else None
    data["backup_last_success_at"] = latest["last_success_at"] if latest else None
    data["backup_age_hours"] = max(
        (x["age_hours"] for x in completed if x["age_hours"] is not None),
        default=None,
    )
    sync = data.get("sync_jobs", [])
    data["sync_overall"] = (
        "NOT_CONFIGURED" if not sync else
        "FAILED" if any(x.get("status") == "FAILED" for x in sync) else
        "UNKNOWN" if any(x.get("status") in ("UNKNOWN", "NEVER_RUN") for x in sync) else
        "OK" if all(x.get("status") == "OK" for x in sync) else
        "NOT_CONFIGURED"
    )
    success = [x.get("last_run_at") for x in sync
               if x.get("status") == "OK" and x.get("last_run_at")]
    data["sync_last_success_at"] = max(success) if success else None
    return data


def run(config_path: Path = DEFAULT_CONFIG, state_dir: Path = STATE_DIR) -> int:
    config = load_config(config_path)
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not config.telemetry_enabled:
        LOG.error("Telemetry/privacy terms not accepted: PBS Agent does not activate. "
                  "Set telemetry_enabled=true in native INI after reviewing the policy.")
        return 0
    state_dir.mkdir(parents=True, exist_ok=True)
    telemetry = TelemetryClient(
        enabled=True,
        version=_read_version(),
        state_store=StateStore(state_dir / "telemetry.json"),
        build_info_path=Path(__file__).resolve().parents[1] / "BUILD_INFO",
    )
    telemetry_runner = TelemetryRunner(telemetry)
    publisher = Publisher(
        config,
        view_limits=ViewLimits(StateStore(state_dir / "view_limits.json")),
        job_registry=StateStore(state_dir / "discovery_jobs.json"),
        timezone_store=StateStore(state_dir / "ha_timezone.json"),
    )
    controller = Controller(state_dir, publisher)
    last_problem_state = StateStore(state_dir / "incidents.json")
    current_status = StateStore(state_dir / "runtime.json")
    mqtt_status = StateStore(state_dir / "mqtt.json")
    try:
        previous_mqtt = mqtt_status.load()
    except (ValueError, OSError):
        previous_mqtt = {}
    last_connected = previous_mqtt.get("last_connected")
    def on_mqtt_connection(status: str, reason: str | None) -> None:
        nonlocal last_connected
        observed = datetime.now(timezone.utc).isoformat()
        if status == "CONNECTED":
            last_connected = observed
        mqtt_status.save({
            "status": status,
            "reason": reason,
            "observed_at": observed,
            "last_connected": last_connected,
        })
    mqtt_status.save({
        "status": "CONNECTING", "reason": None,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "last_connected": last_connected,
    })
    publisher.on_connection_change = on_mqtt_connection
    try:
        last_success_at = current_status.load().get("last_success_at")
    except (ValueError, OSError):
        last_success_at = None
    # In-process only; repeated polls do not re-query immutable snapshot stats.
    upload_cache: dict = {}
    stop = threading.Event()

    def stopped(_signal, _frame):
        stop.set()

    signal.signal(signal.SIGINT, stopped)
    signal.signal(signal.SIGTERM, stopped)
    telemetry_runner.start()
    try:
        publisher.start()
        next_collection = time.monotonic()
        next_auto_check = time.monotonic() + 4
        while not stop.is_set():
            controller.tick()
            while not publisher.auto_update_commands.empty():
                controller.set_auto_update(publisher.auto_update_commands.get_nowait())
            now = time.monotonic()
            if now >= next_auto_check:
                if controller.start_check(manual=False):
                    next_auto_check = now + 24 * 3600
                else:
                    next_auto_check = now + 60
            refresh = False
            while not publisher.commands.empty():
                try:
                    command = publisher.commands.get_nowait()
                except queue.Empty:
                    break
                if command == "refresh":
                    if controller.begin("refresh"):
                        refresh = True
                elif command == "check":
                    controller.start_check(manual=True)
                elif command in {"install", "restart"}:
                    controller.queue_worker(command)
            if not refresh and now < next_collection:
                stop.wait(min(1, max(0.05, next_collection - now)))
                continue
            started = time.monotonic()
            next_collection = started + config.poll_seconds
            ip = host_ip(config.mqtt_host, config.mqtt_port)
            try:
                sample = collect(config, upload_cache=upload_cache)
                if sample["status"] in ("HEALTHY", "DEGRADED", "CRITICAL"):
                    last_success_at = sample["observed_at"]
                state = display_state(sample, config, ip)
                state["last_success_at"] = last_success_at
                ev = transitions(sample, last_problem_state)
                success = publisher.state(state)
                controller.collection_at(last_success_at)
                if refresh:
                    good = sample["status"] in ("HEALTHY", "DEGRADED", "CRITICAL")
                    controller.finish(
                        "refresh",
                        None if good and success else
                        ("Нет подтверждения MQTT PUBACK" if not success
                         else "PBS не предоставил достоверный статус"),
                    )
                # Events are not replayed after an MQTT disconnection.
                if success:
                    for item in ev:
                        publisher.event(item["category"], item["payload"])
                current_status.save({
                    "pid": os.getpid(),
                    "observed_at": sample["observed_at"],
                    "last_success_at": last_success_at,
                    "status": sample["status"], "mqtt": "CONNECTED" if publisher.connected else "DISCONNECTED",
                    "mqtt_last_ack": publisher.last_ack_at,
                    "mqtt_publish_state": success,
                    "pbs_version": sample.get("pbs_version"),
                    "datastores": [{
                        "name": x.get("name"), "health": x.get("health"),
                        "used_percent": x.get("used_percent"),
                    } for x in sample.get("datastores", []) if isinstance(x, dict)],
                    "summary": {
                        "backup_groups": len(sample.get("backup_groups", [])),
                        "maintenance_jobs": len(sample.get("maintenance_jobs", [])),
                        "active_problems": sample.get("summary", {}).get("active_problems"),
                        "sync_overall": sample.get("sync_overall"),
                    },
                    "error_count": len(sample["errors"]),
                    "pbs_errors": sample["errors"][:8],
                    "mqtt_connect_error": publisher.last_connect_error,
                })
            except Exception as exc:
                LOG.exception("PBS collection failed")
                observed = datetime.now(timezone.utc).isoformat()
                # Never leave an old retained green state after a collector
                # crash: publish explicit unavailability instead.
                unavailable = {
                    "observed_at": observed, "last_success_at": last_success_at,
                    "status": "UNAVAILABLE", "hostname": __import__("socket").gethostname(),
                    "ip": ip or "unknown", "agent_version": _read_version(),
                    "pbs_version": None, "datastores": [], "backups": [],
                    "sync_jobs": [], "verify_jobs": [], "prune_jobs": [],
                    "gc": [], "maintenance_jobs": [], "task_history": [],
                    "task_history_status": "UNAVAILABLE", "backup_groups": [],
                    "backup_groups_status": "UNAVAILABLE", "pull_sync_jobs": [], "zfs": {"status": "UNKNOWN", "pools": []},
                    "summary": {}, "errors": [f"{type(exc).__name__}: {str(exc)[:160]}"],
                    "backup_last_success_at": None, "backup_age_hours": None,
                    "sync_overall": "UNKNOWN", "sync_last_success_at": None,
                }
                publisher.state(unavailable)
                if refresh:
                    controller.finish("refresh", "Сбор данных PBS завершился ошибкой")
                current_status.save({
                    "pid": os.getpid(),
                    "observed_at": observed, "last_success_at": last_success_at,
                    "status": "UNAVAILABLE",
                    "mqtt": "CONNECTED" if publisher.connected else "DISCONNECTED",
                    "mqtt_publish_state": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                    "mqtt_connect_error": publisher.last_connect_error,
                })
            # Keep operation state responsive independently of the PBS poll cadence.
            controller.tick()
            stop.wait(0.1)
    finally:
        publisher.stop()
        telemetry_runner.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    if args.check_config:
        load_config(args.config)
        print("OK")
        return 0
    return run(args.config, args.state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
