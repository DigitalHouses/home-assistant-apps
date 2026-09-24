"""Minimal Home Assistant Core API client for recovery actions."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class HomeAssistantApiError(RuntimeError):
    """Raised when a Home Assistant service call fails."""


class HomeAssistantApi:
    def __init__(
        self,
        token: str | None = None,
        base_url: str = "http://supervisor/core/api",
        timeout_seconds: int = 15,
    ) -> None:
        self.token = token or os.getenv("SUPERVISOR_TOKEN", "")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_state(self, entity_id: str) -> dict:
        if not self.token:
            raise HomeAssistantApiError("SUPERVISOR_TOKEN is not available")
        request = urllib.request.Request(
            f"{self.base_url}/states/{entity_id}",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                if response.status < 200 or response.status >= 300:
                    raise HomeAssistantApiError(
                        f"Home Assistant returned HTTP {response.status}"
                    )
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            raise HomeAssistantApiError(
                f"Home Assistant state read failed: HTTP {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            raise HomeAssistantApiError(
                f"Home Assistant state read failed: {exc.reason}"
            ) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise HomeAssistantApiError(
                "Home Assistant state read returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise HomeAssistantApiError(
                "Home Assistant state read returned invalid payload"
            )
        return payload

    def call_service(self, domain: str, service: str, entity_id: str) -> None:
        if not self.token:
            raise HomeAssistantApiError("SUPERVISOR_TOKEN is not available")

        payload = json.dumps({"entity_id": entity_id}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/services/{domain}/{service}",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                if response.status < 200 or response.status >= 300:
                    raise HomeAssistantApiError(
                        f"Home Assistant returned HTTP {response.status}"
                    )
        except urllib.error.HTTPError as exc:
            raise HomeAssistantApiError(
                f"Home Assistant service call failed: HTTP {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            raise HomeAssistantApiError(
                f"Home Assistant service call failed: {exc.reason}"
            ) from exc
