
from pathlib import Path
import pytest

from app.collectors.cpu import (
    CPU_BREAKDOWN_FIELDS, cpu_breakdown_percent, cpu_usage_percent, parse_cpu_stat_line,
)
from app.presentation_pve import PvePresentationRouter, PresentationSubsystem
from test_discovery_groups import _components, _config, _identity
from app.topics import build_topics, state_group_topic

ROOT = Path(__file__).resolve().parents[1]


def times(*values):
    return parse_cpu_stat_line("cpu " + " ".join(map(str, values)))


def test_guest_nice_irq_and_iowait_are_counted_once():
    before = times(100, 20, 40, 300, 10, 5, 5, 0, 30, 5)
    after = times(130, 30, 50, 330, 20, 7, 13, 0, 50, 10)
    result = cpu_breakdown_percent(before, after)
    assert result == pytest.approx(dict(user=15, system=10, guest=25,
                                         iowait=10, irq=10, idle=30))
    assert sum(result.values()) == pytest.approx(100)
    assert cpu_usage_percent(before, after) == 60.0


def test_steal_remains_unassigned_and_short_kernel_rows_work():
    before = times(0, 0, 0, 0)
    after = times(10, 0, 10, 60, 0, 0, 0, 20)
    result = cpu_breakdown_percent(before, after)
    assert result == pytest.approx(dict(user=10, system=10, guest=0,
                                         iowait=0, irq=0, idle=60))
    assert sum(result.values()) == pytest.approx(80)
    assert cpu_usage_percent(before, after) == 40.0


@pytest.mark.parametrize("after", [
    (100, 20, 40, 300, 10, 5, 5, 0, 30, 5),  # no elapsed time
    (110, 20, 50, 320, 9, 5, 5, 0, 30, 5),  # decreasing iowait
    (110, 20, 50, 320, 10, 5, 5, 0, 41, 5),  # impossible guest delta
    (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),  # reboot/reset
])
def test_invalid_sample_is_unknown(after):
    assert cpu_breakdown_percent(times(100,20,40,300,10,5,5,0,30,5), times(*after)) is None


def test_cpu_group_publishes_synchronized_averages_and_unknown():
    router = PvePresentationRouter()
    def route(now, shares, **kwargs):
        return router.route(
            {"cpu": PresentationSubsystem(
                available=True, data={"usage_percent": 20, "breakdown": shares},
                last_success="2026-11-28T00:00:00+00:00", error=None)},
            selected=("cpu",), now=now, collected_at="2026-11-28T00:00:00+00:00",
            last_refresh=None, **kwargs,
        )
    def data(publications):
        return next(p.payload["subsystems"]["cpu"]["data"] for p in publications if p.group == "cpu")
    a = dict(user=10, system=5, guest=5, iowait=0, irq=0, idle=80)
    b = dict(user=0, system=5, guest=15, iowait=0, irq=0, idle=80)
    assert all(v is None for v in data(route(0, None))["breakdown"].values())
    assert data(route(10, a))["breakdown"] == a
    assert not route(20, a)
    assert data(route(910, b))["breakdown"] == pytest.approx({k: (2*a[k]+b[k])/3 for k in a}, abs=0.005)
    assert all(v is None for v in data(route(920, None))["breakdown"].values())
    assert data(route(930, b))["breakdown"] == b


def test_all_six_discovery_components_share_cpu_topic():
    components = _components()
    topic = state_group_topic(build_topics(_config().mqtt, _identity()), "cpu")
    for name in CPU_BREAKDOWN_FIELDS:
        item = components[f"cpu_{name}"]
        assert item["default_entity_id"] == f"sensor.dh_pve_agent_cpu_{name}"
        assert item["state_topic"] == topic
        assert item["state_class"] == "measurement"
        assert item["unit_of_measurement"] == "%"
        assert f"breakdown.{name}" in item["value_template"]


def test_recorder_and_both_charts_cover_every_new_sensor():
    view = (ROOT / "dashboards/ru/10_pve_proxmox.yaml").read_text()
    package = (ROOT / "packages/common/dh_pve_agent_package.yaml").read_text()
    for name in CPU_BREAKDOWN_FIELDS:
        entity = f"sensor.dh_pve_agent_cpu_{name}"
        assert f"        - {entity}\n" in package
        assert view.count(f"- entity: {entity}\n") == 2
    assert "chart_type: line-stack" in view
    assert "chart_type: line\n" in view
    for title in ("Структура CPU · 24 часа", "Детализация CPU · 24 часа"):
        start = view.index("      - type: statistics-graph\n        title: " + title)
        card = view[start:].split("\n      - type:", 1)[0]
        assert "        entities:\n" in card
        assert "        visibility:\n          - condition: numeric_state\n" in card
        assert "            entity: sensor.dh_pve_agent_cpu_idle\n            above: -1\n" in card
        assert "custom:auto-entities" not in card




def test_production_collector_reuses_single_proc_stat_read(tmp_path, monkeypatch):
    from app import production

    samples = iter([
        times(100, 20, 40, 300, 10, 5, 5, 0, 30, 5),
        times(130, 30, 50, 330, 20, 7, 13, 0, 50, 10),
    ])
    reads = []

    def read(path):
        reads.append(path)
        return next(samples)

    monkeypatch.setattr(production, "read_cpu_times", read)
    collector = production.ProductionCollectors(
        node_name="pve", disk_state_store=None, sys_root=tmp_path, proc_root=tmp_path,
    )
    assert collector.cpu().data["breakdown"] is None
    sample = collector.cpu()
    assert sample.data["usage_percent"] == 60
    assert sample.data["breakdown"] == pytest.approx(
        dict(user=15, system=10, guest=25, iowait=10, irq=10, idle=30)
    )
    assert reads == [tmp_path / "stat", tmp_path / "stat"]
