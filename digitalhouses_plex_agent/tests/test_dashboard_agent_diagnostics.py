from pathlib import Path


DASHBOARD = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "lovelace"
    / "plex-dashboard.yaml"
).read_text(encoding="utf-8")


def test_live_dashboard_shows_agent_controls_and_playback():
    assert "path: plex-agent" in DASHBOARD
    assert "sensor.dh_plex_agent_card" in DASHBOARD
    assert "sensor.dh_plex_agent_version" in DASHBOARD
    assert "sensor.dh_plex_agent_uptime" in DASHBOARD
    assert "sensor.dh_plex_agent_playback_started_at" in DASHBOARD
    assert "sensor.dh_plex_agent_api_status" in DASHBOARD
    assert "sensor.dh_plex_agent_collector_status" in DASHBOARD


def test_dashboard_does_not_show_commit_build_sensor():
    assert "sensor.dh_plex_agent_build" not in DASHBOARD
