"""Passive Proxmox task events from journald; never hook guest lifecycle."""
from __future__ import annotations

import logging
import re
import subprocess
import threading
from collections.abc import Callable


_LOG = logging.getLogger(__name__)
# Completed PVE tasks and unexpected QEMU exits. Source-side --grep means
# journalctl does not stream unrelated host log traffic into Python.
_TASK = (
    r"\bend task UPID:.*?:(?P<kind>qmstart|qmstop|qmshutdown|qmreboot|"
    r"qmreset|qmsuspend|qmresume|qmcreate|qmclone|qmdestroy|qmigrate|"
    r"vzstart|vzstop|vzshutdown|vzreboot|vzsuspend|vzresume|"
    r"vzcreate|vzclone|vzdestroy|vzmigrate|vzdump):[^:]*:"
)
_TASK_RE = re.compile(_TASK, re.IGNORECASE)
_QEMU_EXIT_RE = re.compile(r"\bFinished cleanup for\s+\d+\b", re.IGNORECASE)
_JOURNAL_GREP = rf"(?i)(?:{_TASK}|\bFinished cleanup for\s+\d+\b)"


def event_kind(message: str) -> str | None:
    """Return 'guests' or 'backup'; never trust generic log messages as events."""
    task = _TASK_RE.search(message)
    if task is not None:
        return "backup" if task.group("kind").lower() == "vzdump" else "guests"
    if _QEMU_EXIT_RE.search(message):
        return "guests"
    return None


class PveGuestEventMonitor:
    """Small, read-only journal follower. Caller owns all PVE/MQTT changes."""

    def __init__(
        self,
        on_guest_event: Callable[[], None],
        on_backup_event: Callable[[], None],
    ) -> None:
        self.on_guest_event = on_guest_event
        self.on_backup_event = on_backup_event
        self._stop = threading.Event()
        self._healthy = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None

    @property
    def healthy(self) -> bool:
        return self._healthy.is_set()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._follow, name="dh-pve-events", daemon=True
        )
        self._thread.start()

    def _follow(self) -> None:
        command = [
            "journalctl", "--boot=0", "--follow", "--lines=0",
            "--quiet", "--no-pager", "--output=cat", "--grep", _JOURNAL_GREP,
        ]
        while not self._stop.is_set():
            try:
                with subprocess.Popen(
                    command, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, bufsize=1,
                ) as proc:
                    self._process = proc
                    self._healthy.set()
                    assert proc.stdout is not None
                    for message in proc.stdout:
                        if self._stop.is_set():
                            break
                        kind = event_kind(message)
                        if kind == "guests":
                            self.on_guest_event()
                        elif kind == "backup":
                            self.on_backup_event()
                    proc.terminate() if proc.poll() is None else None
                    proc.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired) as exc:
                if not self._stop.is_set():
                    _LOG.warning("Proxmox journal event stream unavailable: %s", exc)
            finally:
                self._healthy.clear()
                self._process = None
            # No busy retry when journalctl is missing or exits unexpectedly.
            self._stop.wait(5.0)

    def stop(self) -> None:
        self._stop.set()
        proc = self._process
        if proc is not None and proc.poll() is None:
            proc.terminate()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
