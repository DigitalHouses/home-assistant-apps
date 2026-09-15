from pathlib import Path

from app.config import UpsConfig
from app.ups_shutdown_budget_reader import read_shutdown_budget


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _config():
    return UpsConfig(
        enabled=True,
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=10.0,
        command_timeout_seconds=3.0,
    )


def _seed(tmp_path: Path):
    pve = tmp_path / "pve"
    qemu = pve / "qemu-server"
    lxc = pve / "lxc"
    qemu.mkdir(parents=True)
    lxc.mkdir(parents=True)
    (qemu / "110.conf").write_text(
        "name: haos\nonboot: 1\nstartup: order=3,up=30,down=60\n",
        encoding="utf-8",
    )
    (qemu / "700.conf").write_text(
        "name: truenas\nonboot: 1\nstartup: order=2,up=30,down=100\n",
        encoding="utf-8",
    )
    (lxc / "100.conf").write_text(
        "hostname: postgres\nonboot: 1\nstartup: order=1,up=30,down=40\n",
        encoding="utf-8",
    )
    datacenter = pve / "datacenter.cfg"
    datacenter.write_text("max_workers: 1\n", encoding="utf-8")
    rrd = pve / ".rrd"
    rrd.write_text(
        "pve2-node/PVE:1000:0:1000:0.1:4:0.1:0:100:20:10:1:100:10:0:0\n"
        "pve2.3-vm/110:100:haos:running:0:1000:4:0.1:100:20:32:10:0:0:0:0\n"
        "pve2.3-vm/700:100:truenas:running:0:1000:4:0.1:100:20:32:10:0:0:0:0\n"
        "pve2.3-vm/100:100:postgres:stopped:0:1000:2:0.1:100:20:32:10:0:0:0:0\n",
        encoding="utf-8",
    )
    upsmon = tmp_path / "upsmon.conf"
    upsmon.write_text(
        "MONITOR ups@localhost 1 user pass primary\n"
        "HOSTSYNC 120\n"
        "FINALDELAY 5\n"
        "SHUTDOWNCMD \"/sbin/shutdown -h now\"\n",
        encoding="utf-8",
    )
    return qemu, lxc, datacenter, rrd, upsmon


def _runner_with_clients(text):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        assert command[:2] == ["upsc", "-c"]
        return Completed(stdout=text)

    return runner, calls


def test_reader_uses_pve_cache_files_and_remote_nut_clients_without_qm_or_pct(tmp_path):
    qemu, lxc, datacenter, rrd, upsmon = _seed(tmp_path)
    runner, calls = _runner_with_clients("127.0.0.1\n192.168.11.33\n")

    result = read_shutdown_budget(
        _config(),
        node_name="PVE",
        history=(),
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        rrd_path=rrd,
        upsmon_path=upsmon,
        now_epoch=lambda: 1000.0,
        runner=runner,
    )

    assert result.available is True
    assert result.configured_guest_budget_seconds == 160
    assert result.hostsync_budget_seconds == 120
    assert result.finaldelay_seconds == 5
    assert result.host_tail_budget_seconds == 90
    assert result.shutdown_budget_seconds == 375
    assert result.configuration_fingerprint
    assert result.history_evidence_status == "none"
    assert calls == [["upsc", "-c", "ups@127.0.0.1:3493"]]


def test_reader_uses_only_clean_comparable_history_and_history_never_reduces_budget(tmp_path):
    qemu, lxc, datacenter, rrd, upsmon = _seed(tmp_path)
    runner, _ = _runner_with_clients("127.0.0.1\n192.168.11.33\n")
    baseline = read_shutdown_budget(
        _config(),
        node_name="PVE",
        history=(),
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        rrd_path=rrd,
        upsmon_path=upsmon,
        now_epoch=lambda: 1000.0,
        runner=runner,
    )
    fingerprint = baseline.configuration_fingerprint

    history = (
        {
            "shutdown_clean": True,
            "shutdown_budget_fingerprint": fingerprint,
            "guest_shutdown_total_seconds": 180,
            "all_guests_stopped_to_shutdown_seconds": 110,
        },
        {
            "shutdown_clean": True,
            "shutdown_budget_fingerprint": fingerprint,
            "guest_shutdown_total_seconds": 100,
            "all_guests_stopped_to_shutdown_seconds": 20,
        },
        {
            "shutdown_clean": False,
            "shutdown_budget_fingerprint": fingerprint,
            "guest_shutdown_total_seconds": 9999,
            "all_guests_stopped_to_shutdown_seconds": 9999,
        },
        {
            "shutdown_clean": True,
            "shutdown_budget_fingerprint": "different",
            "guest_shutdown_total_seconds": 8888,
            "all_guests_stopped_to_shutdown_seconds": 8888,
        },
    )
    runner2, _ = _runner_with_clients("127.0.0.1\n192.168.11.33\n")
    result = read_shutdown_budget(
        _config(),
        node_name="PVE",
        history=history,
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        rrd_path=rrd,
        upsmon_path=upsmon,
        now_epoch=lambda: 1000.0,
        runner=runner2,
    )

    assert result.observed_guest_budget_seconds == 180
    assert result.effective_guest_budget_seconds == 180
    assert result.observed_host_tail_seconds == 110
    assert result.host_tail_budget_seconds == 110
    assert result.shutdown_budget_seconds == 415
    assert result.history_evidence_status == "comparable_clean"


def test_reader_uses_zero_hostsync_when_no_remote_nut_secondary_is_connected(tmp_path):
    qemu, lxc, datacenter, rrd, upsmon = _seed(tmp_path)
    runner, _ = _runner_with_clients("127.0.0.1\n::1\n")

    result = read_shutdown_budget(
        _config(),
        node_name="PVE",
        history=(),
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        rrd_path=rrd,
        upsmon_path=upsmon,
        now_epoch=lambda: 1000.0,
        runner=runner,
    )

    assert result.available is True
    assert result.hostsync_budget_seconds == 0
    assert result.shutdown_budget_seconds == 255


def test_reader_fails_closed_when_runtime_cache_or_nut_client_state_is_unavailable(tmp_path):
    qemu, lxc, datacenter, rrd, upsmon = _seed(tmp_path)
    rrd.write_text("", encoding="utf-8")
    runner, _ = _runner_with_clients("127.0.0.1\n")

    missing_cache = read_shutdown_budget(
        _config(),
        node_name="PVE",
        history=(),
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        rrd_path=rrd,
        upsmon_path=upsmon,
        now_epoch=lambda: 1000.0,
        runner=runner,
    )
    assert missing_cache.available is False
    assert missing_cache.unavailable_reason == "pve_runtime_cache_unavailable"

    _seed(tmp_path)

    def failed_clients(command, **kwargs):
        return Completed(returncode=1, stderr="access denied")

    missing_clients = read_shutdown_budget(
        _config(),
        node_name="PVE",
        history=(),
        qemu_dir=qemu,
        lxc_dir=lxc,
        datacenter_path=datacenter,
        rrd_path=rrd,
        upsmon_path=upsmon,
        now_epoch=lambda: 1000.0,
        runner=failed_clients,
    )
    assert missing_clients.available is False
    assert missing_clients.unavailable_reason == "hostsync_applicability_unavailable"
