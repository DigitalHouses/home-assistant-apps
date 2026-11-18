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

STATE_DIR = Path("/var/lib/digitalhouses_pbs_agent")
LOG = logging.getLogger("digitalhouses_pbs_agent")


def display_state(sample: dict, config, ip: str | None) -> dict:
    data = dict(sample)
    data["agent_version"] = _read_version()
    import socket
    data["hostname"] = socket.gethostname()
    data["ip"] = ip or "unknown"
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
    state_dir.mkdir(parents=True, exist_ok=True)
    publisher = Publisher(config)
    last_problem_state = StateStore(state_dir / "incidents.json")
    current_status = StateStore(state_dir / "runtime.json")
    stop = threading.Event()

    def stopped(_signal, _frame):
        stop.set()

    signal.signal(signal.SIGINT, stopped)
    signal.signal(signal.SIGTERM, stopped)
    publisher.start()
    try:
        while not stop.is_set():
            started = time.monotonic()
            ip = host_ip(config.mqtt_host, config.mqtt_port)
            try:
                sample = collect(config)
                state = display_state(sample, config, ip)
                ev = transitions(sample, last_problem_state)
                success = publisher.state(state)
                # Events are not replayed after an MQTT disconnection.
                if success:
                    for item in ev:
                        publisher.event(item["category"], item["payload"])
                current_status.save({
                    "observed_at": sample["observed_at"],
                    "status": sample["status"], "mqtt": "CONNECTED" if publisher.connected else "DISCONNECTED",
                    "mqtt_last_ack": publisher.last_ack_at,
                    "error_count": len(sample["errors"]),
                })
            except Exception as exc:
                LOG.exception("PBS collection failed")
                current_status.save({
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "status": "UNAVAILABLE", "mqtt": "CONNECTED" if publisher.connected else "DISCONNECTED",
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                })
            elapsed = time.monotonic() - started
            stop.wait(max(1, config.poll_seconds - elapsed))
    finally:
        publisher.stop()
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
