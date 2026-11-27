"""Tests for passive PVE event notifications and task decoding."""
from __future__ import annotations

import io
import re

from app import guest_events


def test_event_classifier_accepts_proxmox_lifecycle_and_backup_completion():
    for kind in (
        "qmstart", "qmstop", "qmshutdown", "qmreboot", "qmreset",
        "qmsuspend", "qmresume", "qmcreate", "qmclone", "qmdestroy",
        "vzstart", "vzstop", "vzshutdown", "vzreboot", "vzsuspend",
        "vzresume", "vzcreate", "vzclone", "vzdestroy",
    ):
        message = f"pvedaemon[5]: <root@pam> end task UPID:pve:1:2:3:4:{kind}:110:root@pam: OK"
        assert guest_events.event_kind(message) == "guests", kind
        assert re.search(guest_events._JOURNAL_GREP, message), kind

    backup = "pvescheduler: end task UPID:pve:1:2:3:4:vzdump:777:root@pam: ERR"
    assert guest_events.event_kind(backup) == "backup"
    assert re.search(guest_events._JOURNAL_GREP, backup)
    assert guest_events.event_kind("qmeventd: Finished cleanup for 110") == "guests"
    assert guest_events.event_kind("kernel: unrelated log message") is None
    assert guest_events.event_kind("pvedaemon: starting task UPID:pve:1:2:3:4:qmstart:110:root@pam:") is None


def test_monitor_follows_only_new_events_and_dispatches_on_main_thread(monkeypatch):
    events = []
    seen_commands = []
    monitor = guest_events.PveGuestEventMonitor(
        lambda: events.append("guests"),
        lambda: (events.append("backup"), monitor._stop.set()),
    )
    messages = "\n".join((
        "pve qmeventd[4]: Finished cleanup for 110",
        "pve pvescheduler[4]: end task UPID:pve:1:2:3:4:vzdump:777:root@pam: OK",
    )) + "\n"

    class FakeProcess:
        def __init__(self, command, **kwargs):
            seen_commands.append(command)
            self.stdout = io.StringIO(messages)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def poll(self):
            return 0

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(guest_events.subprocess, "Popen", FakeProcess)
    monitor._follow()
    assert events == ["guests", "backup"]
    assert "--follow" in seen_commands[0]
    assert "--lines=0" in seen_commands[0]
    assert "--grep" in seen_commands[0]
    assert monitor.healthy is False


def test_unavailable_journal_stream_keeps_fallback_possible(monkeypatch):
    monitor = guest_events.PveGuestEventMonitor(lambda: None, lambda: None)

    def unavailable(*args, **kwargs):
        monitor._stop.set()
        raise OSError("journalctl unavailable")

    monkeypatch.setattr(guest_events.subprocess, "Popen", unavailable)
    monitor._follow()
    assert monitor.healthy is False


def test_scheduled_backup_with_empty_upid_id():
    assert guest_events.event_kind("end task UPID:pve:1:2:3:4:vzdump::root@pam: OK") == "backup"

def test_real_pve_84_scheduler_messages_and_bulk_guest_task():
    for message in ("INFO: Backup job finished successfully", "INFO: Backup job finished with errors"):
        assert guest_events.event_kind(message) == "backup"
        assert re.search(guest_events._JOURNAL_GREP, message)
    assert guest_events.event_kind("<root@pam> end task UPID:pve:1:2:3:startall::root@pam: OK") == "guests"
