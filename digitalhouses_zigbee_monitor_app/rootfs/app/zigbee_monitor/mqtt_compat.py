"""Compatibility helpers for Alpine py3-paho-mqtt (1.x) and paho-mqtt 2.x.

The HAOS image uses Alpine's packaged paho, while CI may install newer paho
from PyPI. Callback signatures also differ; do not rely on the CI version.
"""
from __future__ import annotations

from typing import Any


def create_mqtt_client(mqtt_module: Any, *, client_id: str) -> Any:
    """Select the callback protocol actually supported by the installed paho."""
    callback_api = getattr(mqtt_module, "CallbackAPIVersion", None)
    if callback_api is not None:
        return mqtt_module.Client(callback_api.VERSION2, client_id=client_id)
    return mqtt_module.Client(client_id=client_id)


def connection_failed(reason_code: Any) -> bool:
    """Handle MQTT v1 integer return codes and MQTT v2 ReasonCode instances."""
    is_failure = getattr(reason_code, "is_failure", None)
    if is_failure is not None:
        return bool(is_failure)
    return reason_code != 0
