from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path


DEFAULT_POLICY_HELPER = Path("/opt/digitalhouses/digitalhouses_pve_agent/bin/digitalhouses-pve-agent-ups-policy-cmd")
_ALLOWED_REASONS = frozenset({"charge_guard", "runtime_guard"})


class SoftwareShutdownExecutionError(RuntimeError):
    """Raised when the fixed local UPS shutdown helper cannot commit FSD."""


def execute_fixed_ups_shutdown(
    reason: str,
    *,
    helper_path: Path = DEFAULT_POLICY_HELPER,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout_seconds: float = 5.0,
) -> None:
    if reason not in _ALLOWED_REASONS:
        raise SoftwareShutdownExecutionError("unsupported software shutdown reason")
    try:
        completed = runner(
            [str(helper_path), "dh-pve-ups-shutdown"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SoftwareShutdownExecutionError("UPS shutdown helper failed") from exc
    if completed.returncode != 0:
        raise SoftwareShutdownExecutionError("UPS shutdown helper failed")
