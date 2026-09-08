from __future__ import annotations

from pathlib import Path
from typing import Sequence

import psutil

from .models import ProcessSample, RawProcess


class CollectorError(RuntimeError):
    pass


class ProcVisibilityError(CollectorError):
    pass


def is_plex_process_name(name: str) -> bool:
    return name.strip().casefold().startswith("plex")


def verify_proc_visibility(
    path: Path = Path("/proc/1/cmdline"),
) -> None:
    try:
        path.read_bytes()
    except PermissionError as exc:
        raise ProcVisibilityError(
            "unprivileged agent cannot read process command lines; "
            "check /proc hidepid/process visibility settings"
        ) from exc
    except FileNotFoundError:
        # PID 1 should exist on Linux; treat its absence as a broken namespace.
        raise ProcVisibilityError(f"process visibility probe is missing: {path}")
    except OSError as exc:
        raise ProcVisibilityError(
            f"unable to verify process visibility through {path}: {exc}"
        ) from exc


def collect_raw_processes() -> list[RawProcess]:
    result: list[RawProcess] = []
    try:
        iterator = psutil.process_iter(
            ["pid", "name", "cmdline", "create_time", "cpu_times"]
        )
    except Exception as exc:
        raise CollectorError(f"unable to enumerate processes: {exc}") from exc

    for process in iterator:
        try:
            info = process.info
            name = str(info.get("name") or "")
            if not is_plex_process_name(name):
                continue
            times = info.get("cpu_times")
            if times is None:
                continue
            cmdline = tuple(str(part) for part in (info.get("cmdline") or ()))
            result.append(
                RawProcess(
                    pid=int(info["pid"]),
                    create_time=float(info["create_time"]),
                    name=name,
                    cmdline=cmdline,
                    cpu_time_seconds=float(times.user + times.system),
                )
            )
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied as exc:
            raise CollectorError(
                f"access denied while inspecting Plex process pid={process.pid}"
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise CollectorError(
                f"invalid process metadata for pid={process.pid}: {exc}"
            ) from exc
    return result


class CpuSampler:
    def __init__(self) -> None:
        self._previous: dict[tuple[int, float], tuple[float, float]] = {}

    def sample(
        self,
        processes: Sequence[RawProcess],
        now: float,
    ) -> list[ProcessSample]:
        samples: list[ProcessSample] = []
        new_previous: dict[tuple[int, float], tuple[float, float]] = {}

        for process in processes:
            key = (process.pid, process.create_time)
            previous = self._previous.get(key)
            cpu_percent = 0.0
            if previous is not None:
                previous_time, previous_cpu = previous
                wall_delta = now - previous_time
                cpu_delta = process.cpu_time_seconds - previous_cpu
                if wall_delta > 0 and cpu_delta >= 0:
                    cpu_percent = cpu_delta / wall_delta * 100.0

            samples.append(
                ProcessSample(
                    pid=process.pid,
                    create_time=process.create_time,
                    name=process.name,
                    cmdline=process.cmdline,
                    cpu_percent=max(0.0, cpu_percent),
                )
            )
            new_previous[key] = (now, process.cpu_time_seconds)

        self._previous = new_previous
        return samples
