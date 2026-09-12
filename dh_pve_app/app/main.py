from __future__ import annotations

import argparse
import json
import logging
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig, UpsConfig, load_config
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
from .topics import build_topics, build_ups_topics
from .topology import TopologyManager
from .ups_nut import read_ups
from .ups_policy_apply import ManagedNutPaths, PolicyApplyError, UpsPolicyApplier
from .ups_policy_host import read_policy_safety_facts
from .ups_policy_preflight import (
    PreflightCheck,
    UpsPolicyPreflight,
    read_policy_preflight,
)
from .ups_runtime import UpsRuntime
from .ups_scan import UpsScanner

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


def _now_local() -> datetime:
    return datetime.now().astimezone()


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

    topology = TopologyManager(runner=_run)
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


def build_ups_policy_applier(
    config: UpsConfig,
    *,
    applier_factory=UpsPolicyApplier,
    ups_reader=read_ups,
):
    if not config.policy_apply_enabled:
        return None

    def effective_restart_delay_reader() -> int:
        snapshot = ups_reader(config)
        value = snapshot.ups_start_delay_seconds
        if value is None or value < 0 or not float(value).is_integer():
            raise PolicyApplyError(
                "UPS не сообщил корректную задержку восстановления питания."
            )
        return int(value)

    applier = applier_factory(
        paths=ManagedNutPaths(),
        ups_name=config.name,
        runner=subprocess.run,
        effective_restart_delay_reader=effective_restart_delay_reader,
    )
    return applier.apply


def build_ups_runtime(
    config: AppConfig,
    bridge,
    *,
    selected_name: str | None,
    state_dir: Path = DEFAULT_STATE_DIR,
) -> UpsRuntime | None:
    if not selected_name:
        return None
    identity = resolve_identity(config.general)
    bridge.configure_ups(build_ups_topics(config.mqtt, identity))
    runtime_config = replace(config.ups, enabled=True, name=selected_name)
    return UpsRuntime(
        config=runtime_config,
        mqtt_config=config.mqtt,
        bridge=bridge,
        identity=identity,
        version=_version(),
        state_store=StateStore(state_dir / "ups_runtime.json"),
        now_iso=_now_iso,
        now_local=_now_local,
        now_monotonic=time.monotonic,
        policy_facts_reader=lambda: read_policy_safety_facts(runtime_config),
        policy_applier=build_ups_policy_applier(runtime_config),
    )


def build_ups_scanner(
    config: AppConfig,
    *,
    state_dir: Path = DEFAULT_STATE_DIR,
) -> UpsScanner:
    return UpsScanner(
        config.ups,
        StateStore(state_dir / "ups_selection.json"),
        now_iso=_now_iso,
    )


def build_ups_policy_preflight(
    config: AppConfig,
    *,
    state_dir: Path = DEFAULT_STATE_DIR,
    preflight_reader: Callable[[UpsConfig], UpsPolicyPreflight] = read_policy_preflight,
) -> UpsPolicyPreflight:
    scanner = build_ups_scanner(config, state_dir=state_dir)
    selected_name = scanner.selected_name()
    if not selected_name:
        return UpsPolicyPreflight(
            state="Blocked",
            ready=False,
            checks=(
                PreflightCheck(
                    "ups_selected",
                    False,
                    "UPS еще не выбран; сначала выполните безопасное сканирование UPS.",
                ),
            ),
            guest_shutdown_budget_seconds=None,
        )
    runtime_config = replace(config.ups, enabled=True, name=selected_name)
    return preflight_reader(runtime_config)


def run(config: AppConfig, *, state_dir: Path = DEFAULT_STATE_DIR) -> int:
    log = logging.getLogger("dh_pve_app")
    bridge, runtime = build_runtime(config, state_dir=state_dir)
    scanner = build_ups_scanner(config, state_dir=state_dir)
    ups_runtime = build_ups_runtime(
        config,
        bridge,
        selected_name=scanner.selected_name(),
        state_dir=state_dir,
    )
    stop_event = threading.Event()
    initialized = False
    ups_startup_attempted = False

    def stop(signum: int, frame: object) -> None:
        log.info("Получен сигнал остановки %s", signum)
        stop_event.set()
        bridge.wake_requested.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    log.info("Запуск DH PVE App %s", _version())
    if ups_runtime is not None:
        log.info("Найден сохраненный UPS %s", ups_runtime.config.name)
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

                if bridge.ups_scan_requested.is_set():
                    bridge.ups_scan_requested.clear()
                    outcome = scanner.scan()
                    bridge.publish_ups_scan_state(outcome.payload())
                    log.info("Сканирование UPS: %s", outcome.result)

                    if outcome.selected_name is not None:
                        if ups_runtime is None or outcome.selection_changed:
                            ups_runtime = build_ups_runtime(
                                config,
                                bridge,
                                selected_name=outcome.selected_name,
                                state_dir=state_dir,
                            )
                            ups_startup_attempted = False
                        elif outcome.count == 1:
                            ups_runtime.manual_refresh()

                if ups_runtime is not None and not ups_startup_attempted:
                    bridge.ups_reconnect_requested.clear()
                    bridge.clear_legacy_ups_discovery()
                    ups_ok = ups_runtime.startup()
                    ups_startup_attempted = True
                    if ups_ok:
                        log.info("Первичная публикация DH PVE UPS завершена")
                    else:
                        log.warning(
                            "UPS через NUT пока недоступен; мониторинг PVE продолжает работать"
                        )

                if ups_runtime is not None and ups_startup_attempted:
                    ups_runtime.process_events()
                    ups_runtime.tick(time.monotonic())

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
    parser.add_argument(
        "--ups-policy-preflight",
        action="store_true",
        help="Read UPS/NUT/PVE commissioning state, print JSON, and exit without MQTT.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    if args.check_config:
        resolve_identity(config.general)
        return 0
    if args.ups_policy_preflight:
        report = build_ups_policy_preflight(config, state_dir=args.state_dir)
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return 0 if report.ready else 2

    _configure_logging(config.general.log_level)
    return run(config, state_dir=args.state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
