"""Cheap connectivity probes used by DigitalHouses Internet App."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectivitySnapshot:
    internet_up: bool
    router_up: bool


INTERNET_PROBES: tuple[tuple[str, int], ...] = (
    ("1.1.1.1", 443),
    ("8.8.8.8", 443),
)


def ping_host(host: str, timeout_seconds: int) -> bool:
    try:
        result = subprocess.run(
            [
                "ping",
                "-n",
                "-c",
                "1",
                "-W",
                str(timeout_seconds),
                host,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds + 2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def internet_reachable(timeout_seconds: int) -> bool:
    for host, port in INTERNET_PROBES:
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                return True
        except OSError:
            continue
    return False


def sample(router_ip: str, timeout_seconds: int) -> ConnectivitySnapshot:
    return ConnectivitySnapshot(
        internet_up=internet_reachable(timeout_seconds),
        router_up=ping_host(router_ip, timeout_seconds),
    )
