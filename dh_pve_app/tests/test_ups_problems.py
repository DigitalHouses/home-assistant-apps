from app.ups_health import summarize_ups_problems
from app.ups_nut import parse_upsc_output


def test_healthy_online_ups_has_no_problems():
    summary = summarize_ups_problems(parse_upsc_output("ups.status: OL\n"))

    assert summary.count == 0
    assert summary.severity == "ok"
    assert summary.problems == ()
    assert summary.details == "Проблем не обнаружено."


def test_on_battery_is_warning_and_low_battery_escalates_to_critical():
    summary = summarize_ups_problems(
        parse_upsc_output("ups.status: OB LB DISCHRG\n")
    )

    assert summary.count == 2
    assert summary.severity == "critical"
    assert summary.problems == (
        "ИБП работает от батареи.",
        "Низкий заряд батареи.",
    )
    assert summary.details == (
        "1. ИБП работает от батареи.\n"
        "2. Низкий заряд батареи."
    )


def test_overload_is_critical_replace_battery_and_bypass_are_warnings():
    overload = summarize_ups_problems(parse_upsc_output("ups.status: OL OVER\n"))
    replace_battery = summarize_ups_problems(parse_upsc_output("ups.status: OL RB\n"))
    bypass = summarize_ups_problems(parse_upsc_output("ups.status: BYPASS\n"))

    assert overload.severity == "critical"
    assert overload.problems == ("Перегрузка ИБП.",)
    assert replace_battery.severity == "warning"
    assert replace_battery.problems == ("Требуется замена батареи ИБП.",)
    assert bypass.severity == "warning"
    assert bypass.problems == ("ИБП работает в режиме bypass.",)


def test_charging_and_discharging_are_not_problems_by_themselves():
    charging = summarize_ups_problems(parse_upsc_output("ups.status: OL CHRG\n"))
    discharging = summarize_ups_problems(parse_upsc_output("ups.status: OL DISCHRG\n"))

    assert charging.count == 0
    assert discharging.count == 0


def test_unknown_power_state_is_warning():
    summary = summarize_ups_problems(parse_upsc_output("ups.status: CAL\n"))

    assert summary.count == 1
    assert summary.severity == "warning"
    assert summary.problems == ("Состояние питания ИБП не определено.",)


def test_nut_read_failure_is_critical_even_without_snapshot():
    summary = summarize_ups_problems(None, nut_available=False)

    assert summary.count == 1
    assert summary.severity == "critical"
    assert summary.problems == ("Данные ИБП через NUT недоступны.",)
