from __future__ import annotations

import subprocess
from collections.abc import Callable


class ServiceReloadError(RuntimeError):
    pass


class FixedServiceReloadExecutor:
    """Reload only dh_pve_app.service through a fixed, non-shell command."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.runner = runner
        self.timeout_seconds = float(timeout_seconds)

    def __call__(self) -> None:
        completed = self.runner(
            ["systemctl", "reload", "dh_pve_app.service"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode == 0:
            return
        detail = (completed.stderr or completed.stdout or "service reload failed").strip()
        raise ServiceReloadError(detail)
