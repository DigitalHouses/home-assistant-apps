from pathlib import Path


DASHBOARD = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "lovelace"
    / "plex-dashboard.yaml"
).read_text(encoding="utf-8")


def test_dashboard_shows_agent_version_and_uptime():
    assert "sensor.dh_plex_agent_version" in DASHBOARD
    assert "sensor.dh_plex_agent_uptime" in DASHBOARD


def test_dashboard_does_not_show_commit_build_sensor():
    assert "sensor.dh_plex_build" not in DASHBOARD
