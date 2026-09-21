from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from dataclasses import replace

import psutil
from datetime import datetime, timezone
from pathlib import Path

from .activity_classifier import classify_activity
from .api_runtime import PlexApiRuntime
from .build_info import load_build_info
from .config import AppConfig, load_config
from .discovery import build_discovery_payload, build_topics
from .gpu_collector import GpuStateReader
from .metrics import RollingCpuMetrics, group_current_cpu
from .models import (
    ActivityState,
    CpuGroupMetrics,
    CpuMetrics,
    MonitorSnapshot,
    next_last_refresh,
)
from .mqtt_bridge import MqttBridge
from .presentation_runtime import PlexPublicationRuntime
from .process_collector import (
    CollectorError,
    CpuSampler,
    collect_raw_processes,
    verify_proc_visibility,
)

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(
    "/etc/digitalhouses_plex_monitoring/"
    "digitalhouses_plex_monitoring.conf"
)
UPTIME_HEARTBEAT_SECONDS = 60.0
PLAYBACK_STATE_PATH = Path(
    "/var/lib/digitalhouses_plex_monitoring/playback_session_starts.json"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_cpu() -> CpuMetrics:
    zero = CpuGroupMetrics(current=0.0, average=0.0, maximum=0.0)
    return CpuMetrics(total=zero, scanner=zero, transcoder=zero)


def _error_snapshot(
    previous: MonitorSnapshot | None,
) -> MonitorSnapshot:
    if previous is not None:
        return replace(
            previous,
            collected_at=_utc_now(),
            collector_status="error",
        )
    return MonitorSnapshot(
        collected_at=_utc_now(),
        activity=ActivityState(
            plex_server_running=False,
            scanner_running=False,
            credits_detection=False,
            intro_detection=False,
            thumbnail_generation=False,
            transcoder_running=False,
            activity="unknown",
            scanner_actions=(),
            current_item=None,
        ),
        cpu=_empty_cpu(),
        process_count=0,
        collector_status="error",
        last_refresh=None,
    )


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def run(config: AppConfig) -> int:
    log = logging.getLogger("digitalhouses_plex_monitoring")
    build = load_build_info(APP_ROOT)
    verify_proc_visibility()

    topics = build_topics(config)
    api_runtime = PlexApiRuntime(
        config.plex_api,
        playback_state_path=PLAYBACK_STATE_PATH,
    )
    gpu_collector = GpuStateReader()
    server_boot_time = datetime.fromtimestamp(
        psutil.boot_time(),
        timezone.utc,
    ).isoformat()
    discovery = build_discovery_payload(config, build)
    mqtt = MqttBridge(config, topics, discovery)
    sampler = CpuSampler()
    rolling = RollingCpuMetrics(config.general.cpu_window_seconds)
    publication = PlexPublicationRuntime(
        bridge=mqtt,
        build=build,
        source_interval_seconds=config.general.poll_interval_seconds,
        high_cpu_threshold=config.telemetry.high_load_threshold,
        now_monotonic=time.monotonic,
        server_boot_time=server_boot_time,
        agent_started_at=_utc_now(),
    )

    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        log.info("Shutdown requested by signal %s", signum)
        stop_event.set()
        mqtt.wake_requested.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    log.info(
        "Starting DigitalHouses Plex Agent %s | source=%s commit=%s "
        "instance=%s sampling=%.1fs cpu_window=%.1fs plex_api=%s",
        build.version,
        build.source,
        build.commit[:12] if build.commit != "unknown" else "unknown",
        config.general.instance_id,
        config.general.poll_interval_seconds,
        config.general.cpu_window_seconds,
        "enabled" if config.plex_api.enabled else "disabled",
    )

    mqtt.start()
    last_snapshot: MonitorSnapshot | None = None
    collector_failed = False
    next_poll = time.monotonic()
    next_uptime_heartbeat = time.monotonic() + UPTIME_HEARTBEAT_SECONDS
    legacy_state_cleared = False
    gpu_payload: dict[str, object] = {
        "supported": False,
        "available": False,
        "status": "starting",
        "source": None,
        "pci_address": None,
        "video_busy_percent": None,
        "render_busy_percent": None,
        "video_enhance_busy_percent": None,
        "frequency_mhz": None,
        "rc6_percent": None,
        "temperature_c": None,
    }

    try:
        while not stop_event.is_set():
            now = time.monotonic()
            refresh = mqtt.refresh_requested.is_set()
            republish = mqtt.republish_requested.is_set()
            due = now >= next_poll
            uptime_due = now >= next_uptime_heartbeat

            if not (refresh or republish or due or uptime_due):
                wait_for = min(
                    max(0.0, next_poll - now),
                    max(0.0, next_uptime_heartbeat - now),
                    config.general.poll_interval_seconds,
                )
                mqtt.wake_requested.wait(wait_for)
                mqtt.wake_requested.clear()
                continue

            if republish:
                mqtt.republish_requested.clear()
                if mqtt.connected.is_set():
                    mqtt.publish_discovery()
                    if not legacy_state_cleared:
                        legacy_state_cleared = mqtt.clear_legacy_state()
                    mqtt.set_collector_available(
                        not collector_failed and last_snapshot is not None,
                        force=True,
                    )
                    mqtt.set_plex_api_available(
                        api_runtime.status == "ok",
                        force=True,
                    )
                    if publication.has_cache and publication.republish_cached():
                        next_uptime_heartbeat = (
                            time.monotonic() + UPTIME_HEARTBEAT_SECONDS
                        )

            should_collect = due or refresh or last_snapshot is None

            if should_collect:
                previous_scanner_running = (
                    last_snapshot.activity.scanner_running
                    if last_snapshot is not None
                    else False
                )
                was_failed = collector_failed
                try:
                    raw = collect_raw_processes()
                    sample_time = time.monotonic()
                    samples = sampler.sample(raw, sample_time)
                    activity = classify_activity(samples)
                    total, scanner, transcoder = group_current_cpu(
                        samples,
                        logical_cpu_count=psutil.cpu_count(logical=True) or 1,
                    )
                    cpu = rolling.update(
                        sample_time,
                        total,
                        scanner,
                        transcoder,
                    )
                    collected_at = _utc_now()
                    last_refresh = next_last_refresh(
                        (
                            last_snapshot.last_refresh
                            if last_snapshot is not None
                            else None
                        ),
                        refresh,
                        collected_at,
                    )

                    last_snapshot = MonitorSnapshot(
                        collected_at=collected_at,
                        activity=activity,
                        cpu=cpu,
                        process_count=len(samples),
                        collector_status="ok",
                        last_refresh=last_refresh,
                    )
                    collector_failed = False
                    if was_failed:
                        log.info("Plex process collector recovered")
                    if mqtt.connected.is_set():
                        mqtt.set_collector_available(
                            True,
                            force=republish or was_failed,
                        )
                    next_poll = sample_time + config.general.poll_interval_seconds
                except CollectorError:
                    if not was_failed:
                        log.exception("Plex process collector failed")
                    else:
                        log.debug(
                            "Plex process collector still failing",
                            exc_info=True,
                        )
                    collector_failed = True
                    if mqtt.connected.is_set():
                        mqtt.set_collector_available(
                            False,
                            force=republish or not was_failed,
                        )
                    next_poll = (
                        time.monotonic()
                        + config.general.poll_interval_seconds
                    )

                gpu_payload = gpu_collector.collect()

                scanner_finished = bool(
                    previous_scanner_running
                    and not collector_failed
                    and last_snapshot is not None
                    and not last_snapshot.activity.scanner_running
                )
                api_result = api_runtime.collect(
                    now=time.monotonic(),
                    refresh=refresh,
                    scanner_finished=scanner_finished,
                )

                if api_result.failure_transition:
                    log.warning(
                        "Plex API collector failed: %s",
                        api_runtime.last_error or "unknown error",
                    )
                elif api_result.recovered:
                    log.info("Plex API collector recovered")

                if mqtt.connected.is_set():
                    mqtt.set_plex_api_available(
                        api_runtime.status == "ok",
                        force=(
                            republish
                            or api_result.recovered
                            or api_result.failure_transition
                        ),
                    )

                if api_result.libraries_changed:
                    discovery = build_discovery_payload(
                        config,
                        build,
                        api_runtime.libraries,
                    )
                    mqtt.set_discovery_payload(discovery)
                    if mqtt.connected.is_set():
                        mqtt.publish_discovery()

            if refresh:
                mqtt.refresh_requested.clear()

            state_snapshot: MonitorSnapshot | None
            if collector_failed:
                state_snapshot = _error_snapshot(last_snapshot)
            else:
                state_snapshot = last_snapshot

            if (
                should_collect
                and state_snapshot is not None
                and mqtt.connected.is_set()
            ):
                if publication.publish_snapshot(
                    state_snapshot,
                    api_runtime.payload(),
                    gpu_payload=gpu_payload,
                    manual_refresh=refresh,
                ):
                    next_uptime_heartbeat = (
                        time.monotonic() + UPTIME_HEARTBEAT_SECONDS
                    )

            if (
                mqtt.connected.is_set()
                and time.monotonic() >= next_uptime_heartbeat
            ):
                if publication.publish_uptime_heartbeat():
                    next_uptime_heartbeat = (
                        time.monotonic() + UPTIME_HEARTBEAT_SECONDS
                    )

    finally:
        mqtt.stop()
        log.info("DigitalHouses Plex Agent stopped")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )
    args = parser.parse_args()
    config = load_config(args.config)
    _configure_logging(config.general.log_level)
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
