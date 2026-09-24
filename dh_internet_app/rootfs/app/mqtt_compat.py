"""Compatibility helpers for paho-mqtt 1.x and 2.x."""

from __future__ import annotations

from typing import Any


def create_mqtt_client(mqtt_module: Any, *, client_id: str) -> Any:
    """Create a Client using callback API v2 when the installed paho supports it."""
    callback_api = getattr(mqtt_module, "CallbackAPIVersion", None)
    if callback_api is not None:
        return mqtt_module.Client(
            callback_api.VERSION2,
            client_id=client_id,
        )
    return mqtt_module.Client(client_id=client_id)
