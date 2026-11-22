"""Regression: current-boot guest history must not scan every journald line."""

import re
from subprocess import CompletedProcess

from app import shutdown_history


GUEST_MESSAGES = [
    "pve systemd-logind[1]: The system will power off now!",
    "pve pve-guests[1]: Stopping VM 110 (timeout = 60 seconds)",
    "pve pvedaemon[1]: VM 110 qmp guest-shutdown got timeout",
    "pve pvedaemon[1]: end task UPID:pve:1:2:3:4:qmshutdown:110:root@pam: OK",
    "pve pct[1]: <root@pam> starting task UPID:pve:1:2:3:4:vzshutdown:333:root@pam:",
    "pve pct[1]: <root@pam> end task UPID:pve:1:2:3:4:vzshutdown:333:root@pam: OK",
    "pve pve-guests[1]: all VMs and CTs stopped",
    "pve systemd[1]: Reached target shutdown.target - System Shutdown.",
]


def test_current_boot_reader_filters_at_journalctl_source(monkeypatch):
    observed = []
    journal = [
        "pve kernel: harmless background log entry",
    ] * 100000 + GUEST_MESSAGES

    def fake_run(args, **kwargs):
        observed.append(args)
        assert kwargs["timeout"] == 20.0
        assert args[:3] == ["journalctl", "-b", "0"]
        regex = re.compile(args[args.index("--grep") + 1])
        filtered = [row for row in journal if regex.search(row)]
        return CompletedProcess(args, 0, stdout="".join(
            f"2026-11-22T08:35:00+05:00 {row}\n" for row in filtered
        ), stderr="")

    monkeypatch.setattr(shutdown_history.subprocess, "run", fake_run)
    output = shutdown_history._default_current_boot_journal_reader()
    lines = output.splitlines()
    assert len(lines) == len(GUEST_MESSAGES)
    assert "harmless" not in output
    assert len(observed) == 1

    parsed = shutdown_history.parse_guest_shutdown_journal(output)
    assert parsed["guests"]["vm"]["110"]["result"] == "timeout"
    assert parsed["guests"]["lxc"]["333"]["result"] == "clean"
    assert parsed["all_guests_stopped_at"] is not None
    assert parsed["clean_shutdown"] is True


def test_journal_filter_preserves_unscoped_failure_and_simple_end():
    evidence = [
        "pve pvedaemon[1]: Stopping CT 111 (timeout = 30 seconds)",
        "pve pvedaemon[1]: VM quit/powerdown failed - terminating now with SIGTERM",
        "pve pvedaemon[1]: VM still running - terminating now with SIGKILL",
        "pve pvedaemon[1]: VM quit/powerdown failed - got timeout",
        "pve pvedaemon[1]: VM 110 task ended",
        "pve pvedaemon[1]: CT 111 task ended",
        "pve systemd[1]: System is powering down.",
        "pve systemd[1]: Reached target system power off.",
        "pve systemd-shutdown[1]: Syncing filesystems and block devices.",
    ]
    matcher = re.compile(shutdown_history._CURRENT_BOOT_GUEST_GREP)
    assert all(matcher.search(line) for line in evidence)
    assert not matcher.search("pve kernel: random unrelated SMART diagnostics")
    assert not matcher.search("pve qemu[2]: VM 111 guest-ping got timeout")


def test_previous_boot_journal_reader_remains_unfiltered(monkeypatch):
    observed = []

    def fake_run(args, **kwargs):
        observed.append(args)
        return CompletedProcess(args, 0, stdout="full previous boot", stderr="")

    monkeypatch.setattr(shutdown_history.subprocess, "run", fake_run)
    assert shutdown_history._default_previous_boot_journal_reader() == "full previous boot"
    assert observed[0][:3] == ["journalctl", "-b", "-1"]
    assert "--grep" not in observed[0]
