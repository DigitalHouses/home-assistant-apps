import json
import sys
from types import SimpleNamespace

import app.main as main_module
from app.config import MqttConfig, UpsConfig
from app.state_store import StateStore
from app.ups_policy_preflight import PreflightCheck, UpsPolicyPreflight


def _config():
    return SimpleNamespace(
        general=SimpleNamespace(log_level="info"),
        mqtt=MqttConfig(
            host="mqtt",
            port=1883,
            username="",
            password="",
            topic_prefix="DigitalHouses/Global/dh_pve_app",
            discovery_prefix="homeassistant",
            keepalive_seconds=60,
        ),
        ups=UpsConfig(
            enabled=False,
            name="",
            host="127.0.0.1",
            port=3493,
            poll_interval_seconds=5.0,
            command_timeout_seconds=3.0,
        ),
    )


def test_build_preflight_blocks_when_no_ups_has_been_selected(tmp_path):
    called = []

    report = main_module.build_ups_policy_preflight(
        _config(),
        state_dir=tmp_path,
        preflight_reader=lambda config: called.append(config),
    )

    assert report.state == "Blocked"
    assert report.ready is False
    assert called == []
    assert any(check.key == "ups_selected" and not check.ok for check in report.checks)


def test_build_preflight_uses_persisted_selected_ups(tmp_path):
    StateStore(tmp_path / "ups_selection.json").save({"selected_name": "ups"})
    seen = []
    expected = UpsPolicyPreflight(
        state="Ready",
        ready=True,
        checks=(PreflightCheck("ok", True, "ok"),),
        guest_shutdown_budget_seconds=280,
    )

    report = main_module.build_ups_policy_preflight(
        _config(),
        state_dir=tmp_path,
        preflight_reader=lambda config: seen.append(config) or expected,
    )

    assert report is expected
    assert len(seen) == 1
    assert seen[0].enabled is True
    assert seen[0].name == "ups"


def test_cli_prints_preflight_json_and_exits_without_starting_runtime(
    tmp_path, monkeypatch, capsys
):
    report = UpsPolicyPreflight(
        state="Ready",
        ready=True,
        checks=(PreflightCheck("ups_available", True, "ok"),),
        guest_shutdown_budget_seconds=280,
    )
    monkeypatch.setattr(main_module, "load_config", lambda path: _config())
    monkeypatch.setattr(
        main_module,
        "build_ups_policy_preflight",
        lambda config, state_dir: report,
    )
    monkeypatch.setattr(
        main_module,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("runtime started")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dh_pve_app",
            "--config",
            str(tmp_path / "config"),
            "--state-dir",
            str(tmp_path),
            "--ups-policy-preflight",
        ],
    )

    assert main_module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "Ready"
    assert payload["ready"] is True


def test_cli_returns_nonzero_for_blocked_preflight(tmp_path, monkeypatch, capsys):
    report = UpsPolicyPreflight(
        state="Blocked",
        ready=False,
        checks=(PreflightCheck("ups_available", False, "down"),),
        guest_shutdown_budget_seconds=None,
    )
    monkeypatch.setattr(main_module, "load_config", lambda path: _config())
    monkeypatch.setattr(
        main_module,
        "build_ups_policy_preflight",
        lambda config, state_dir: report,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dh_pve_app",
            "--state-dir",
            str(tmp_path),
            "--ups-policy-preflight",
        ],
    )

    assert main_module.main() == 2
    assert json.loads(capsys.readouterr().out)["state"] == "Blocked"
