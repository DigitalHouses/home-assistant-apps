from pathlib import Path

from app.ups_shutdown_executor import DEFAULT_POLICY_HELPER


def test_policy_helper_lives_in_read_only_app_code():
    assert DEFAULT_POLICY_HELPER == Path(
        "/opt/digitalhouses/digitalhouses_pve_agent/bin/digitalhouses-pve-agent-ups-policy-cmd"
    )
    assert str(DEFAULT_POLICY_HELPER).startswith("/opt/digitalhouses/digitalhouses_pve_agent/")


def test_runtime_systemd_keeps_nut_configuration_read_only():
    unit = Path("digitalhouses_pve_agent/systemd/digitalhouses_pve_agent.service").read_text(encoding="utf-8")

    assert "ProtectSystem=full" in unit
    assert "ReadWritePaths=/etc/nut" not in unit
    assert "ReadWritePaths=/opt" not in unit
    assert "ReadWritePaths=/usr" not in unit
    assert "ReadWritePaths=/usr/local" not in unit
