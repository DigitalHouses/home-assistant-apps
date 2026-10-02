"""Runtime gate: no consent must not initialize monitoring."""
import logging
from types import SimpleNamespace
import pytest
from app import app as runtime


def test_denied_consent_stops_before_side_effects(monkeypatch, caplog):
    def unexpected(*args, **kwargs):
        raise AssertionError("runtime started without consent")
    monkeypatch.setattr(runtime, "load_build_info", unexpected)
    config = SimpleNamespace(telemetry=SimpleNamespace(enabled=False))
    with caplog.at_level(logging.ERROR):
        result = runtime.run(config)
    assert result == 78
    assert "Statistics collection consent not granted. Stopping application." in caplog.text


def test_accepted_consent_enters_runtime(monkeypatch):
    class Entered(Exception):
        pass
    def start(*args, **kwargs):
        raise Entered()
    monkeypatch.setattr(runtime, "load_build_info", start)
    config = SimpleNamespace(telemetry=SimpleNamespace(enabled=True))
    with pytest.raises(Entered):
        runtime.run(config)
