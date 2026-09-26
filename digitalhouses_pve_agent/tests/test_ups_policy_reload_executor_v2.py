import subprocess

import pytest

from app.ups_policy_reload import (
    FixedServiceReloadExecutor,
    ServiceReloadError,
)


class Runner:
    def __init__(self, *, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        return subprocess.CompletedProcess(
            argv,
            self.returncode,
            stdout="",
            stderr=self.stderr,
        )


def test_fixed_reload_executor_uses_only_dh_pve_service_reload_without_shell():
    runner = Runner()
    executor = FixedServiceReloadExecutor(runner=runner, timeout_seconds=4.0)

    executor()

    assert len(runner.calls) == 1
    argv, kwargs = runner.calls[0]
    assert argv == ["systemctl", "reload", "digitalhouses_pve_agent.service"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 4.0
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True


def test_fixed_reload_executor_fails_closed_on_nonzero_return_code():
    runner = Runner(returncode=1, stderr="reload failed")
    executor = FixedServiceReloadExecutor(runner=runner)

    with pytest.raises(ServiceReloadError, match="reload failed"):
        executor()
