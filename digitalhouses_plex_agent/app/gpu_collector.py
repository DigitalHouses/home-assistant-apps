from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Callable, Mapping


_PCI_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}[.][0-7]$")
DEFAULT_GPU_STATE_FILE = Path(
    "/var/lib/digitalhouses_plex_agent/gpu_state.json"
)
DEFAULT_GPU_STATE_MAX_AGE_SECONDS = 30.0

_GPU_VALUE_FIELDS = (
    "video_busy_percent",
    "render_busy_percent",
    "video_enhance_busy_percent",
    "frequency_mhz",
    "rc6_percent",
    "temperature_c",
)


def _round_or_none(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 1)
    return None


def parse_intel_gpu_top_json(text: str) -> dict[str, object]:
    raw = text.strip().rstrip(",")
    if not raw:
        raise ValueError("empty intel_gpu_top output")
    try:
        parsed = json.loads(raw)
        samples = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        samples = []
        decoder = json.JSONDecoder()
        position = 0
        while position < len(raw):
            while position < len(raw) and (
                raw[position].isspace() or raw[position] == ","
            ):
                position += 1
            if position >= len(raw):
                break
            try:
                sample, position = decoder.raw_decode(raw, position)
            except json.JSONDecodeError:
                break
            samples.append(sample)
        if not samples:
            raise ValueError("invalid intel_gpu_top JSON stream")

    full = [
        sample
        for sample in samples
        if isinstance(sample, dict)
        and float(sample.get("period", {}).get("duration", 0) or 0) >= 500
    ]
    if not full:
        raise ValueError("no full intel_gpu_top samples")

    def peak(prefix: str) -> float:
        values: list[float] = []
        for sample in full:
            engines = sample.get("engines", {})
            if not isinstance(engines, dict):
                continue
            for name, data in engines.items():
                if not str(name).startswith(prefix) or not isinstance(data, dict):
                    continue
                busy = data.get("busy")
                if isinstance(busy, (int, float)) and not isinstance(busy, bool):
                    values.append(max(0.0, min(100.0, float(busy))))
        return round(max(values, default=0.0), 1)

    last = full[-1]
    frequency = last.get("frequency", {})
    actual_frequency = frequency.get("actual") if isinstance(frequency, dict) else None
    rc6 = last.get("rc6", {})
    rc6_value = rc6.get("value") if isinstance(rc6, dict) else None

    return {
        "supported": True,
        "available": True,
        "status": "ok",
        "source": "intel_gpu_top",
        "video_busy_percent": peak("Video/"),
        "render_busy_percent": peak("Render/3D/"),
        "video_enhance_busy_percent": peak("VideoEnhance/"),
        "frequency_mhz": _round_or_none(actual_frequency),
        "rc6_percent": _round_or_none(rc6_value),
        "sample_count": len(full),
    }


def detect_intel_gpu_pci(sys_root: Path = Path("/sys")) -> str | None:
    drm_root = sys_root / "class" / "drm"
    if not drm_root.exists():
        return None
    for render in sorted(drm_root.glob("renderD*")):
        vendor_path = render / "device" / "vendor"
        try:
            vendor = vendor_path.read_text(encoding="utf-8").strip().lower()
            device = (render / "device").resolve(strict=True)
        except OSError:
            continue
        if vendor != "0x8086":
            continue
        pci = device.name.lower()
        if _PCI_RE.fullmatch(pci):
            return pci
    return None


def read_gpu_temperature(
    pci_address: str,
    *,
    sys_root: Path = Path("/sys"),
) -> float | None:
    pci = pci_address.strip().lower()
    if not _PCI_RE.fullmatch(pci):
        return None
    pci_path = sys_root / "bus" / "pci" / "devices" / pci
    try:
        pci_real = pci_path.resolve(strict=True)
    except OSError:
        return None

    hwmon_root = sys_root / "class" / "hwmon"
    if not hwmon_root.exists():
        return None

    values: list[float] = []
    for hwmon in sorted(hwmon_root.glob("hwmon*")):
        try:
            device_real = (hwmon / "device").resolve(strict=True)
        except OSError:
            continue
        try:
            attached = device_real == pci_real or pci_real in device_real.parents
        except RuntimeError:
            attached = False
        if not attached:
            continue
        for input_path in hwmon.glob("temp*_input"):
            try:
                milli_c = int(input_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            values.append(round(milli_c / 1000.0, 1))
    return max(values) if values else None


def _capture_intel_gpu_top(command: str) -> str:
    process = subprocess.Popen(
        [command, "-J", "-s", "1000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=2.4)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=1.0)
    if not stdout.strip():
        message = stderr.strip() or f"intel_gpu_top exited with rc={process.returncode}"
        raise RuntimeError(message)
    return stdout


class IntelGpuCollector:
    def __init__(
        self,
        *,
        sys_root: Path = Path("/sys"),
        command: str | None = None,
    ) -> None:
        self.sys_root = sys_root
        self.command = command

    @staticmethod
    def _base(
        *,
        supported: bool,
        available: bool,
        status: str,
        pci_address: str | None,
        temperature_c: float | None,
    ) -> dict[str, object]:
        return {
            "supported": supported,
            "available": available,
            "status": status,
            "source": None,
            "pci_address": pci_address,
            "video_busy_percent": None,
            "render_busy_percent": None,
            "video_enhance_busy_percent": None,
            "frequency_mhz": None,
            "rc6_percent": None,
            "temperature_c": temperature_c,
        }

    def collect(self) -> dict[str, object]:
        pci = detect_intel_gpu_pci(self.sys_root)
        if pci is None:
            return self._base(
                supported=False,
                available=False,
                status="unsupported",
                pci_address=None,
                temperature_c=None,
            )

        temperature = read_gpu_temperature(pci, sys_root=self.sys_root)
        command = self.command or shutil.which("intel_gpu_top")
        if not command:
            return self._base(
                supported=True,
                available=False,
                status="tool_missing",
                pci_address=pci,
                temperature_c=temperature,
            )

        try:
            metrics = parse_intel_gpu_top_json(_capture_intel_gpu_top(command))
        except Exception:
            return self._base(
                supported=True,
                available=False,
                status="error",
                pci_address=pci,
                temperature_c=temperature,
            )

        return {
            **metrics,
            "pci_address": pci,
            "temperature_c": temperature,
        }



def write_gpu_state_atomic(
    path: Path,
    payload: Mapping[str, object],
    *,
    now_epoch: Callable[[], float] = time.time,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(payload)
    state["collected_at_epoch"] = float(now_epoch())
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


class GpuStateReader:
    def __init__(
        self,
        path: Path = DEFAULT_GPU_STATE_FILE,
        *,
        max_age_seconds: float = DEFAULT_GPU_STATE_MAX_AGE_SECONDS,
        now_epoch: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.max_age_seconds = float(max_age_seconds)
        self.now_epoch = now_epoch

    @staticmethod
    def _unavailable(
        status: str,
        *,
        supported: bool,
        source: object = None,
        pci_address: object = None,
    ) -> dict[str, object]:
        return {
            "supported": supported,
            "available": False,
            "status": status,
            "source": source,
            "pci_address": pci_address,
            **{field: None for field in _GPU_VALUE_FIELDS},
        }

    def collect(self) -> dict[str, object]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pci = detect_intel_gpu_pci()
            return self._unavailable(
                "helper_unavailable",
                supported=pci is not None,
                pci_address=pci,
            )
        except (OSError, json.JSONDecodeError):
            return self._unavailable("helper_error", supported=True)

        if not isinstance(raw, dict):
            return self._unavailable("helper_error", supported=True)

        supported = bool(raw.get("supported", False))
        source = raw.get("source")
        pci_address = raw.get("pci_address")
        collected_at = raw.get("collected_at_epoch")
        if not isinstance(collected_at, (int, float)) or isinstance(
            collected_at, bool
        ):
            return self._unavailable(
                "helper_error",
                supported=supported,
                source=source,
                pci_address=pci_address,
            )

        age = max(0.0, float(self.now_epoch()) - float(collected_at))
        if age > self.max_age_seconds:
            return self._unavailable(
                "stale",
                supported=supported,
                source=source,
                pci_address=pci_address,
            )

        return {
            "supported": supported,
            "available": bool(raw.get("available", False)),
            "status": str(raw.get("status") or "unknown"),
            "source": source,
            "pci_address": pci_address,
            **{field: raw.get(field) for field in _GPU_VALUE_FIELDS},
        }
