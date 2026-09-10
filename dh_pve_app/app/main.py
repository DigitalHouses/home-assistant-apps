from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig, load_config
from .discovery_guest import build_guest_aware_discovery_payload
from .identity import resolve_identity
from .mqtt_bridge import MqttBridge
from .production import _run
from .production_guest import GuestAwareProductionCollectors
from .publish_policy import PublishPolicy
from .runtime_dynamic import DynamicDiscoveryRuntime
from .runtime_settings import RuntimeSettings
from .scheduler import Scheduler
from .state_store import StateStore
from .topics import build_topics
from .topology import TopologyManager

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path("/etc/dh_pve_app/dh_pve_app.conf")
DEFAULT_STATE_DIR = Path("/var/lib/dh_pve_app")


def _version() -> str:
    try:
        return (APP_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _initial_settings(store: StateStore) -> RuntimeSettings:
    persisted = store.load()
    values = persisted.get("runtime_settings")
    if isinstance(values, dict):
        return RuntimeSettings(
            {
                str(key): float(value)
                for key, value in values.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
        )
    return RuntimeSettings()


def build_runtime(config: AppConfig, *, state_dir: Path = DEFAULT_STATE_DIR):
    identity = resolve_identity(config.general)
    topics = build_topics(config.mqtt, identity)
    runtime_store = StateStore(state_dir / "runtime.json")
    settings = _initial_settings(runtime_store)

    discovery_builder = lambda inventory: build_guest_aware_discovery_payload(
        config,
        identity,
        version=_version(),
        inventory=inventory,
    )
    bridge = MqttBridge(
        config.mqtt,
        topics,
        settings,
        discovery_builder({}),
    )

    topology = TopologyManager(runner=_run, node_name=identity.node_name)
    production = GuestAwareProductionCollectors(
        node_name=identity.node_name,
        disk_state_store=StateStore(state_dir / "disks.json"),
        topology=topology,
    )
    collectors = production.mapping()

    scheduler = Scheduler()
    now = time.monotonic()
    fast = settings.get("fast_poll_interval_seconds")
    disk = settings.get("disk_poll_interval_seconds")
    # qm/pct/pvesh and QGA helpers are Perl-heavy on PVE. Keep cheap host
    # metrics fast, but poll guest inventory and guest GPU telemetry at 30 s.
    scheduler.add("guests", interval_seconds=30.0, now=now)
    scheduler.add("gpu", interval_seconds=30.0, now=now)
    for name in ("cpu", "memory", "fans"):
        scheduler.add(name, interval_seconds=fast, now=now)
    scheduler.add("smart", interval_seconds=disk, now=now)
    scheduler.add("storage", interval_seconds=60.0, now=now)
    scheduler.add("host", interval_seconds=86400.0, now=now)

    runtime = DynamicDiscoveryRuntime(
        collectors=collectors,
        bridge=bridge,
        settings=settings,
        publish_policy=PublishPolicy(settings),
        state_store=runtime_store,
        scheduler=scheduler,
        now_iso=_now_iso,
        discovery_builder=discovery_builder,
        setting_tasks={
            "fast_poll_interval_seconds": ("cpu", "memory", "fans"),
            "disk_poll_interval_seconds": ("smart",),
        },
    )
    return bridge, runtime


def run(config: AppConfig, *, state_dir: Path = DEFAULT_STATE_DIR) -> int:
    log = logging.getLogger("dh_pve_app")
    bridge, runtime = build_runtime(config, state_dir=state_dir)
    stop_event = threading.Event()
    initialized = False

    def stop(signum: int, frame: object) -> None:
        log.info("Получен сигнал остановки %s", signum)
        stop_event.set()
        bridge.wake_requested.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    log.info("Запуск DH PVE App %s", _version())
    bridge.start()

    try:
        while not stop_event.is_set():
            if bridge.connected.is_set() and not initialized:
                bridge.reconnect_requested.clear()
                initialized = runtime.startup()
                if initialized:
                    log.info("Первичная публикация MQTT завершена")
                else:
                    log.warning(
                        "Первичная публикация MQTT выполнена не полностью; "
                        "будет повторена после следующего MQTT reconnect"
                    )

            if initialized:
                runtime.process_events()
                runtime.tick(time.monotonic())

            bridge.wake_requested.wait(1.0)
            bridge.wake_requested.clear()
    finally:
        bridge.stop()
        log.info("DH PVE App остановлен")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="dh_pve_app")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate configuration and exit.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    if args.check_config:
        resolve_identity(config.general)
        return 0

    _configure_logging(config.general.log_level)
    return run(config, state_dir=args.state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
