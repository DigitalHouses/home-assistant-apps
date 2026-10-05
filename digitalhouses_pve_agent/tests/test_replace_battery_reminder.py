from __future__ import annotations

from pathlib import Path

from app.ups_health import ups_problem_observations
from app.ups_nut import parse_upsc_output


APP_ROOT = Path(__file__).resolve().parents[1]
EN_PACKAGE = APP_ROOT / "examples" / "packages" / "dh_pve_agent_notification_local_package.yaml"
RU_PACKAGE = (
    APP_ROOT
    / "examples"
    / "packages"
    / "locales"
    / "ru"
    / "dh_pve_agent_notification_local_package.yaml"
)


def test_replace_battery_is_critical() -> None:
    snapshot = parse_upsc_output("ups.status: OL RB\n")
    observations = {
        item.problem_id: item
        for item in ups_problem_observations(snapshot, nut_available=True)
    }

    assert observations["replace_battery"].active is True
    assert observations["replace_battery"].severity == "critical"


def test_local_packages_repeat_replace_battery_notification_hourly() -> None:
    for path in (EN_PACKAGE, RU_PACKAGE):
        text = path.read_text(encoding="utf-8")

        assert "id: replace_battery_started" in text
        assert "id: replace_battery_cleared" in text
        assert "trigger: time_pattern" in text
        assert 'minutes: "0"' in text
        assert "id: replace_battery_reminder" in text
        assert "binary_sensor.dh_pve_agent_ups_replace_battery_problem" in text
        assert "sensor.dh_pve_agent_ups_battery_charge" in text
        assert "sensor.dh_pve_agent_ups_battery_voltage" in text
        assert text.count("replace_battery_reminder") == 2
