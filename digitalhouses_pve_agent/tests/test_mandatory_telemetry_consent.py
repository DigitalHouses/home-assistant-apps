"""Runtime gate: no consent must not initialize monitoring."""
import logging
from types import SimpleNamespace
import pytest
from app import main as runtime


def test_denied_consent_stops_before_side_effects(monkeypatch, caplog, tmp_path):
    def unexpected(*args, **kwargs):
        raise AssertionError("runtime started without consent")
    monkeypatch.setattr(runtime, "_shutdown_tracker", unexpected)
    config = SimpleNamespace(telemetry=SimpleNamespace(enabled=False))
    with caplog.at_level(logging.ERROR):
        result = runtime.run(config, state_dir=tmp_path)
    assert result == 1
    assert "Statistics collection consent not granted. Stopping application." in caplog.text


def test_accepted_consent_enters_runtime(monkeypatch, tmp_path):
    class Entered(Exception):
        pass
    def start(*args, **kwargs):
        raise Entered()
    monkeypatch.setattr(runtime, "_shutdown_tracker", start)
    config = SimpleNamespace(telemetry=SimpleNamespace(enabled=True))
    with pytest.raises(Entered):
        runtime.run(config, state_dir=tmp_path)
