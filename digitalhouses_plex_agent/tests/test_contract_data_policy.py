from pathlib import Path

import pytest

from app.build_info import BuildInfoError, load_build_info
from app.config import load_config
from app.discovery import build_discovery_payload
from app.models import (
    ActivityState,
    BuildInfo,
    CpuGroupMetrics,
    CpuMetrics,
    MonitorSnapshot,
)
from app.presentation_runtime import ContractDataError, PlexPublicationRuntime


class FakeBridge:
    def publish_state_group(self, group, payload):
        return True


def _build() -> BuildInfo:
    return BuildInfo(
        "0.7.0",
        "digitalhouses_plex_agent-v0.7.0",
        "a" * 40,
    )


def _runtime(*, started_at="2026-09-27T00:00:00+00:00"):
    return PlexPublicationRuntime(
        bridge=FakeBridge(),
        build=_build(),
        source_interval_seconds=10.0,
        now_monotonic=lambda: 100.0,
        agent_started_at=started_at,
    )


def _snapshot() -> MonitorSnapshot:
    return MonitorSnapshot(
        collected_at="2026-09-27T00:00:01+00:00",
        activity=ActivityState(
            plex_server_running=True,
            scanner_running=False,
            credits_detection=False,
            intro_detection=False,
            thumbnail_generation=False,
            transcoder_running=False,
            activity="idle",
            scanner_actions=(),
            current_item=None,
        ),
        cpu=CpuMetrics(
            CpuGroupMetrics(0.0, 0.0, 0.0),
            CpuGroupMetrics(0.0, 0.0, 0.0),
            CpuGroupMetrics(0.0, 0.0, 0.0),
        ),
        process_count=1,
        collector_status="ok",
        last_refresh=None,
    )


def test_missing_version_file_is_contract_error(tmp_path: Path):
    with pytest.raises(BuildInfoError, match="missing VERSION"):
        load_build_info(tmp_path)


def test_invalid_version_is_contract_error(tmp_path: Path):
    (tmp_path / "VERSION").write_text("unknown\n", encoding="utf-8")
    with pytest.raises(BuildInfoError, match="invalid semantic VERSION"):
        load_build_info(tmp_path)


def test_missing_started_at_is_contract_error():
    with pytest.raises(ContractDataError, match="agent_started_at"):
        _runtime(started_at=None)


@pytest.mark.parametrize(
    "value",
    [
        "not-a-timestamp",
        "2026-09-27T00:00:00",
        "",
    ],
)
def test_invalid_started_at_is_contract_error(value):
    with pytest.raises(ContractDataError, match="agent_started_at"):
        _runtime(started_at=value)


def test_missing_plex_api_status_is_contract_error():
    runtime = _runtime()
    with pytest.raises(ContractDataError, match="plex_api_status"):
        runtime.publish_snapshot(_snapshot(), {}, force=True)


def test_invalid_plex_api_status_is_contract_error():
    runtime = _runtime()
    with pytest.raises(ContractDataError, match="plex_api_status"):
        runtime.publish_snapshot(
            _snapshot(),
            {"plex_api_status": "unknown"},
            force=True,
        )


def test_required_diagnostics_do_not_use_discovery_fallbacks(tmp_path: Path):
    path = tmp_path / "app.conf"
    path.write_text("[mqtt]\nhost = mqtt.example\n", encoding="utf-8")
    components = build_discovery_payload(
        load_config(path),
        _build(),
    )["components"]

    assert components["agent_version"]["value_template"] == (
        "{{ value_json.agent_version }}"
    )
    assert components["agent_started_at"]["value_template"] == (
        "{{ value_json.agent_started_at }}"
    )
    assert components["agent_uptime"]["value_template"] == (
        "{{ value_json.agent_uptime_seconds }}"
    )
