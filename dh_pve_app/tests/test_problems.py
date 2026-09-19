from app.problems import PveProblemEngine
from app.runtime_settings import RuntimeSettings


def thresholds(**overrides):
    values = RuntimeSettings().as_dict()
    values.update(overrides)
    return values


def active_ids(engine):
    return [item["problem_id"] for item in engine.aggregate().active]


def test_cpu_temperature_uses_fast_rolling_average_and_strict_threshold_semantics():
    engine = PveProblemEngine()
    limits = thresholds()

    assert engine.observe(0.0, {"cpu": {"temperature_c": 90.0}}, limits) == ()
    assert engine.observe(60.0, {"cpu": {"temperature_c": 90.0}}, limits) == ()
    assert active_ids(engine) == []

    started = engine.observe(61.0, {"cpu": {"temperature_c": 91.0}}, limits)
    assert len(started) == 1
    assert started[0].event_type == "problem_started"
    assert started[0].current.problem_id == "cpu_temperature"
    assert started[0].current.average == 90.5
    assert started[0].current.threshold == 90.0
    assert not hasattr(started[0].current, "summary")
    assert not hasattr(started[0].current, "details")

    # Equality is neither recovery nor a duplicate update.
    assert engine.observe(121.0, {"cpu": {"temperature_c": 89.0}}, limits) == ()
    assert active_ids(engine) == ["cpu_temperature"]

    recovered = engine.observe(122.0, {"cpu": {"temperature_c": 88.0}}, limits)
    assert len(recovered) == 1
    assert recovered[0].event_type == "problem_recovered"
    assert recovered[0].current.active is False


def test_invalid_numeric_samples_do_not_become_zero_or_recover_an_active_problem():
    engine = PveProblemEngine()
    limits = thresholds()

    engine.observe(0.0, {"cpu": {"temperature_c": 95.0}}, limits)
    started = engine.observe(60.0, {"cpu": {"temperature_c": 95.0}}, limits)
    assert started[0].event_type == "problem_started"

    for now, value in ((70.0, None), (80.0, float("nan")), (90.0, float("inf"))):
        assert engine.observe(now, {"cpu": {"temperature_c": value}}, limits) == ()

    state = engine.problem("cpu_temperature")
    assert state is not None
    assert state.active is True
    assert state.average == 95.0


def test_slow_problem_windows_are_isolated_per_object_and_domain():
    engine = PveProblemEngine()
    limits = thresholds()
    first = {
        "storage": {
            "local": {"name": "local", "usage_percent": 70.0},
            "backup": {"name": "backup", "usage_percent": 90.0},
        },
        "disk_temperature": {
            "nvme_hot": {"disk_type": "NVMe", "model": "Hot", "temperature_c": 81.0},
            "nvme_cool": {"disk_type": "NVMe", "model": "Cool", "temperature_c": 60.0},
            "unknown": {"disk_type": "other", "model": "Mystery", "temperature_c": 100.0},
        },
        "gpu": {
            "gpu0": {"display_name": "iGPU", "temperature_c": 90.0},
            "gpu1": {"display_name": "Cool GPU", "temperature_c": 50.0},
        },
    }

    assert engine.observe(0.0, first, limits) == ()
    transitions = engine.observe(300.0, first, limits)
    assert {item.current.problem_id for item in transitions} == {
        "storage_backup_percent_used",
        "disk_nvme_hot_temperature",
        "gpu_gpu0_temperature",
    }
    assert active_ids(engine) == [
        "disk_nvme_hot_temperature",
        "gpu_gpu0_temperature",
        "storage_backup_percent_used",
    ]
    assert engine.problem("disk_nvme_cool_temperature") is not None
    assert engine.problem("disk_nvme_cool_temperature").active is False
    assert engine.problem("disk_unknown_temperature") is None


def test_cpu_throttling_and_smart_failure_are_immediate_discrete_problems():
    engine = PveProblemEngine()
    limits = thresholds()

    baseline = {
        "cpu": {"throttling_active": False},
        "smart": {"disk0": {"model": "Disk", "smart_passed": True}},
    }
    assert engine.observe(0.0, baseline, limits) == ()

    throttled = engine.observe(1.0, {"cpu": {"throttling_active": True}}, limits)
    assert [item.event_type for item in throttled] == ["problem_started"]
    assert throttled[0].current.problem_id == "cpu_throttling"
    assert engine.observe(2.0, {"cpu": {"throttling_active": True}}, limits) == ()

    failed = engine.observe(
        3.0,
        {"smart": {"disk0": {"model": "Disk", "smart_passed": False}}},
        limits,
    )
    assert [item.event_type for item in failed] == ["problem_started"]
    assert failed[0].current.problem_id == "disk_disk0_smart"
    assert failed[0].current.severity == "critical"

    recovered = engine.observe(
        4.0,
        {
            "cpu": {"throttling_active": False},
            "smart": {"disk0": {"model": "Disk", "smart_passed": True}},
        },
        limits,
    )
    assert {item.current.problem_id for item in recovered} == {
        "cpu_throttling",
        "disk_disk0_smart",
    }
    assert all(item.event_type == "problem_recovered" for item in recovered)


def test_threshold_edit_immediately_reevaluates_current_valid_average():
    engine = PveProblemEngine()
    limits = thresholds()

    engine.observe(0.0, {"cpu": {"temperature_c": 85.0}}, limits)
    assert engine.observe(60.0, {"cpu": {"temperature_c": 85.0}}, limits) == ()

    started = engine.reevaluate_threshold("cpu_temperature_threshold", 80.0)
    assert [item.event_type for item in started] == ["problem_started"]
    assert started[0].current.average == 85.0

    updated = engine.reevaluate_threshold("cpu_temperature_threshold", 82.0)
    assert [item.event_type for item in updated] == ["problem_updated"]
    assert updated[0].current.active is True

    equality = engine.reevaluate_threshold("cpu_temperature_threshold", 85.0)
    assert [item.event_type for item in equality] == ["problem_updated"]
    assert equality[0].current.active is True

    recovered = engine.reevaluate_threshold("cpu_temperature_threshold", 90.0)
    assert [item.event_type for item in recovered] == ["problem_recovered"]
    assert recovered[0].current.active is False


def test_aggregate_is_deterministic_and_machine_only():
    engine = PveProblemEngine()
    limits = thresholds()

    engine.observe(
        0.0,
        {
            "cpu": {"throttling_active": True},
            "smart": {"disk0": {"model": "Disk A", "smart_passed": False}},
        },
        limits,
    )
    aggregate = engine.aggregate()

    assert aggregate.count == 2
    assert aggregate.severity == "critical"
    assert not hasattr(aggregate, "summary")
    assert [item["problem_id"] for item in aggregate.active] == [
        "cpu_throttling",
        "disk_disk0_smart",
    ]
    for item in aggregate.active:
        assert set(item) == {
            "problem_id",
            "category",
            "severity",
            "object_id",
            "object_name",
            "metric",
            "value",
            "average",
            "threshold",
        }
        assert "summary" not in item
        assert "details" not in item
