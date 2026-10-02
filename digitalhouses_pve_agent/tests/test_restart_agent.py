from pathlib import Path
from types import SimpleNamespace

from app.main import RESTART_EXIT_CODE, _restart_denial_reason


ROOT = Path(__file__).resolve().parents[1]


def _ups(
    *,
    line_power=True,
    on_battery=False,
    low_battery=False,
    discharging=False,
    status_tokens=("OL",),
    nut_available=True,
    committed=False,
):
    snapshot = SimpleNamespace(
        line_power=line_power,
        on_battery=on_battery,
        low_battery=low_battery,
        discharging=discharging,
        status_tokens=status_tokens,
    )
    return SimpleNamespace(
        nut_available=nut_available,
        last_snapshot=snapshot,
        reader=lambda config: snapshot,
        config=object(),
        software_shutdown_committed=lambda: committed,
    )


def test_restart_allowed_without_configured_ups():
    assert _restart_denial_reason(None, ups_startup_attempted=False) is None


def test_restart_allowed_with_online_ups():
    assert _restart_denial_reason(_ups(), ups_startup_attempted=True) is None


def test_restart_denied_before_ups_initialization_or_without_nut():
    assert _restart_denial_reason(_ups(), ups_startup_attempted=False)
    assert _restart_denial_reason(
        _ups(nut_available=False), ups_startup_attempted=True
    )


def test_restart_denied_after_software_shutdown_committed():
    assert _restart_denial_reason(
        _ups(committed=True), ups_startup_attempted=True
    )


def test_restart_denied_for_unsafe_ups_snapshots():
    for kwargs in (
        {"line_power": False},
        {"on_battery": True},
        {"low_battery": True},
        {"discharging": True},
        {"status_tokens": ("OL", "FSD")},
    ):
        assert _restart_denial_reason(
            _ups(**kwargs), ups_startup_attempted=True
        ), kwargs


def test_restart_denied_when_ups_snapshot_missing():
    ups = _ups()
    ups.reader = lambda config: None
    assert _restart_denial_reason(ups, ups_startup_attempted=True)


def test_restart_denied_when_fresh_ups_read_fails():
    ups = _ups()

    def broken_reader(config):
        raise ConnectionError("NUT unavailable")

    ups.reader = broken_reader
    reason = _restart_denial_reason(ups, ups_startup_attempted=True)
    assert reason and "NUT unavailable" in reason


def test_restart_checks_fresh_state_not_cached_state():
    ups = _ups()
    ups.reader = lambda config: _ups(on_battery=True).last_snapshot
    assert _restart_denial_reason(ups, ups_startup_attempted=True)


def test_restart_is_service_owned_not_self_systemctl():
    service = (ROOT / "systemd" / "digitalhouses_pve_agent.service").read_text(
        encoding="utf-8"
    )
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert RESTART_EXIT_CODE == 75
    assert "Restart=on-failure" in service
    assert "RestartSec=5" in service
    assert "return RESTART_EXIT_CODE if restart_requested else 0" in main
    assert "systemctl restart" not in main
