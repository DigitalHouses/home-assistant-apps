from app.publish_policy import MetricValue, PublishPolicy
from app.runtime_settings import RuntimeSettings


def _policy():
    return PublishPolicy(RuntimeSettings())


def test_startup_publishes_and_no_change_is_suppressed_after_mark():
    policy = _policy()
    snapshot = {
        "cpu_usage": MetricValue(12.0, "cpu_percent"),
        "temperature": MetricValue(50.0, "temperature_c"),
    }

    first = policy.evaluate(snapshot)
    assert first.publish is True
    assert "startup" in first.reasons

    policy.mark_published(snapshot)
    second = policy.evaluate(snapshot)
    assert second.publish is False


def test_baseline_changes_only_after_mark_published():
    policy = _policy()
    initial = {"cpu_usage": MetricValue(10.0, "cpu_percent")}
    changed = {"cpu_usage": MetricValue(16.0, "cpu_percent")}

    policy.mark_published(initial)
    decision = policy.evaluate(changed)
    assert decision.publish is True

    decision_again = policy.evaluate(changed)
    assert decision_again.publish is True


def test_numeric_thresholds_and_zero_transition():
    policy = _policy()
    initial = {
        "cpu": MetricValue(10.0, "cpu_percent"),
        "ram": MetricValue(50.0, "memory_percent"),
        "temp": MetricValue(50.0, "temperature_c"),
        "freq": MetricValue(2800.0, "frequency_mhz"),
        "storage": MetricValue(70.0, "storage_percent"),
        "fan": MetricValue(1000.0, "fan_rpm"),
        "gpu": MetricValue(20.0, "gpu_percent"),
    }
    policy.mark_published(initial)

    small = {
        "cpu": MetricValue(14.9, "cpu_percent"),
        "ram": MetricValue(50.9, "memory_percent"),
        "temp": MetricValue(50.9, "temperature_c"),
        "freq": MetricValue(2899.0, "frequency_mhz"),
        "storage": MetricValue(70.4, "storage_percent"),
        "fan": MetricValue(1099.0, "fan_rpm"),
        "gpu": MetricValue(24.9, "gpu_percent"),
    }
    assert policy.evaluate(small).publish is False

    large = dict(small)
    large["temp"] = MetricValue(51.0, "temperature_c")
    assert policy.evaluate(large).publish is True

    policy.mark_published({"cpu": MetricValue(0.0, "cpu_percent")})
    assert policy.evaluate({"cpu": MetricValue(0.1, "cpu_percent")}).publish is True


def test_discrete_and_counter_changes_publish_immediately():
    policy = _policy()
    policy.mark_published({
        "smart": MetricValue("OK", "discrete"),
        "media_errors": MetricValue(0, "counter"),
    })

    assert policy.evaluate({
        "smart": MetricValue("ERROR", "discrete"),
        "media_errors": MetricValue(0, "counter"),
    }).publish is True

    assert policy.evaluate({
        "smart": MetricValue("OK", "discrete"),
        "media_errors": MetricValue(1, "counter"),
    }).publish is True


def test_force_publishes_without_change():
    policy = _policy()
    snapshot = {"cpu": MetricValue(10.0, "cpu_percent")}
    policy.mark_published(snapshot)

    decision = policy.evaluate(snapshot, force=True)
    assert decision.publish is True
    assert "force" in decision.reasons
