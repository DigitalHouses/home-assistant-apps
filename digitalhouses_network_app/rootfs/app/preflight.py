"""Supervisor launcher contract checks for the Go runtime."""
from __future__ import annotations

import os
import re


def validate_environment(env: dict[str, str]) -> None:
    version = env.get("APP_VERSION")
    if not version or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("APP_VERSION must be a semantic version")
    port = env.get("DH_PORT")
    if not port or not port.isdecimal() or not 0 < int(port) < 65536:
        raise ValueError("DH_PORT must be the port assigned by Home Assistant Ingress")
    interval = env.get("DH_INTERVAL")
    if not interval or not interval.isdecimal() or not 15 <= int(interval) <= 3600:
        raise ValueError("DH_INTERVAL must be 15..3600 seconds")
    if not env.get("SUPERVISOR_TOKEN"):
        raise ValueError("SUPERVISOR_TOKEN required for HA Core API")
    if env.get("DH_DB") != "/data/network.sqlite3":
        raise ValueError("DH_DB must point to the persistent App data volume")


if __name__ == "__main__":
    validate_environment(dict(os.environ))
