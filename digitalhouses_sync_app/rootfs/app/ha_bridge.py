"""Explicit admin-only Home Assistant transport for DH Sync migration development.

No access to Home Assistant occurs at import-time or in the App main loop.
Mutations are reached only through the separately guarded migration CLI.
Storage updates use HA WebSocket API, never direct .storage writes.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from adoption import read_file
from storage_migration import MigrationError


class HAWebSocketBridge:
    """HA 2026.10.x Lovelace WS and config-check REST bridge."""

    def __init__(
        self, *,
        base_url: str,
        admin_token: str,
        home: Path,
        storage_file: str,
        timeout: int = 15,
    ):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise MigrationError("HA API URL must use http(s) with hostname")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise MigrationError("HA API URL must contain only scheme, hostname and port")
        if not admin_token.strip():
            raise MigrationError("HA administrator token is required")
        if not re.fullmatch(r"\.storage/lovelace(?:\.dashboard_[a-zA-Z0-9_.-]+)?", storage_file):
            raise MigrationError("Invalid Storage file path; must be a known Lovelace Storage file")
        self.home = home
        self.storage_file = home / storage_file
        self.base_url = base_url.rstrip("/")
        self.token = admin_token
        self.timeout = timeout
        self.ws_url = parsed._replace(
            scheme="wss" if parsed.scheme == "https" else "ws",
            path="/api/websocket",
            query="",
            fragment="",
        ).geturl()

    def _ws(self, command: dict) -> Any:
        # Packaged as py3-websocket-client in the HAOS container; lazy import
        # allows the migration model tests to run without an HA environment.
        try:
            import websocket
        except ImportError as exc:
            raise MigrationError("HA WebSocket dependency is not installed") from exc
        try:
            sock = websocket.create_connection(
                self.ws_url, timeout=self.timeout, enable_multithread=True
            )
            try:
                challenge = json.loads(sock.recv())
                if challenge.get("type") != "auth_required":
                    raise MigrationError("Unexpected Home Assistant WebSocket authentication handshake")
                sock.send(json.dumps({"type": "auth", "access_token": self.token}))
                accepted = json.loads(sock.recv())
                if accepted.get("type") != "auth_ok":
                    raise MigrationError("Home Assistant administrator authorization was rejected")
                message = {"id": 1, **command}
                sock.send(json.dumps(message, ensure_ascii=False))
                while True:
                    reply = json.loads(sock.recv())
                    if reply.get("id") == 1 and reply.get("type") == "result":
                        if not reply.get("success"):
                            err = reply.get("error") or {}
                            code = err.get("code", "unknown") if isinstance(err, dict) else "unknown"
                            raise MigrationError(f"HA WebSocket command {command['type']} failed: {code}")
                        return reply.get("result")
                    # Ignore unrelated notifications; bounded by socket timeout.
            finally:
                sock.close()
        except (ValueError, OSError, TimeoutError) as exc:
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError("Home Assistant WebSocket request failed") from exc

    def read_storage(self, url_path: str) -> dict:
        result = self._ws({"type": "lovelace/config", "url_path": url_path, "force": True})
        if not isinstance(result, dict):
            raise MigrationError("Home Assistant returned invalid Lovelace config")
        return result

    def save_storage(self, url_path: str, config: dict) -> None:
        self._ws({"type": "lovelace/config/save", "url_path": url_path, "config": config})

    def read_persisted_storage(self, url_path: str) -> dict:
        try:
            snapshot = json.loads(read_file(self.home, self.storage_file))
        except (UnicodeDecodeError, ValueError) as exc:
            raise MigrationError("HA persistent Storage file is unreadable") from exc
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("data"), dict):
            raise MigrationError("Unexpected persistent Lovelace Storage format")
        data = snapshot["data"]
        config = data.get("config")
        if not isinstance(config, dict):
            raise MigrationError("Storage file lacks a config mapping")
        return config

    def read_target_yaml_dashboard(self, url_path: str) -> dict:
        result = self._ws({"type": "lovelace/config", "url_path": url_path, "force": True})
        if not isinstance(result, dict):
            raise MigrationError("Destination dashboard did not return a mapping")
        return result

    def read_plex_agent_version(self) -> str:
        result = self._ws({"type": "get_states"})
        if not isinstance(result, list):
            raise MigrationError("HA get_states returned unexpected data")
        candidates = [
            item.get("state") for item in result
            if isinstance(item, dict)
            and item.get("entity_id") == "sensor.dh_plex_agent_version"
        ]
        if len(candidates) != 1 or not isinstance(candidates[0], str):
            raise MigrationError("Plex Agent Version diagnostic not found")
        version = candidates[0]
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            raise MigrationError("Plex Agent Version sensor has an invalid state")
        return version

    def check_config(self) -> bool:
        request = urllib.request.Request(
            url=self.base_url + "/api/config/core/check_config",
            data=b"{}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise MigrationError("Home Assistant configuration API returned non-200")
                result = json.loads(response.read(1_000_000))
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError("HA configuration validation request failed") from exc
        return isinstance(result, dict) and result.get("result") == "valid"
