from pathlib import Path

from app.ups_policy_apply import ManagedNutPaths


def test_policy_helper_lives_in_read_only_app_code():
    paths = ManagedNutPaths()

    assert paths.command_script == Path(
        "/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"
    )
    assert str(paths.command_script).startswith("/opt/digitalhouses/dh_pve_app/")


def test_systemd_keeps_protectsystem_and_opens_only_nut_config_for_policy_write():
    unit = Path("dh_pve_app/systemd/dh_pve_app.service").read_text(encoding="utf-8")

    assert "ProtectSystem=full" in unit
    assert "ReadWritePaths=/etc/nut" in unit
    assert "ReadWritePaths=/opt" not in unit
    assert "ReadWritePaths=/usr" not in unit
    assert "ReadWritePaths=/usr/local" not in unit
