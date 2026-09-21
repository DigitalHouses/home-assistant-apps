from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "examples" / "dh_app_pve_dashboard_ru.yaml"


def test_ru_dashboard_presents_fan_percent_as_primary_metric_with_rpm_fallback():
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "fan.entity_id | replace('_rpm', '_speed')" in text
    assert "speed ~ '%" in text
    assert "~ rpm ~ ' RPM'" in text


def test_ru_dashboard_requires_confirmation_before_manual_fan_calibration():
    text = DASHBOARD.read_text(encoding="utf-8")

    assert "button.dh_app_pve_calibrate_fans" in text
    assert "confirmation:" in text
    assert "максимальную скорость" in text
    assert "автоматическое" in text
    assert "button.press" in text
