from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from .config import UpsConfig
from .pve_cache import read_pve_rrd
from .ups_policy import GuestShutdownTask, calculate_guest_shutdown_budget
from .ups_shutdown_budget import (
    ShutdownBudgetInputs,
    ShutdownBudgetResult,
    calculate_shutdown_budget,
)


DEFAULT_QEMU_DIR = Path("/etc/pve/qemu-server")
DEFAULT_LXC_DIR = Path("/etc/pve/lxc")
DEFAULT_DATACENTER_PATH = Path("/etc/pve/datacenter.cfg")
DEFAULT_RRD_PATH = Path("/etc/pve/.rrd")
DEFAULT_UPSMON_PATH = Path("/etc/nut/upsmon.conf")
DEFAULT_HOST_TAIL_FALLBACK_SECONDS = 90
DEFAULT_GUEST_TIMEOUT_SECONDS = 180


def _unavailable(reason: str) -> ShutdownBudgetResult:
    return replace(
        calculate_shutdown_budget(
            ShutdownBudgetInputs(
                configured_guest_budget_seconds=None,
                observed_guest_budget_seconds=None,
                hostsync_seconds=None,
                hostsync_applicable=None,
                finaldelay_seconds=None,
                observed_host_tail_seconds=None,
                host_tail_fallback_seconds=DEFAULT_HOST_TAIL_FALLBACK_SECONDS,
            )
        ),
        unavailable_reason=reason,
    )


def _read_simple_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values


def _startup_values(config: Mapping[str, str]) -> tuple[int | None, int]:
    order: int | None = None
    timeout = DEFAULT_GUEST_TIMEOUT_SECONDS
    raw = config.get("startup", "")
    for item in raw.split(","):
        key, separator, value = item.strip().partition("=")
        if not separator:
            continue
        try:
            parsed = int(value.strip())
        except ValueError:
            continue
        key = key.strip()
        if key == "order":
            order = parsed
        elif key == "down" and parsed >= 0:
            timeout = parsed
    return order, timeout


def _max_workers(path: Path) -> int:
    try:
        values = _read_simple_config(path)
        configured = int(values.get("max_workers", ""))
        if configured >= 1:
            return configured
    except (OSError, ValueError):
        pass
    return max(1, os.cpu_count() or 1)


def _running_tasks(
    *,
    qemu_dir: Path,
    lxc_dir: Path,
    rrd_path: Path,
    node_name: str,
    now_epoch: float,
) -> list[tuple[str, GuestShutdownTask]] | None:
    try:
        snapshot = read_pve_rrd(
            rrd_path,
            node_name=node_name,
            now_epoch=now_epoch,
        )
    except (OSError, ValueError):
        return None
    if snapshot.node is None:
        return None

    tasks: list[tuple[str, GuestShutdownTask]] = []
    for vmid, runtime in sorted(snapshot.guests.items(), key=lambda item: int(item[0])):
        if runtime.status != "running" or runtime.template is True:
            continue
        config_path: Path | None = None
        kind: str | None = None
        qemu_path = qemu_dir / f"{vmid}.conf"
        lxc_path = lxc_dir / f"{vmid}.conf"
        if qemu_path.is_file():
            config_path = qemu_path
            kind = "vm"
        elif lxc_path.is_file():
            config_path = lxc_path
            kind = "lxc"
        if config_path is None or kind is None:
            return None
        try:
            config = _read_simple_config(config_path)
        except OSError:
            return None
        if config.get("template", "0").strip().casefold() in {"1", "true", "yes", "on"}:
            continue
        order, timeout = _startup_values(config)
        tasks.append(
            (
                kind,
                GuestShutdownTask(
                    vmid=int(vmid),
                    order=order,
                    timeout_seconds=timeout,
                ),
            )
        )
    return tasks


def _configured_tasks(
    *,
    qemu_dir: Path,
    lxc_dir: Path,
) -> list[tuple[str, GuestShutdownTask]] | None:
    tasks: list[tuple[str, GuestShutdownTask]] = []
    for kind, directory in (("vm", qemu_dir), ("lxc", lxc_dir)):
        try:
            paths = sorted(
                directory.glob("*.conf"),
                key=lambda path: (
                    (0, int(path.stem))
                    if path.stem.isdigit()
                    else (1, path.stem)
                ),
            )
        except OSError:
            return None
        for path in paths:
            if not path.stem.isdigit():
                continue
            try:
                config = _read_simple_config(path)
            except OSError:
                return None
            if config.get("template", "0").strip().casefold() in {"1", "true", "yes", "on"}:
                continue
            order, timeout = _startup_values(config)
            tasks.append(
                (
                    kind,
                    GuestShutdownTask(
                        vmid=int(path.stem),
                        order=order,
                        timeout_seconds=timeout,
                    ),
                )
            )
    return tasks


def _order_key(order: int | None) -> tuple[int, int]:
    if order is None:
        return (1, 0)
    return (0, order)


def _ordered_task_groups(
    tasks: Sequence[tuple[str, GuestShutdownTask]],
) -> tuple[tuple[tuple[str, GuestShutdownTask], ...], ...]:
    grouped: dict[int | None, list[tuple[str, GuestShutdownTask]]] = {}
    for item in tasks:
        grouped.setdefault(item[1].order, []).append(item)
    return tuple(
        tuple(sorted(grouped[order], key=lambda item: item[1].vmid))
        for order in sorted(grouped, key=_order_key, reverse=True)
    )


def _shutdown_sequence(
    tasks: Sequence[tuple[str, GuestShutdownTask]],
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(str(task.vmid) for _kind, task in group)
        for group in _ordered_task_groups(tasks)
    )


def _running_guest_ids(
    tasks: Sequence[tuple[str, GuestShutdownTask]],
) -> tuple[str, ...]:
    return tuple(
        f"{kind}:{task.vmid}"
        for group in _ordered_task_groups(tasks)
        for kind, task in group
    )


def _upsmon_timing(path: Path) -> tuple[int | None, int | None]:
    hostsync: int | None = None
    finaldelay: int | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^(HOSTSYNC|FINALDELAY)\s+(\d+)\s*$", line, re.IGNORECASE)
        if match is None:
            continue
        value = int(match.group(2))
        if match.group(1).upper() == "HOSTSYNC":
            hostsync = value
        else:
            finaldelay = value
    return hostsync, finaldelay


def _client_is_remote(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    host = text
    if text.startswith("[") and "]" in text:
        host = text[1 : text.index("]")]
    elif text.count(":") == 1 and text.rsplit(":", 1)[1].isdigit():
        host = text.rsplit(":", 1)[0]
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.casefold() not in {"localhost", "ip6-localhost"}


def _hostsync_applicable(
    config: UpsConfig,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> bool | None:
    target = f"{config.name}@{config.host}:{config.port}"
    try:
        completed = runner(
            ["upsc", "-c", target],
            capture_output=True,
            text=True,
            timeout=config.command_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return any(_client_is_remote(line) for line in (completed.stdout or "").splitlines())


def _fingerprint(
    *,
    node_name: str,
    tasks: Sequence[tuple[str, GuestShutdownTask]],
    max_workers: int,
    hostsync_seconds: int | None,
    hostsync_applicable: bool,
    finaldelay_seconds: int | None,
) -> str:
    payload = {
        "node": node_name,
        "max_workers": max_workers,
        "hostsync_seconds": hostsync_seconds,
        "hostsync_applicable": hostsync_applicable,
        "finaldelay_seconds": finaldelay_seconds,
        "guests": [
            {
                "kind": kind,
                "vmid": task.vmid,
                "order": task.order,
                "timeout_seconds": task.timeout_seconds,
            }
            for kind, task in tasks
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _history_evidence(
    history: Sequence[Mapping[str, object]],
    *,
    fingerprint: str,
) -> tuple[int | None, int | None, str]:
    guest_values: list[int] = []
    tail_values: list[int] = []
    for record in history:
        if record.get("shutdown_clean") is not True:
            continue
        if record.get("shutdown_budget_fingerprint") != fingerprint:
            continue
        guest = record.get("guest_shutdown_total_seconds")
        tail = record.get("all_guests_stopped_to_shutdown_seconds")
        if isinstance(guest, int) and not isinstance(guest, bool) and guest >= 0:
            guest_values.append(guest)
        if isinstance(tail, int) and not isinstance(tail, bool) and tail >= 0:
            tail_values.append(tail)
    if not guest_values and not tail_values:
        return None, None, "none"
    return (
        max(guest_values) if guest_values else None,
        max(tail_values) if tail_values else None,
        "comparable_clean",
    )


def read_shutdown_budget(
    config: UpsConfig,
    *,
    node_name: str,
    history: Sequence[Mapping[str, object]],
    qemu_dir: Path = DEFAULT_QEMU_DIR,
    lxc_dir: Path = DEFAULT_LXC_DIR,
    datacenter_path: Path = DEFAULT_DATACENTER_PATH,
    rrd_path: Path = DEFAULT_RRD_PATH,
    upsmon_path: Path = DEFAULT_UPSMON_PATH,
    now_epoch: Callable[[], float] = time.time,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ShutdownBudgetResult:
    tasks = _running_tasks(
        qemu_dir=qemu_dir,
        lxc_dir=lxc_dir,
        rrd_path=rrd_path,
        node_name=node_name,
        now_epoch=now_epoch(),
    )
    if tasks is None:
        return _unavailable("pve_runtime_cache_unavailable")

    workers = _max_workers(datacenter_path)
    configured_guest_budget = calculate_guest_shutdown_budget(
        [task for _kind, task in tasks],
        max_workers=workers,
    )
    all_tasks = _configured_tasks(
        qemu_dir=qemu_dir,
        lxc_dir=lxc_dir,
    )
    all_configured_guest_budget = (
        calculate_guest_shutdown_budget(
            [task for _kind, task in all_tasks],
            max_workers=workers,
        )
        if all_tasks is not None
        else None
    )
    hostsync_seconds, finaldelay_seconds = _upsmon_timing(upsmon_path)
    hostsync_applicable = _hostsync_applicable(config, runner=runner)
    if hostsync_applicable is None:
        return _unavailable("hostsync_applicability_unavailable")

    fingerprint = _fingerprint(
        node_name=node_name,
        tasks=tasks,
        max_workers=workers,
        hostsync_seconds=hostsync_seconds,
        hostsync_applicable=hostsync_applicable,
        finaldelay_seconds=finaldelay_seconds,
    )
    observed_guest, observed_tail, evidence_status = _history_evidence(
        history,
        fingerprint=fingerprint,
    )
    result = calculate_shutdown_budget(
        ShutdownBudgetInputs(
            configured_guest_budget_seconds=configured_guest_budget,
            observed_guest_budget_seconds=observed_guest,
            hostsync_seconds=hostsync_seconds,
            hostsync_applicable=hostsync_applicable,
            finaldelay_seconds=finaldelay_seconds,
            observed_host_tail_seconds=observed_tail,
            host_tail_fallback_seconds=DEFAULT_HOST_TAIL_FALLBACK_SECONDS,
        )
    )
    return replace(
        result,
        configuration_fingerprint=fingerprint,
        history_evidence_status=evidence_status,
        all_configured_guest_budget_seconds=all_configured_guest_budget,
        running_guests=_running_guest_ids(tasks),
        shutdown_sequence=_shutdown_sequence(tasks),
    )
