"""Ookla Speedtest runner and persisted last-success state."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from state import atomic_write_json, iso, now_local


def default_speedtest_state() -> dict[str, Any]:
    return {
        "status": "ready",
        "download_mbps": None,
        "upload_mbps": None,
        "ping_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": None,
        "provider": "",
        "external_ip": "",
        "server": "",
        "result_url": "",
        "tested_at": None,
        "error": None,
    }


def load_last_result(path: Path) -> dict[str, Any]:
    state = default_speedtest_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return state
    if not isinstance(raw, dict):
        return state
    for key in state:
        if key in raw:
            state[key] = raw[key]
    if state["tested_at"]:
        state["status"] = "success"
        state["error"] = None
    return state


def save_last_result(path: Path, state: dict[str, Any]) -> None:
    atomic_write_json(path, state)


def parse_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("type") != "result":
        raise RuntimeError("Ookla Speedtest did not return a result object")

    download = payload.get("download")
    upload = payload.get("upload")
    ping = payload.get("ping")
    if not isinstance(download, dict) or download.get("bandwidth") is None:
        raise RuntimeError("Ookla result is missing download.bandwidth")
    if not isinstance(upload, dict) or upload.get("bandwidth") is None:
        raise RuntimeError("Ookla result is missing upload.bandwidth")
    if not isinstance(ping, dict) or ping.get("latency") is None:
        raise RuntimeError("Ookla result is missing ping.latency")

    interface = payload.get("interface")
    if not isinstance(interface, dict):
        interface = {}
    server = payload.get("server")
    if not isinstance(server, dict):
        server = {}
    result = payload.get("result")
    if not isinstance(result, dict):
        result = {}

    packet_loss = payload.get("packetLoss")
    return {
        "status": "success",
        "download_mbps": round(float(download["bandwidth"]) * 8 / 1_000_000, 2),
        "upload_mbps": round(float(upload["bandwidth"]) * 8 / 1_000_000, 2),
        "ping_ms": round(float(ping["latency"]), 2),
        "jitter_ms": (
            round(float(ping["jitter"]), 2)
            if ping.get("jitter") is not None
            else None
        ),
        "packet_loss_pct": (
            round(float(packet_loss), 2) if packet_loss is not None else None
        ),
        "provider": str(payload.get("isp") or ""),
        "external_ip": str(interface.get("externalIp") or ""),
        "server": str(server.get("name") or ""),
        "result_url": str(result.get("url") or ""),
        "tested_at": iso(now_local()),
        "error": None,
    }


def run_speedtest(timeout_seconds: int) -> dict[str, Any]:
    args = [
        "speedtest",
        "--accept-license",
        "--accept-gdpr",
        "--format=json",
        "--progress=no",
    ]
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Ookla Speedtest timed out after {timeout_seconds} seconds"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to start Ookla Speedtest: {exc}") from exc

    if completed.returncode != 0:
        message = " ".join(completed.stderr.split())[-900:]
        raise RuntimeError(
            message or f"Ookla Speedtest exited with code {completed.returncode}"
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ookla Speedtest returned invalid JSON") from exc
    return parse_result(payload)
