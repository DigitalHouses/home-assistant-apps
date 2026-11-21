"""PBS Agent entry point: read-only polling and retained state before Events."""
from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .collector import collect
from .config import DEFAULT_CONFIG, load_config
from .events import transitions
from .mqtt import Publisher, _read_version, host_ip
from .state import StateStore
from .telemetry import TelemetryClient, TelemetryRunner

STATE_DIR = Path("/var/lib/digitalhouses_pbs_agent")
LOG = logging.getLogger("digitalhouses_pbs_agent")


def display_state(sample: dict, config, ip: str | None) -> dict:
    data = dict(sample)
    data["agent_version"] = _read_version()
    import socket
    data["hostname"] = socket.gethostname()
    data["ip"] = ip or "unknown"
    data["dashboard_limits"] = {"backup_groups": config.dashboard_backup_groups_limit, "task_events": config.dashboard_task_events_limit}
    completed = [x for x in data.get("backups", [])
                 if x.get("last_success_at") is not None]
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
    publisher = Publisher(config)
    last_problem_state = StateStore(state_dir / "incidents.json")
    current_status = StateStore(state_dir / "runtime.json")
    mqtt_status = StateStore(state_dir / "mqtt.json")
    def on_mqtt_connection(status: str, reason: str | None) -> None:
        mqtt_status.save({
            "status": status,
            "reason": reason,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        })
    mqtt_status.save({
        "status": "CONNECTING", "reason": None,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    })
    publisher.on_connection_change = on_mqtt_connection
    try:
        last_success_at = current_status.load().get("last_success_at")
    except (ValueError, OSError):
        last_success_at = None
    stop = threading.Event()

    def stopped(_signal, _frame):
        stop.set()

    signal.signal(signal.SIGINT, stopped)
    signal.signal(signal.SIGTERM, stopped)
    telemetry_runner.start()
    try:
        publisher.start()
        while not stop.is_set():
            started = time.monotonic()
            ip = host_ip(config.mqtt_host, config.mqtt_port)
            try:
                sample = collect(config)
                if sample["status"] in ("HEALTHY", "DEGRADED", "CRITICAL"):
                    last_success_at = sample["observed_at"]
                state = display_state(sample, config, ip)
                state["last_success_at"] = last_success_at
                ev = transitions(sample, last_problem_state)
                success = publisher.state(state)
                # Events are not replayed after an MQTT disconnection.
                if success:
                    for item in ev:
                        publisher.event(item["category"], item["payload"])
                current_status.save({
                    "observed_at": sample["observed_at"],
                    "last_success_at": last_success_at,
                    "status": sample["status"], "mqtt": "CONNECTED" if publisher.connected else "DISCONNECTED",
                    "mqtt_last_ack": publisher.last_ack_at,
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
                    "dashboard_limits": {"backup_groups": config.dashboard_backup_groups_limit, "task_events": config.dashboard_task_events_limit},
                    "summary": {}, "errors": [f"{type(exc).__name__}: {str(exc)[:160]}"],
                    "backup_last_success_at": None, "backup_age_hours": None,
                    "sync_overall": "UNKNOWN", "sync_last_success_at": None,
                }
                publisher.state(unavailable)
                current_status.save({
                    "observed_at": observed, "last_success_at": last_success_at,
                    "status": "UNAVAILABLE",
                    "mqtt": "CONNECTED" if publisher.connected else "DISCONNECTED",
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                    "mqtt_connect_error": publisher.last_connect_error,
                })
            elapsed = time.monotonic() - started
            stop.wait(max(1, config.poll_seconds - elapsed))
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
