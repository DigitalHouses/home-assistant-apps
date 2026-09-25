from pathlib import Path

from app.collectors import memory

FIXTURES = Path(__file__).parent / "fixtures" / "host"


def test_parse_memory_inventory_for_n100_and_legacy_i3():
    assert hasattr(memory, "parse_dmidecode_memory")
    n100 = memory.parse_dmidecode_memory(
        (FIXTURES / "shahristan_dmidecode_memory.txt").read_text()
    )
    i3 = memory.parse_dmidecode_memory(
        (FIXTURES / "legacy_i3_dmidecode_memory.txt").read_text()
    )

    assert (n100.total_slots, n100.populated_slots, n100.total_gib) == (2, 1, 16.0)
    assert (n100.memory_type, n100.form_factor, n100.speed_mt_s) == (
        "DDR4", "SODIMM", 3200
    )
    assert n100.modules[0].manufacturer is None
    assert n100.modules[0].part_number is None

    assert (i3.total_slots, i3.populated_slots, i3.total_gib) == (2, 1, 8.0)
    assert (i3.memory_type, i3.form_factor, i3.speed_mt_s) == (
        "DDR4", "DIMM", 2133
    )
    assert i3.modules[0].manufacturer == "1315"
    assert i3.modules[0].part_number == "CT8G4DFS8213.C8FBR1"


def test_collect_memory_inventory_runs_dmidecode():
    assert hasattr(memory, "collect_memory_inventory")
    calls = []

    class Result:
        stdout = (FIXTURES / "shahristan_dmidecode_memory.txt").read_text()

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    inventory = memory.collect_memory_inventory(run=fake_run)
    assert inventory.populated_slots == 1
    assert calls == [
        (
            ["dmidecode", "-t", "memory"],
            {"check": True, "capture_output": True, "text": True},
        )
    ]
