"""Ookla Speedtest runner and persisted last-success state."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from state import ContractDataError, atomic_write_json, iso, load_json_object, now_local


def default_speedtest_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "last_result": None,
        "download_mbps": None,
        "upload_mbps": None,
        "ping_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": None,
        "provider": None,
        "external_ip": None,
        "server": None,
        "server_id": None,
        "result_url": None,
        "tested_at": None,
        "error": None,
    }


def _optional_number(value: Any, *, field: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractDataError(f"{field} must be numeric or null")
    if value < 0:
        raise ContractDataError(f"{field} must not be negative")
    return value


def _optional_string(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractDataError(f"{field} must be a string or null")
    return value or None


def load_last_result(path: Path) -> dict[str, Any]:
    state = default_speedtest_state()
    raw = load_json_object(path, label="speedtest")
    if raw is None:
        return state

    for field in (
        "download_mbps",
        "upload_mbps",
        "ping_ms",
        "jitter_ms",
        "packet_loss_pct",
    ):
        state[field] = _optional_number(
            raw.get(field),
            field=f"speedtest.{field}",
        )

    for field in ("provider", "external_ip", "server", "result_url", "error"):
        state[field] = _optional_string(
            raw.get(field),
            field=f"speedtest.{field}",
        )

    server_id = raw.get("server_id")
    if server_id is not None and (
        isinstance(server_id, bool)
        or not isinstance(server_id, int)
        or server_id <= 0
    ):
        raise ContractDataError(
            "speedtest.server_id must be a positive integer or null"
        )
    state["server_id"] = server_id

    tested_at = raw.get("tested_at")
    if tested_at is not None and (
        not isinstance(tested_at, str) or not tested_at
    ):
        raise ContractDataError(
            "speedtest.tested_at must be a non-empty string or null"
        )
    state["tested_at"] = tested_at

    last_result = raw.get("last_result")
    if last_result is not None and last_result not in {
        "success",
        "error",
        "no_connectivity",
    }:
        raise ContractDataError(
            "speedtest.last_result must be success, error, no_connectivity or null"
        )
    if tested_at and last_result is None:
        # Explicit legacy migration for pre-0.1.6 successful result state.
        last_result = "success"
    state["last_result"] = last_result
    state["status"] = "idle"
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
        "provider": (
            str(payload["isp"]).strip()
            if payload.get("isp") not in (None, "")
            else None
        ),
        "external_ip": (
            str(interface["externalIp"]).strip()
            if interface.get("externalIp") not in (None, "")
            else None
        ),
        "server": (
            " — ".join(
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
            )
            or None
        ),
        "server_id": (
            int(server["id"]) if str(server.get("id") or "").isdigit() else None
        ),
        "result_url": (
            str(result["url"]).strip()
            if result.get("url") not in (None, "")
            else None
        ),
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
    raw = load_json_object(path, label="speedtest servers")
    if raw is None:
        return default_servers_state()

    rows = raw.get("servers")
    if not isinstance(rows, list):
        raise ContractDataError("speedtest servers.servers must be a list")

    validated: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ContractDataError(
                f"speedtest servers.servers[{index}] must be an object"
            )
        server_id = row.get("id")
        if (
            isinstance(server_id, bool)
            or not isinstance(server_id, int)
            or server_id <= 0
        ):
            raise ContractDataError(
                f"speedtest servers.servers[{index}].id must be a positive integer"
            )
        clean = {"id": server_id}
        for field in ("provider", "location", "country"):
            value = row.get(field)
            if not isinstance(value, str):
                raise ContractDataError(
                    f"speedtest servers.servers[{index}].{field} must be a string"
                )
            clean[field] = value
        validated.append(clean)

    updated_at = raw.get("updated_at")
    if updated_at is not None and (
        not isinstance(updated_at, str) or not updated_at
    ):
        raise ContractDataError(
            "speedtest servers.updated_at must be a non-empty string or null"
        )
    error = raw.get("error")
    if error is not None and not isinstance(error, str):
        raise ContractDataError(
            "speedtest servers.error must be a string or null"
        )
    return {
        "count": len(validated),
        "updated_at": updated_at,
        "servers": validated,
        "error": error,
    }

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
