from pathlib import Path

from app.state_store import StateStore
from app.telemetry import DEFAULT_TELEMETRY_STATE_FILE, TelemetryClient


class FakeTransport:
    def __init__(self, status=204, error=None):
        self.status = status
        self.error = error
        self.calls = []

    def request(self, *, method, path, payload, token, timeout_seconds):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "payload": payload,
                "token": token,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        return self.status


def _released_build(tmp_path: Path, version: str) -> Path:
    path = tmp_path / "BUILD_INFO"
    path.write_text(
        f"version = {version}\n"
        f"source = digitalhouses_pve_agent-v{version}\n"
        "commit = 0123456789abcdef0123456789abcdef01234567\n",
        encoding="utf-8",
    )
    return path


def test_fresh_install_creates_persistent_uuid_and_256_bit_token(tmp_path: Path):
    store = StateStore(tmp_path / "telemetry.json")
    first = TelemetryClient(
        enabled=False,
        version="0.5.8",
        state_store=store,
        build_info_path=tmp_path / "BUILD_INFO",
    )
    second = TelemetryClient(
        enabled=False,
        version="0.5.8",
        state_store=store,
        build_info_path=tmp_path / "BUILD_INFO",
    )

    assert first.installation_id == second.installation_id
    assert first.installation_token == second.installation_token
    assert len(bytes.fromhex(first.installation_token)) >= 32


def test_payload_is_exact_protocol_v1_without_country_or_host_data(tmp_path: Path):
    client = TelemetryClient(
        enabled=False,
        version="0.5.8",
        state_store=StateStore(tmp_path / "telemetry.json"),
        build_info_path=tmp_path / "BUILD_INFO",
    )

    assert client.payload() == {
        "schema": 1,
        "telemetry_policy_version": 1,
        "installation_id": client.installation_id,
        "product": "digitalhouses_pve_agent",
        "version": "0.5.8",
    }


def test_disabled_telemetry_never_calls_transport(tmp_path: Path):
    transport = FakeTransport()
    client = TelemetryClient(
        enabled=False,
        version="0.5.8",
        state_store=StateStore(tmp_path / "telemetry.json"),
        build_info_path=_released_build(tmp_path, "0.5.8"),
        transport=transport,
        now_epoch=lambda: 1000.0,
    )

    assert client.tick() is False
    assert transport.calls == []


def test_unreleased_build_never_calls_production_telemetry(tmp_path: Path):
    build = tmp_path / "BUILD_INFO"
    build.write_text(
        "version = 0.5.8\nsource = main\n"
        "commit = 0123456789abcdef0123456789abcdef01234567\n",
        encoding="utf-8",
    )
    transport = FakeTransport()
    client = TelemetryClient(
        enabled=True,
        version="0.5.8",
        state_store=StateStore(tmp_path / "telemetry.json"),
        build_info_path=build,
        transport=transport,
        now_epoch=lambda: 1000.0,
    )

    assert client.tick() is False
    assert transport.calls == []


def test_enabled_released_build_sends_once_and_restart_does_not_storm(tmp_path: Path):
    now = {"value": 1000.0}
    store = StateStore(tmp_path / "telemetry.json")
    build = _released_build(tmp_path, "0.5.8")
    first_transport = FakeTransport()
    first = TelemetryClient(
        enabled=True,
        version="0.5.8",
        state_store=store,
        build_info_path=build,
        transport=first_transport,
        now_epoch=lambda: now["value"],
    )

    assert first.tick() is True
    assert len(first_transport.calls) == 1
    call = first_transport.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/v1/heartbeat"
    assert call["payload"] == first.payload()
    assert call["token"] == first.installation_token

    restarted_transport = FakeTransport()
    restarted = TelemetryClient(
        enabled=True,
        version="0.5.8",
        state_store=store,
        build_info_path=build,
        transport=restarted_transport,
        now_epoch=lambda: now["value"] + 60.0,
    )
    assert restarted.tick() is False
    assert restarted_transport.calls == []


def test_version_change_allows_one_immediate_best_effort_report(tmp_path: Path):
    now = {"value": 1000.0}
    store = StateStore(tmp_path / "telemetry.json")
    old = TelemetryClient(
        enabled=True,
        version="0.5.8",
        state_store=store,
        build_info_path=_released_build(tmp_path, "0.5.8"),
        transport=FakeTransport(),
        now_epoch=lambda: now["value"],
    )
    assert old.tick() is True

    build = _released_build(tmp_path, "0.5.9")
    transport = FakeTransport()
    upgraded = TelemetryClient(
        enabled=True,
        version="0.5.9",
        state_store=store,
        build_info_path=build,
        transport=transport,
        now_epoch=lambda: now["value"] + 60.0,
    )
    assert upgraded.tick() is True
    assert transport.calls[0]["payload"]["version"] == "0.5.9"


def test_failure_is_isolated_and_backed_off(tmp_path: Path):
    now = {"value": 1000.0}
    transport = FakeTransport(error=OSError("offline"))
    client = TelemetryClient(
        enabled=True,
        version="0.5.8",
        state_store=StateStore(tmp_path / "telemetry.json"),
        build_info_path=_released_build(tmp_path, "0.5.8"),
        transport=transport,
        now_epoch=lambda: now["value"],
    )

    assert client.tick() is False
    assert len(transport.calls) == 1
    now["value"] += 60.0
    assert client.tick() is False
    assert len(transport.calls) == 1


def test_authenticated_delete_uses_same_installation_identity(tmp_path: Path):
    transport = FakeTransport()
    client = TelemetryClient(
        enabled=False,
        version="0.5.8",
        state_store=StateStore(tmp_path / "telemetry.json"),
        build_info_path=tmp_path / "BUILD_INFO",
        transport=transport,
    )

    assert client.delete() is True
    call = transport.calls[0]
    assert call["method"] == "DELETE"
    assert call["path"] == "/v1/installation"
    assert call["payload"] == {
        "schema": 1,
        "installation_id": client.installation_id,
        "product": "digitalhouses_pve_agent",
    }
    assert call["token"] == client.installation_token


def test_linux_agent_telemetry_identity_uses_canonical_persistent_path():
    assert str(DEFAULT_TELEMETRY_STATE_FILE) == (
        "/var/lib/digitalhouses/digitalhouses_pve_agent/telemetry.json"
    )
