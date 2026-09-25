"""Recovery policy and guarded ONT/router actions."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from config import RecoveryConfig, RecoveryTarget
from ha_api import HomeAssistantApi


class RecoveryStopped(RuntimeError):
    """Raised when the current incident recovery was stopped by the user."""


@dataclass(frozen=True)
class RecoverySelection:
    targets: tuple[str, ...]
    reason: str


def choose_targets(
    *,
    mode: str,
    internet_up: bool,
    router_up: bool,
) -> RecoverySelection:
    if internet_up:
        return RecoverySelection((), "internet_available")
    if mode == "both":
        return RecoverySelection(("ont", "router"), "mode_both")
    if mode != "smart":
        raise ValueError(f"unsupported recovery mode: {mode}")
    if router_up:
        return RecoverySelection(("ont",), "router_available_internet_down")
    return RecoverySelection(("router",), "router_unavailable")


class RecoveryExecutor:
    """Execute only the fixed button/switch recovery action surface."""

    def __init__(
        self,
        api: HomeAssistantApi,
        stop_event: threading.Event,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api = api
        self.stop_event = stop_event
        self.sleep = sleep

    def execute(self, target: RecoveryTarget) -> None:
        if self.stop_event.is_set():
            raise RecoveryStopped("recovery stopped before action")

        if target.action == "button":
            self.api.call_service("button", "press", target.entity_id)
            return

        if target.action != "switch":
            raise ValueError(f"unsupported recovery action: {target.action}")

        try:
            self.api.call_service("switch", "turn_off", target.entity_id)
            remaining = target.power_off_seconds
            while remaining > 0:
                if self.stop_event.is_set():
                    raise RecoveryStopped("recovery stopped while switch was off")
                step = min(1, remaining)
                self.sleep(step)
                remaining -= step
        finally:
            # turn_off may have reached Home Assistant even when its HTTP
            # response fails, so always make a best-effort restore attempt.
            self.api.call_service("switch", "turn_on", target.entity_id)


def target_by_name(config: RecoveryConfig, name: str) -> RecoveryTarget:
    if name == "ont":
        return config.ont
    if name == "router":
        return config.router
    raise ValueError(f"unknown recovery target: {name}")
