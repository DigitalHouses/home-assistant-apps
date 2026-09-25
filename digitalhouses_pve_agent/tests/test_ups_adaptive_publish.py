from app.publish_policy import PublishPolicy
from app.runtime_settings import RuntimeSettings
from app.ups_nut import parse_upsc_output, ups_metrics


def _should_publish(previous_text: str, current_text: str) -> bool:
    policy = PublishPolicy(RuntimeSettings())
    previous = ups_metrics(parse_upsc_output(previous_text))
    current = ups_metrics(parse_upsc_output(current_text))
    assert policy.evaluate(previous).publish is True
    policy.mark_published(previous)
    return policy.evaluate(current).publish


def test_online_mode_uses_sparse_runtime_and_load_thresholds():
    previous = "ups.status: OL\nbattery.runtime: 2160\nups.load: 5\n"

    assert _should_publish(
        previous,
        "ups.status: OL\nbattery.runtime: 2100\nups.load: 9\n",
    ) is False
    assert _should_publish(
        previous,
        "ups.status: OL\nbattery.runtime: 1860\nups.load: 5\n",
    ) is True
    assert _should_publish(
        previous,
        "ups.status: OL\nbattery.runtime: 2160\nups.load: 10\n",
    ) is True


def test_online_mode_uses_two_percent_charge_and_three_volt_thresholds():
    previous = (
        "ups.status: OL\nbattery.charge: 100\n"
        "input.voltage: 220\noutput.voltage: 220\nbattery.voltage: 27\n"
    )

    assert _should_publish(
        previous,
        "ups.status: OL\nbattery.charge: 99\n"
        "input.voltage: 222\noutput.voltage: 222\nbattery.voltage: 29\n",
    ) is False
    assert _should_publish(
        previous,
        "ups.status: OL\nbattery.charge: 98\n"
        "input.voltage: 220\noutput.voltage: 220\nbattery.voltage: 27\n",
    ) is True
    assert _should_publish(
        previous,
        "ups.status: OL\nbattery.charge: 100\n"
        "input.voltage: 223\noutput.voltage: 220\nbattery.voltage: 27\n",
    ) is True


def test_on_battery_mode_uses_tighter_thresholds():
    previous = (
        "ups.status: OB DISCHRG\nbattery.charge: 100\nbattery.runtime: 2160\n"
        "ups.load: 5\ninput.voltage: 220\noutput.voltage: 220\nbattery.voltage: 27\n"
    )

    assert _should_publish(
        previous,
        "ups.status: OB DISCHRG\nbattery.charge: 99\nbattery.runtime: 2160\n"
        "ups.load: 5\ninput.voltage: 220\noutput.voltage: 220\nbattery.voltage: 27\n",
    ) is True
    assert _should_publish(
        previous,
        "ups.status: OB DISCHRG\nbattery.charge: 100\nbattery.runtime: 2100\n"
        "ups.load: 5\ninput.voltage: 220\noutput.voltage: 220\nbattery.voltage: 27\n",
    ) is True
    assert _should_publish(
        previous,
        "ups.status: OB DISCHRG\nbattery.charge: 100\nbattery.runtime: 2160\n"
        "ups.load: 7\ninput.voltage: 220\noutput.voltage: 220\nbattery.voltage: 27\n",
    ) is True
    assert _should_publish(
        previous,
        "ups.status: OB DISCHRG\nbattery.charge: 100\nbattery.runtime: 2160\n"
        "ups.load: 5\ninput.voltage: 222\noutput.voltage: 220\nbattery.voltage: 27\n",
    ) is True


def test_operating_mode_change_publishes_immediately():
    assert _should_publish(
        "ups.status: OL\nbattery.charge: 100\n",
        "ups.status: OB DISCHRG\nbattery.charge: 100\n",
    ) is True


def test_service_facts_publish_when_they_change():
    previous = (
        "ups.status: OL\nups.beeper.status: enabled\n"
        "ups.test.result: No test initiated\nbattery.charge.low: 10\n"
    )
    current = (
        "ups.status: OL\nups.beeper.status: disabled\n"
        "ups.test.result: No test initiated\nbattery.charge.low: 10\n"
    )

    assert _should_publish(previous, current) is True
