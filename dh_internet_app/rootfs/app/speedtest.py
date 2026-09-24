"""Ookla Speedtest runner and persisted last-success state."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from state import atomic_write_json, iso, now_local


def default_speedtest_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "last_result": None,
        "download_mbps": None,
        "upload_mbps": None,
        "ping_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": None,
        "provider": "",
        "external_ip": "",
        "server": "",
        "server_id": None,
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
    state["status"] = "idle"
    if state["tested_at"] and not state["last_result"]:
        state["last_result"] = "success"
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
        "status": "idle",
        "last_result": "success",
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
        "server": " — ".join(
            item
            for item in (
                str(server.get("name") or "").strip(),
                ", ".join(
                    item
                    for item in (
                        str(server.get("location") or "").strip(),
                        str(server.get("country") or "").strip(),
                    )
                    if item
                ),
            )
            if item
        ),
        "server_id": (
            int(server["id"]) if str(server.get("id") or "").isdigit() else None
        ),
        "result_url": str(result.get("url") or ""),
        "tested_at": iso(now_local()),
        "error": None,
    }


def run_speedtest(timeout_seconds: int, server_id: int | None = None) -> dict[str, Any]:
    args = [
        "speedtest",
        "--accept-license",
        "--accept-gdpr",
        "--format=json",
        "--progress=no",
    ]
    if server_id is not None:
        args.append(f"--server-id={server_id}")
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


def default_servers_state() -> dict[str, Any]:
    return {"count": 0, "updated_at": None, "servers": [], "error": None}


def load_servers_state(path: Path) -> dict[str, Any]:
    state = default_servers_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return state
    if not isinstance(raw, dict):
        return state
    rows = raw.get("servers")
    if isinstance(rows, list):
        state["servers"] = [row for row in rows if isinstance(row, dict)]
        state["count"] = len(state["servers"])
    state["updated_at"] = raw.get("updated_at")
    state["error"] = raw.get("error")
    return state


def save_servers_state(path: Path, state: dict[str, Any]) -> None:
    atomic_write_json(path, state)


def parse_server_list(output: str) -> list[dict[str, Any]]:
    servers: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = re.split(r"\s{2,}", line.strip(), maxsplit=3)
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        server_id, provider, location, country = parts
        servers.append(
            {
                "id": int(server_id),
                "provider": provider.strip(),
                "location": location.strip(),
                "country": country.strip(),
            }
        )
    return servers


def list_servers(timeout_seconds: int = 60) -> list[dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["speedtest", "--accept-license", "--accept-gdpr", "--servers"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Ookla server list timed out after {timeout_seconds} seconds"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to start Ookla server list: {exc}") from exc

    if completed.returncode != 0:
        message = " ".join(completed.stderr.split())[-900:]
        raise RuntimeError(
            message or f"Ookla server list exited with code {completed.returncode}"
        )
    servers = parse_server_list(completed.stdout)
    if not servers:
        raise RuntimeError("Ookla server list returned no parseable servers")
    return servers
