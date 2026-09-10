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


def test_main_wires_shared_topology_and_low_cost_guest_gpu_polling():
    text = (ROOT / "app" / "main.py").read_text()
    assert "GuestAwareProductionCollectors" in text
    assert "TopologyManager" in text
    assert 'scheduler.add("guests", interval_seconds=30.0' in text
    assert 'scheduler.add("gpu", interval_seconds=30.0' in text
    assert 'scheduler.add("topology"' not in text
    assert 'for name in ("cpu", "memory", "fans")' in text


def test_default_smart_poll_interval_is_one_minute():
    text = (ROOT / "app" / "runtime_settings.py").read_text()
    block = text[text.index('"disk_poll_interval_seconds"'):text.index('"cpu_publish_delta"')]
    assert "default=60.0" in block


def test_guest_aware_full_collection_orders_topology_before_dependents():
    text = (ROOT / "app" / "production_guest.py").read_text()
    mapping = text[text.index("def mapping(self):"):]
    assert mapping.index('"topology": self.topology_inventory') < mapping.index('"smart": self.smart')
    assert mapping.index('"topology": self.topology_inventory') < mapping.index('"gpu": self.gpu')
    assert mapping.index('"guests": self.guests') < mapping.index('"smart": self.smart')
