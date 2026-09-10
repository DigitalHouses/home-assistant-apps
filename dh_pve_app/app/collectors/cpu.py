from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models import CpuFrequencySnapshot, CpuTopology, ThrottleCounters


@dataclass(frozen=True)
class CpuTimes:
    total: int
    idle: int


def parse_cpu_stat_line(line: str) -> CpuTimes:
    parts = line.split()
    if not parts or parts[0] != "cpu":
        raise ValueError("expected aggregate cpu line")
    values = [int(item) for item in parts[1:]]
    if len(values) < 4:
        raise ValueError("aggregate cpu line is incomplete")
    values += [0] * (8 - len(values))
    user, nice, system, idle, iowait, irq, softirq, steal = values[:8]
    return CpuTimes(
        total=user + nice + system + idle + iowait + irq + softirq + steal,
        idle=idle + iowait,
    )


def read_cpu_times(path: Path = Path("/proc/stat")) -> CpuTimes:
    with path.open("r", encoding="utf-8") as handle:
        return parse_cpu_stat_line(handle.readline())


def cpu_usage_percent(previous: CpuTimes, current: CpuTimes) -> float | None:
    total = current.total - previous.total
    idle = current.idle - previous.idle
    if total <= 0:
        return None
    return round(max(0.0, min(100.0, (total - idle) * 100.0 / total)), 1)


def _lscpu_fields(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key and key not in result:
            result[key] = value.strip()
    return result


def _to_int(fields: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(fields.get(key, str(default)).split()[0])
    except (ValueError, IndexError):
        return default


def _to_float(fields: dict[str, str], key: str) -> float | None:
    try:
        return float(fields[key].split()[0])
    except (KeyError, ValueError, IndexError):
        return None


def parse_lscpu(text: str) -> CpuTopology:
    fields = _lscpu_fields(text)
    threads = _to_int(fields, "CPU(s)")
    threads_per_core = max(1, _to_int(fields, "Thread(s) per core", 1))
    cores_per_socket = _to_int(fields, "Core(s) per socket")
    sockets = max(1, _to_int(fields, "Socket(s)", 1))
    cores = cores_per_socket * sockets if cores_per_socket else (
        threads // threads_per_core if threads else 0
    )
    return CpuTopology(
        model=fields.get("Model name") or None,
        cores=cores,
        threads=threads,
        sockets=sockets,
        threads_per_core=threads_per_core,
        min_mhz=_to_float(fields, "CPU min MHz"),
        max_mhz=_to_float(fields, "CPU max MHz"),
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def read_cpu_temperature(sys_root: Path = Path("/sys")) -> float | None:
    for hwmon in sorted((sys_root / "class" / "hwmon").glob("hwmon*")):
        if _read_text(hwmon / "name") != "coretemp":
            continue
        for input_path in sorted(hwmon.glob("temp*_input")):
            label_path = input_path.with_name(input_path.name.replace("_input", "_label"))
            if _read_text(label_path) != "Package id 0":
                continue
            raw = _read_int(input_path)
            if raw is not None:
                return round(raw / 1000.0, 1)
    for zone in sorted((sys_root / "class" / "thermal").glob("thermal_zone*")):
        if _read_text(zone / "type") != "x86_pkg_temp":
            continue
        raw = _read_int(zone / "temp")
        if raw is not None:
            return round(raw / 1000.0, 1)
    return None


def _mhz(khz: int | None) -> float | None:
    return None if khz is None else round(khz / 1000.0, 1)


def _one_or_mixed(values: list[str | None]) -> str | None:
    unique = sorted({value for value in values if value})
    if not unique:
        return None
    return unique[0] if len(unique) == 1 else "mixed"


def read_cpu_frequency(sys_root: Path = Path("/sys")) -> CpuFrequencySnapshot:
    rows: list[dict[str, object]] = []
    base = sys_root / "devices" / "system" / "cpu" / "cpufreq"
    for policy in sorted(base.glob("policy*")):
        if not policy.is_dir():
            continue
        current = _read_int(policy / "cpuinfo_cur_freq")
        source = "cpuinfo_cur_freq"
        if current is None:
            current = _read_int(policy / "scaling_cur_freq")
            source = "scaling_cur_freq"
        if current is None:
            continue
        rows.append({
            "current": current,
            "source": source,
            "driver": _read_text(policy / "scaling_driver"),
            "governor": _read_text(policy / "scaling_governor"),
            "hardware_min": _read_int(policy / "cpuinfo_min_freq"),
            "hardware_max": _read_int(policy / "cpuinfo_max_freq"),
            "scaling_min": _read_int(policy / "scaling_min_freq"),
            "scaling_max": _read_int(policy / "scaling_max_freq"),
        })
    if not rows:
        return CpuFrequencySnapshot(False, None, None, None, None, None, None, None, None, None, None, 0)

    currents = [int(row["current"]) for row in rows]
    def extrema(name: str, pick) -> int | None:
        values = [int(row[name]) for row in rows if row[name] is not None]
        return pick(values) if values else None

    return CpuFrequencySnapshot(
        available=True,
        average_mhz=round(sum(currents) / len(currents) / 1000.0, 1),
        minimum_current_mhz=_mhz(min(currents)),
        maximum_current_mhz=_mhz(max(currents)),
        hardware_minimum_mhz=_mhz(extrema("hardware_min", min)),
        hardware_maximum_mhz=_mhz(extrema("hardware_max", max)),
        scaling_minimum_mhz=_mhz(extrema("scaling_min", min)),
        scaling_maximum_mhz=_mhz(extrema("scaling_max", max)),
        source=_one_or_mixed([str(row["source"]) for row in rows]),
        scaling_driver=_one_or_mixed([row["driver"] if isinstance(row["driver"], str) else None for row in rows]),
        scaling_governor=_one_or_mixed([row["governor"] if isinstance(row["governor"], str) else None for row in rows]),
        policy_count=len(rows),
    )


def read_throttle_counters(sys_root: Path = Path("/sys")) -> ThrottleCounters:
    rows: list[tuple[int | None, int | None, int | None, int | None]] = []
    base = sys_root / "devices" / "system" / "cpu"
    for directory in sorted(base.glob("cpu[0-9]*/thermal_throttle")):
        if not directory.is_dir():
            continue
        rows.append((
            _read_int(directory / "package_throttle_count"),
            _read_int(directory / "package_throttle_total_time_ms"),
            _read_int(directory / "core_throttle_count"),
            _read_int(directory / "core_throttle_total_time_ms"),
        ))
    def maximum(index: int) -> int | None:
        values = [row[index] for row in rows if row[index] is not None]
        return max(values) if values else None
    package_count, package_time = maximum(0), maximum(1)
    core_count, core_time = maximum(2), maximum(3)
    if package_count is not None and package_time is not None:
        source, count, total_time = "package", package_count, package_time
    elif core_count is not None and core_time is not None:
        source, count, total_time = "core_max", core_count, core_time
    else:
        source, count, total_time = None, None, None
    return ThrottleCounters(
        available=source is not None,
        counter_source=source,
        count_since_boot=count,
        time_since_boot_ms=total_time,
        package_count_since_boot=package_count,
        package_time_since_boot_ms=package_time,
        core_count_max_since_boot=core_count,
        core_time_max_since_boot_ms=core_time,
        cpu_entry_count=len(rows),
    )


def thermal_throttling_active(
    previous: ThrottleCounters | None,
    current: ThrottleCounters,
    *,
    min_time_delta_ms: int = 100,
) -> bool:
    if previous is None or not previous.available or not current.available:
        return False
    if previous.count_since_boot is None or current.count_since_boot is None:
        return False
    if previous.time_since_boot_ms is None or current.time_since_boot_ms is None:
        return False
    count_delta = current.count_since_boot - previous.count_since_boot
    time_delta = current.time_since_boot_ms - previous.time_since_boot_ms
    if count_delta < 0 or time_delta < 0:
        return False
    return count_delta > 0 and time_delta >= min_time_delta_ms
