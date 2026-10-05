from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "ups"
GUIDE = ROOT / "docs" / "UPS_SHUTDOWN_SETUP.md"
CARD = ROOT / "examples" / "dh_pve_agent_shutdown_readiness_card.yaml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ups_setup_guide_and_tools_exist():
    assert GUIDE.is_file()
    assert (TOOLS / "nut-readiness-audit.sh").is_file()
    assert (TOOLS / "nut-install-packages.sh").is_file()
    assert (TOOLS / "nut-stage-primary-config.sh").is_file()


def test_commissioning_scripts_have_valid_shell_syntax():
    for path in sorted(TOOLS.glob("*.sh")):
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_commissioning_toolkit_has_no_live_shutdown_or_ups_output_actions():
    forbidden = (
        "upsmon -c fsd",
        "upscmd ",
        "load.off",
        "load.on",
        "shutdown.return",
        "shutdown.stayoff",
        "shutdown.reboot",
    )
    for path in sorted(TOOLS.glob("*.sh")):
        text = _read(path).lower()
        for token in forbidden:
            assert token not in text, f"{token!r} must not appear in {path.name}"


def test_staging_tool_never_applies_nut_configuration_or_restarts_services():
    text = _read(TOOLS / "nut-stage-primary-config.sh")
    assert 'SHUTDOWNCMD "/bin/true"' in text
    assert "dh_primary_user" in text
    assert "HOSTSYNC 120" in text
    assert "FINALDELAY 5" in text
    assert "MODE=standalone" in text
    assert "openssl rand -hex 24" in text
    assert 'output_dir="$(realpath -m -- "$output_dir")"' in text
    assert '[[ "$output_dir" != /root/* ]]' in text
    assert "systemctl " not in text
    assert "apt-get " not in text


def test_package_helper_only_installs_packages():
    text = _read(TOOLS / "nut-install-packages.sh")
    assert "nut-server" in text
    assert "nut-client" in text
    assert "nut-snmp" in text
    assert "systemctl " not in text
    assert "/etc/nut/" not in text


def test_audit_is_explicitly_read_only():
    text = _read(TOOLS / "nut-readiness-audit.sh")
    assert "READ-ONLY" in text
    assert "--ups-policy-preflight" in text
    assert "nut-scanner -U" in text
    assert "systemctl restart" not in text
    assert "systemctl start" not in text
    assert "systemctl enable" not in text


def test_guide_documents_safe_commissioning_before_production_activation():
    text = _read(GUIDE)
    assert 'SHUTDOWNCMD "/bin/true"' in text
    assert 'SHUTDOWNCMD "/sbin/shutdown -h now"' in text
    assert "nut-readiness-audit.sh" in text
    assert "nut-install-packages.sh" in text
    assert "nut-stage-primary-config.sh" in text
    assert "controlled live shutdown" in text.lower()
    assert "does not rewrite" in text


def test_shutdown_card_links_to_setup_guide_and_uses_human_guidance():
    text = _read(CARD)
    assert "UPS_SHUTDOWN_SETUP.md" in text
    assert "требуется настройка" in text
    assert "Что проверить" in text
    assert "Роль NUT" in text
    assert "Автоматическое выключение PVE" in text
