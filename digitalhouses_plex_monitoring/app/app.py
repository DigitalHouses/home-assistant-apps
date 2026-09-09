from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .activity_classifier import classify_activity
from .api_runtime import PlexApiRuntime
from .build_info import load_build_info
from .config import AppConfig, load_config
from .discovery import build_discovery_payload, build_topics
from .metrics import RollingCpuMetrics, group_current_cpu
from .models import (
    ActivityState,
    CpuGroupMetrics,
    CpuMetrics,
    MonitorSnapshot,
    build_state_payload,
    next_last_refresh,
)
from .mqtt_bridge import MqttBridge
from .process_collector import (
    CollectorError,
    CpuSampler,
    collect_raw_processes,
    verify_proc_visibility,
)
from .publish_policy import PublishPolicy

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(
    "/etc/digitalhouses_plex_monitoring/"
    "digitalhouses_plex_monitoring.conf"
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
    api_runtime = PlexApiRuntime(config.plex_api)
    discovery = build_discovery_payload(config, build)
    mqtt = MqttBridge(config, topics, discovery)
    sampler = CpuSampler()
    rolling = RollingCpuMetrics(config.general.cpu_window_seconds)
    policy = PublishPolicy(
        config.telemetry.cpu_change_threshold,
        config.telemetry.high_load_threshold,
        config.telemetry.high_load_publish_interval_seconds,
    )

    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        log.info("Shutdown requested by signal %s", signum)
        stop_event.set()
        mqtt.wake_requested.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    log.info(
        "Starting DigitalHouses Plex Monitoring %s | source=%s commit=%s "
        "instance=%s poll=%.1fs cpu_window=%.1fs plex_api=%s",
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

    try:
        while not stop_event.is_set():
            now = time.monotonic()
            refresh = mqtt.refresh_requested.is_set()
            republish = mqtt.republish_requested.is_set()
            due = now >= next_poll

            if not (refresh or republish or due):
                wait_for = min(
                    max(0.0, next_poll - now),
                    config.general.poll_interval_seconds,
                )
                mqtt.wake_requested.wait(wait_for)
                mqtt.wake_requested.clear()
                continue

            if republish:
                mqtt.republish_requested.clear()
                if mqtt.connected.is_set():
                    mqtt.publish_discovery()
                    mqtt.set_collector_available(
                        not collector_failed and last_snapshot is not None,
                        force=True,
                    )
                    mqtt.set_plex_api_available(
                        api_runtime.status == "ok",
                        force=True,
                    )

            should_collect = due or refresh or last_snapshot is None
            recovered = False
            process_failure_transition = False
            api_changed = False
            api_recovered = False
            api_failure_transition = False

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
                    total, scanner, transcoder = group_current_cpu(samples)
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
                    recovered = was_failed
                    if recovered:
                        log.info("Plex process collector recovered")
                    if mqtt.connected.is_set():
                        mqtt.set_collector_available(
                            True,
                            force=republish or recovered,
                        )
                    next_poll = (
                        sample_time
                        + config.general.poll_interval_seconds
                    )
                except CollectorError:
                    if not was_failed:
                        log.exception("Plex process collector failed")
                    else:
                        log.debug(
                            "Plex process collector still failing",
                            exc_info=True,
                        )
                    collector_failed = True
                    process_failure_transition = not was_failed
                    if mqtt.connected.is_set():
                        mqtt.set_collector_available(
                            False,
                            force=republish or process_failure_transition,
                        )
                    next_poll = (
                        time.monotonic()
                        + config.general.poll_interval_seconds
                    )

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
                api_changed = api_result.changed
                api_recovered = api_result.recovered
                api_failure_transition = api_result.failure_transition

                if api_failure_transition:
                    log.warning(
                        "Plex API collector failed: %s",
                        api_runtime.last_error or "unknown error",
                    )
                elif api_recovered:
                    log.info("Plex API collector recovered")

                if mqtt.connected.is_set():
                    mqtt.set_plex_api_available(
                        api_runtime.status == "ok",
                        force=(
                            republish
                            or api_recovered
                            or api_failure_transition
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

            if state_snapshot is not None and mqtt.connected.is_set():
                force_publish = (
                    refresh
                    or republish
                    or recovered
                    or process_failure_transition
                    or api_changed
                )
                decision = policy.evaluate(
                    state_snapshot,
                    time.monotonic(),
                    force=force_publish,
                )
                if decision.publish:
                    payload = build_state_payload(state_snapshot, build)
                    payload.update(api_runtime.payload())
                    if mqtt.publish_state(payload):
                        policy.mark_published(
                            state_snapshot,
                            time.monotonic(),
                        )
                        reasons = list(decision.reasons)
                        if refresh:
                            reasons.append("manual_refresh")
                        if republish:
                            reasons.append("republish")
                        if recovered:
                            reasons.append("collector_recovery")
                        if process_failure_transition:
                            reasons.append("collector_failure")
                        if api_changed:
                            reasons.append("plex_api_change")
                        if api_recovered:
                            reasons.append("plex_api_recovery")
                        if api_failure_transition:
                            reasons.append("plex_api_failure")
                        log.info(
                            "Published Plex state (%s)",
                            ",".join(dict.fromkeys(reasons)),
                        )

    finally:
        mqtt.stop()
        log.info("DigitalHouses Plex Monitoring stopped")

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
