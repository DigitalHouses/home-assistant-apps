from pathlib import Path

from app.ups_policy_apply import ManagedNutPaths


def test_policy_helper_lives_in_app_state_not_usr_local():
    paths = ManagedNutPaths()

    assert paths.command_script == Path("/var/lib/dh_pve_app/dh-pve-ups-policy-cmd")
    assert not str(paths.command_script).startswith("/usr/")


def test_systemd_keeps_protectsystem_and_opens_only_nut_config_for_policy_write():
    unit = Path("dh_pve_app/systemd/dh_pve_app.service").read_text(encoding="utf-8")

    assert "ProtectSystem=full" in unit
    assert "ReadWritePaths=/etc/nut" in unit
    assert "ReadWritePaths=/usr" not in unit
    assert "ReadWritePaths=/usr/local" not in unit
