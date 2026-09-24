"""ICMP connectivity probes used by DigitalHouses Internet App."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

GOOGLE_PROBE = "8.8.8.8"
CLOUDFLARE_PROBE = "1.1.1.1"


@dataclass(frozen=True)
class ConnectivitySnapshot:
    internet_up: bool
    router_up: bool
    google_up: bool = False
    cloudflare_up: bool = False


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


def sample(router_ip: str, timeout_seconds: int) -> ConnectivitySnapshot:
    google_up = ping_host(GOOGLE_PROBE, timeout_seconds)
    cloudflare_up = ping_host(CLOUDFLARE_PROBE, timeout_seconds)
    return ConnectivitySnapshot(
        internet_up=google_up or cloudflare_up,
        router_up=ping_host(router_ip, timeout_seconds),
        google_up=google_up,
        cloudflare_up=cloudflare_up,
    )
