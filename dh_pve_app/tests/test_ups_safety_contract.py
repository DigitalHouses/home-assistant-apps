from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alpha_has_no_power_control_commands():
    app_text = "\n".join(
        p.read_text(encoding="utf-8") for p in (ROOT / "app").glob("*.py")
    )
    forbidden = ("upscmd", "upsrw", "FSD", "shutdown -h", "poweroff")
    for token in forbidden:
        assert token not in app_text


def test_installer_does_not_configure_or_control_nut():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "/etc/nut" not in text
    assert "nut-monitor" not in text
    assert "nut-server" not in text
    assert "upsmon" not in text


def test_ups_reader_is_read_only_upsc_backend():
    text = (ROOT / "app" / "ups_nut.py").read_text(encoding="utf-8")
    assert '["upsc", f"{config.name}@{config.host}:{config.port}"]' in text
    assert "upscmd" not in text
    assert "upsrw" not in text
