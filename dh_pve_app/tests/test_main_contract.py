from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_production_entrypoint_wires_all_phase1_collector_groups():
    text = (ROOT / "app" / "production.py").read_text()
    for name in ("host", "cpu", "memory", "storage", "smart", "gpu", "fans"):
        assert f'"{name}": self.{name}' in text


def test_main_uses_event_driven_runtime_without_state_heartbeat():
    text = (ROOT / "app" / "main.py").read_text()
    assert "runtime.process_events()" in text
    assert "runtime.tick(time.monotonic())" in text
    assert "heartbeat" not in text.casefold()
