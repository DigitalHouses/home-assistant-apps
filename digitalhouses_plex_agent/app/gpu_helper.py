from __future__ import annotations

import argparse
import logging
from pathlib import Path
import signal
import threading
import time

from .gpu_collector import (
    DEFAULT_GPU_STATE_FILE,
    IntelGpuCollector,
    write_gpu_state_atomic,
)


LOGGER = logging.getLogger("digitalhouses_plex_agent_gpu_helper")


def run(
    *,
    state_file: Path,
    interval_seconds: float,
) -> int:
    collector = IntelGpuCollector()
    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        LOGGER.info("GPU helper stop requested by signal %s", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    LOGGER.info(
        "Starting Plex GPU helper | interval=%.1fs state=%s",
        interval_seconds,
        state_file,
    )

    next_sample = time.monotonic()

    while not stop_event.is_set():
        wait_seconds = max(0.0, next_sample - time.monotonic())
        if stop_event.wait(wait_seconds):
            break

        started_at = time.monotonic()
        payload = collector.collect()
        try:
            write_gpu_state_atomic(state_file, payload)
        except OSError as exc:
            LOGGER.warning("Unable to publish GPU helper state: %s", exc)

        next_sample += interval_seconds
        if next_sample <= started_at:
            next_sample = started_at + interval_seconds

    LOGGER.info("Plex GPU helper stopped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_GPU_STATE_FILE,
    )
    parser.add_argument("--interval", type=float, default=10.0)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    return run(
        state_file=args.state_file,
        interval_seconds=max(1.0, float(args.interval)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
