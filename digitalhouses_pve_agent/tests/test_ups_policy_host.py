from pathlib import Path
from types import SimpleNamespace
import subprocess

from app.config import UpsConfig
from app.ups_policy_host import read_policy_safety_facts


def _ups_config():
    return UpsConfig(
        enabled=True,
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
        command_timeout_seconds=3.0,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _topology(tmp_path: Path) -> tuple[Path, Path, Path]:
    qemu = tmp_path / "qemu-server"
    lxc = tmp_path / "lxc"
    datacenter = tmp_path / "datacenter.cfg"

    _write(qemu / "110.conf", "onboot: 1\nstartup: order=30,down=60\n")
    _write(qemu / "501.conf", "onboot: 1\nstartup: order=50,down=30\n")
    _write(qemu / "700.conf", "onboot: 1\nstartup: order=1,down=100\n")
    _write(qemu / "777.conf", "agent: 1\n")
    _write(qemu / "900.conf", "memory: 4096\n")

    _write(lxc / "101.conf", "onboot: 1\nstartup: order=20,down=60\n")
    _write(lxc / "149.conf", "onboot: 1\nstartup: order=20,down=60\n")
    _write(lxc / "200.conf", "onboot: 1\nstartup: order=50,down=30\n")
    _write(lxc / "333.conf", "onboot: 1\nstartup: order=50,down=30\n")
    _write(lxc / "1011.conf", "onboot: 1\nstartup: order=40,up=10,down=30\n")
    _write(lxc / "10001.conf", "onboot: 1\nstartup: order=40,down=30\n")
    _write(lxc / "10004.conf", "onboot: 1\nstartup: order=40,down=30\n")
    _write(lxc / "150.conf", "hostname: nut-web\n")

    datacenter.write_text("keyboard: en-us\n", encoding="utf-8")
    return qemu, lxc, datacenter


def _shutdown_policy():
    return SimpleNamespace(hostsync_seconds=120, finaldelay_seconds=5)


def _runner(*, running_extra: tuple[int, ...] = (), nproc: int = 4):
    def run(command, **kwargs):
        if command == ["qm", "list"]:
            rows = [
                "VMID NAME STATUS MEM(MB) BOOTDISK(GB) PID",
                "110 haos-asyl-mura running 2048 32.00 1",
                "501 plex-vm running 2048 32.00 2",
                "700 TrueNAS running 4096 32.00 3",
                "777 digitalhouses.vip stopped 1024 32.00 0",
                "900 VM-WIN-11 " + ("running" if 900 in running_extra else "stopped") + " 4096 64.00 0",
            ]
            stdout = "\n".join(rows) + "\n"
        elif command == ["pct", "list"]:
            stdout = (
                "VMID Status Lock Name\n"
                "101 running postgresql\n"
                "149 running DHClimatePG\n"
                "150 stopped nut-web\n"
                "200 running uptimekuma\n"
                "333 running NetAlertX\n"
                "1011 running digitalhouses.vip\n"
                "10001 running wordpress\n"
                "10004 running docs\n"
            )
        elif command == ["nproc"]:
            stdout = f"{nproc}\n"
        elif command == [
            "upsc",
            "ups@127.0.0.1:3493",
            "ups.delay.shutdown",
        ]:
            stdout = "60\n"
        else:
            raise AssertionError(f"unexpected command: {command!r}")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return run


def test_read_policy_safety_facts_matches_current_pve_shutdown_topology(tmp_path):
    qemu, lxc, datacenter = _topology(tmp_path)

    facts = read_policy_safety_facts(
        _ups_config(),
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        runner=_runner(),
        shutdown_policy_reader=_shutdown_policy,
    )

    assert facts.guest_shutdown_budget_seconds == 280
    assert facts.hostsync_seconds == 120
    assert facts.finaldelay_seconds == 5
    assert facts.ups_poweroff_delay_seconds == 60
    assert facts.host_shutdown_reserve_seconds == 60
    assert facts.safety_margin_seconds == 60


def test_stopped_non_autostart_guests_do_not_inflate_policy_budget(tmp_path):
    qemu, lxc, datacenter = _topology(tmp_path)
    _write(qemu / "99134.conf", "startup: order=99,down=600\n")

    facts = read_policy_safety_facts(
        _ups_config(),
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        runner=_runner(),
        shutdown_policy_reader=_shutdown_policy,
    )

    assert facts.guest_shutdown_budget_seconds == 280


def test_running_non_autostart_guest_is_included_with_pve_defaults(tmp_path):
    qemu, lxc, datacenter = _topology(tmp_path)

    facts = read_policy_safety_facts(
        _ups_config(),
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        runner=_runner(running_extra=(900,)),
        shutdown_policy_reader=_shutdown_policy,
    )

    assert facts.guest_shutdown_budget_seconds == 460


def test_datacenter_max_workers_changes_parallel_group_budget(tmp_path):
    qemu, lxc, datacenter = _topology(tmp_path)
    datacenter.write_text("keyboard: en-us\nmax_workers: 2\n", encoding="utf-8")

    facts = read_policy_safety_facts(
        _ups_config(),
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        runner=_runner(nproc=4),
        shutdown_policy_reader=_shutdown_policy,
    )

    assert facts.guest_shutdown_budget_seconds == 340


def test_template_guests_are_excluded_even_if_onboot_is_present(tmp_path):
    qemu, lxc, datacenter = _topology(tmp_path)
    _write(qemu / "999.conf", "template: 1\nonboot: 1\nstartup: order=99,down=600\n")

    facts = read_policy_safety_facts(
        _ups_config(),
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        runner=_runner(),
        shutdown_policy_reader=_shutdown_policy,
    )

    assert facts.guest_shutdown_budget_seconds == 280
