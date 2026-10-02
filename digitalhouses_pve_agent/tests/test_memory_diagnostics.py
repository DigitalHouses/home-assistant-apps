from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone

from app.memory_diagnostics import MemoryDiagnostics
from app.runtime_settings import RuntimeSettings
from app.state_store import StateStore


def _psi(some: int, full: int) -> str:
    return (
        f"some avg10=0.00 avg60=0.00 avg300=0.00 total={some}\n"
        f"full avg10=0.00 avg60=0.00 avg300=0.00 total={full}\n"
    )


def _guest():
    return {"lxcs": {"7000": {"name": "stats", "status": "running"}}, "vms": {}}


def _fixture(tmp_path, *, journal=None):
    proc_root = tmp_path / "proc"
    group_root = tmp_path / "cgroup"
    (proc_root / "pressure").mkdir(parents=True)
    group = group_root / "lxc.payload.7000"
    group.mkdir(parents=True)
    (proc_root / "pressure" / "memory").write_text(_psi(0, 0))
    (group / "memory.pressure").write_text(_psi(0, 0))
    (group / "memory.events").write_text("oom 0\noom_kill 0\n")

    def runner(*args, **kwargs):
        entries = [] if journal is None else journal
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="\n".join(json.dumps(x) for x in entries),
            stderr="",
        )

    monitor = MemoryDiagnostics(
        StateStore(tmp_path / "memory.json"),
        proc_root=proc_root, cgroup_root=group_root, journal_run=runner,
    )
    return monitor, proc_root, group



def test_kernel_journal_epoch_arguments_work_with_proxmox_journalctl(tmp_path):
    """Proxmox journalctl rejects datetime.isoformat() with timezone/micros."""
    proc_root = tmp_path / "proc"
    group_root = tmp_path / "cgroup"
    (proc_root / "pressure").mkdir(parents=True)
    (proc_root / "pressure" / "memory").write_text(_psi(0, 0))
    captured = []

    def journalctl(args, **kwargs):
        captured.append(args)
        since = args[args.index("--since") + 1]
        until = args[args.index("--until") + 1]
        # Simulate the real host's date-parser failure for ISO-8601.
        if not since.startswith("@") or not until.startswith("@"):
            return subprocess.CompletedProcess(args, 1, "", "Failed to parse timestamp")
        return subprocess.CompletedProcess(args, 0, "", "")

    monitor = MemoryDiagnostics(
        StateStore(tmp_path / "memory.json"), proc_root=proc_root,
        cgroup_root=group_root, journal_run=journalctl,
    )
    local = datetime(2026, 10, 3, 1, 51, 50, tzinfo=timezone(timedelta(hours=5)))
    result = monitor.scan(local, {"lxcs": {}, "vms": {}})
    assert result["journal_status"] == "ok"
    assert captured
    assert captured[0][captured[0].index("--since") + 1] == f"@{int(local.timestamp()) - 605}"
    assert captured[0][captured[0].index("--until") + 1] == f"@{int(local.timestamp())}"

def test_psi_full_and_lxc_oom_kill_are_detected_without_repeating(tmp_path):
    monitor, proc_root, group = _fixture(tmp_path)
    start = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    first = monitor.scan(start, _guest())
    assert first["count"] == 0
    assert first["journal_status"] == "ok"
    assert first["pressure_status"] == "ok"

    (group / "memory.pressure").write_text(_psi(300_000, 110_000))
    (group / "memory.events").write_text("oom 1\noom_kill 1\n")
    second = monitor.scan(start + timedelta(minutes=10), _guest())
    assert second["count"] == 1  # OOM is never thresholded.
    assert second["events"][0]["level"] == "red"
    assert any(
        x["guest"] == "7000" and x["full_us"] == 110_000
        for x in monitor.psi_samples
    )

    (group / "memory.pressure").write_text(_psi(31_400_000, 31_110_000))
    third = monitor.scan(start + timedelta(minutes=20), _guest())
    assert third["count"] == 2
    psi = next(e for e in third["events"] if e["kind"] == "pressure")
    assert psi["amount"] == 31_110_000  # Include preceding 0.11s.
    assert psi["policy"] == "full-5pct-v1"

    (group / "memory.pressure").write_text(_psi(31_500_000, 31_200_000))
    continuing = monitor.scan(start + timedelta(minutes=30), _guest())
    assert continuing["count"] == 2
    assert next(e for e in continuing["events"] if e["kind"] == "pressure")["amount"] == 31_200_000

    monitor.scan(start + timedelta(minutes=40), _guest())  # No FULL -> close.
    (group / "memory.pressure").write_text(_psi(67_000_000, 66_200_000))
    later = monitor.scan(start + timedelta(minutes=50), _guest())
    assert later["count"] == 3  # New episode after quiet interval


def test_five_percent_exact_boundary_and_actual_hourly_period(tmp_path):
    monitor, proc_root, _group = _fixture(tmp_path)
    t = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    monitor.scan(t, {"lxcs": {}, "vms": {}})

    # 179 seconds in 60 minutes = 4.97%, no public incident.
    (proc_root / "pressure" / "memory").write_text(_psi(179_000_000, 179_000_000))
    first = monitor.scan(t + timedelta(hours=1), {"lxcs": {}, "vms": {}})
    assert first["count"] == 0
    assert monitor.psi_samples[-1]["full_us"] == 179_000_000
    assert monitor.psi_samples[-1]["elapsed_us"] == 3_600_000_000

    # Another 180 seconds in 60 minutes is precisely 5%. One episode
    # includes both contiguous intervals; no 30-second fixed threshold.
    (proc_root / "pressure" / "memory").write_text(_psi(359_000_000, 359_000_000))
    second = monitor.scan(t + timedelta(hours=2), {"lxcs": {}, "vms": {}})
    assert second["count"] == 1
    assert second["events"][0]["amount"] == 359_000_000

    # An interval with only 1 microsecond stays merged into the open episode.
    (proc_root / "pressure" / "memory").write_text(_psi(359_000_001, 359_000_001))
    third = monitor.scan(t + timedelta(hours=3), {"lxcs": {}, "vms": {}})
    assert third["count"] == 1
    assert third["events"][0]["amount"] == 359_000_001


def test_ten_minute_threshold_requires_thirty_seconds(tmp_path):
    monitor, proc_root, _group = _fixture(tmp_path)
    t = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    no_lxcs = {"lxcs": {}, "vms": {}}
    monitor.scan(t, no_lxcs)

    # Tiny nonzero FULL and exactly 29.99 seconds must remain local-only.
    (proc_root / "pressure" / "memory").write_text(
        _psi(29_990_000, 29_990_000)
    )
    first = monitor.scan(t + timedelta(minutes=10), no_lxcs)
    assert first["count"] == 0

    # One subsequent 10-minute interval at precisely 30 seconds is enough.
    (proc_root / "pressure" / "memory").write_text(
        _psi(59_990_000, 59_990_000)
    )
    second = monitor.scan(t + timedelta(minutes=20), no_lxcs)
    assert second["count"] == 1
    assert second["events"][0]["amount"] == 59_990_000
    assert [s["full_us"] for s in monitor.psi_samples] == [
        29_990_000, 30_000_000,
    ]


def test_zero_and_microsecond_samples_preserved_without_ha_noise(tmp_path):
    monitor, proc_root, group = _fixture(tmp_path)
    t = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    monitor.scan(t, _guest())
    (proc_root / "pressure" / "memory").write_text(_psi(12, 1))
    (group / "memory.pressure").write_text(_psi(10, 1))
    monitor.scan(t + timedelta(minutes=10), _guest())
    monitor.scan(t + timedelta(minutes=20), _guest())
    assert monitor.payload()["count"] == 0
    assert sorted(x["full_us"] for x in monitor.psi_samples) == [0, 0, 1, 1]
    assert len(monitor.psi_samples) == 4

    restored = MemoryDiagnostics(
        StateStore(tmp_path / "memory.json"),
        proc_root=proc_root, cgroup_root=tmp_path / "cgroup",
        journal_run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""),
    )
    assert restored.psi_samples == monitor.psi_samples
    assert restored.payload()["count"] == 0


def test_pending_short_pressure_survives_restart_and_legacy_is_local(tmp_path):
    monitor, proc_root, _group = _fixture(tmp_path)
    t = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    no_lxcs = {"lxcs": {}, "vms": {}}
    monitor.scan(t, no_lxcs)
    # Pre-0.5.51 pressure entries remain in local event history, not in HA.
    legacy = monitor._event(
        at=t, guest="PVE", kind="pressure", level="yellow",
        description="Memory Pressure FULL · задержки 0.01 с", amount=10_000,
    )
    monitor.baselines["PVE"]["pressure_event"] = legacy["id"]
    (proc_root / "pressure" / "memory").write_text(_psi(1_000_000, 1_000_000))
    monitor.scan(t + timedelta(minutes=10), no_lxcs)
    assert monitor.payload()["count"] == 0

    restarted = MemoryDiagnostics(
        StateStore(tmp_path / "memory.json"),
        proc_root=proc_root, cgroup_root=tmp_path / "cgroup",
        journal_run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""),
    )
    (proc_root / "pressure" / "memory").write_text(_psi(32_000_000, 32_000_000))
    result = restarted.scan(t + timedelta(minutes=20), no_lxcs)
    assert result["count"] == 1
    assert result["events"][0]["amount"] == 32_000_000
    assert len(restarted.events) == 2  # Legacy record retained locally.
    assert restarted.events[0]["policy"] == "full-5pct-v1"


def test_psi_sample_retention_30_days_and_baseline_reset(tmp_path):
    monitor, proc_root, _group = _fixture(tmp_path)
    t = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    no_lxcs = {"lxcs": {}, "vms": {}}
    monitor.scan(t, no_lxcs)
    (proc_root / "pressure" / "memory").write_text(_psi(0, 0))
    monitor.scan(t + timedelta(minutes=10), no_lxcs)
    assert len(monitor.psi_samples) == 1

    # After 31 days the old window is pruned, not kept indefinitely.
    monitor.scan(t + timedelta(days=31), no_lxcs)
    assert len(monitor.psi_samples) == 1
    assert monitor.psi_samples[0]["at"] == (t + timedelta(days=31)).isoformat()
    # A counter reset must not produce a sample with negative differences.
    (proc_root / "pressure" / "memory").write_text(_psi(100_000, 100_000))
    monitor.scan(t + timedelta(days=31, minutes=10), no_lxcs)
    before = len(monitor.psi_samples)
    (proc_root / "pressure" / "memory").write_text(_psi(100, 100))
    monitor.scan(t + timedelta(days=31, minutes=20), no_lxcs)
    assert len(monitor.psi_samples) == before
    assert monitor.payload()["count"] == 0


def test_counter_reset_is_new_baseline_not_new_incident(tmp_path):
    monitor, _proc, group = _fixture(tmp_path)
    t = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    monitor.scan(t, _guest())
    (group / "memory.pressure").write_text(_psi(500_000, 200_000))
    (group / "memory.events").write_text("oom 3\noom_kill 2\n")
    monitor.scan(t + timedelta(minutes=10), _guest())
    before = len(monitor.events)
    (group / "memory.pressure").write_text(_psi(5_000, 100))
    (group / "memory.events").write_text("oom 0\noom_kill 0\n")
    monitor.scan(t + timedelta(minutes=20), _guest())
    assert len(monitor.events) == before


def test_journal_oom_header_and_killed_process_make_one_red_event(tmp_path):
    t = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    entries = [
        {
            "__CURSOR": "a",
            "__REALTIME_TIMESTAMP": str(int(t.timestamp() * 1_000_000)),
            "MESSAGE": "oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=/lxc.payload.7000",
        },
        {
            "__CURSOR": "b",
            "__REALTIME_TIMESTAMP": str(int(t.timestamp() * 1_000_000) + 5),
            "MESSAGE": "Memory cgroup out of memory: Killed process 123 (postgres) in /lxc.payload.7000",
        },
    ]
    monitor, _proc, group = _fixture(tmp_path, journal=entries)
    monitor.scan(t, _guest())
    assert len(monitor.events) == 1
    assert monitor.events[0]["level"] == "red"
    assert "postgres" in monitor.events[0]["description"]
    monitor.scan(t + timedelta(minutes=10), _guest())
    assert len(monitor.events) == 1


def test_history_survives_restart_and_drops_older_than_30_days(tmp_path):
    monitor, _proc, _group = _fixture(tmp_path)
    t = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    monitor.scan(t, _guest())
    monitor._event(
        at=t - timedelta(days=31), guest="7000", kind="oom",
        level="orange", description="old",
    )
    monitor._event(
        at=t - timedelta(days=1), guest="PVE", kind="oom",
        level="red", description="recent",
    )
    monitor.scan(t + timedelta(minutes=10), _guest())
    assert [e["description"] for e in monitor.events] == ["recent"]
    restored = MemoryDiagnostics(
        StateStore(tmp_path / "memory.json"),
        proc_root=tmp_path / "proc", cgroup_root=tmp_path / "cgroup",
        journal_run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""),
    )
    assert restored.payload()["count"] == 1


def test_interval_parameter_is_validated_and_defaults_to_ten_minutes():
    settings = RuntimeSettings()
    assert settings.get("memory_check_interval") == 10
    assert settings.apply("memory_check_interval", "60") == 60


def test_host_reboot_resets_all_cgroup_and_pressure_baselines(tmp_path):
    monitor, proc_root, group = _fixture(tmp_path)
    boot_file = proc_root / "sys/kernel/random/boot_id"
    boot_file.parent.mkdir(parents=True)
    boot_file.write_text("boot-A")
    t = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    monitor.scan(t, _guest())
    (group / "memory.pressure").write_text(_psi(1200, 1000))
    (group / "memory.events").write_text("oom 2\noom_kill 1\n")
    monitor.scan(t + timedelta(minutes=10), _guest())
    before = len(monitor.events)
    boot_file.write_text("boot-B")
    # Even when totals exceed the values from the previous boot, a new boot
    # must establish a baseline instead of fabricating another incident.
    (group / "memory.pressure").write_text(_psi(9000, 8000))
    (group / "memory.events").write_text("oom 8\noom_kill 5\n")
    monitor.scan(t + timedelta(minutes=20), _guest())
    assert len(monitor.events) == before


def test_kernel_killed_process_without_cgroup_uses_unambiguous_oom_header(tmp_path):
    t = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    entries = [
        {
            "__CURSOR": "oom-header",
            "__REALTIME_TIMESTAMP": str(int(t.timestamp() * 1_000_000)),
            "MESSAGE": "oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=/lxc.payload.7000",
        },
        {
            "__CURSOR": "oom-kill",
            "__REALTIME_TIMESTAMP": str(int(t.timestamp() * 1_000_000) + 300_000),
            "MESSAGE": "Out of memory: Killed process 123 (postgres) total-vm:200000kB",
        },
    ]
    monitor, _, _ = _fixture(tmp_path, journal=entries)
    monitor.scan(t + timedelta(seconds=1), _guest())
    assert len(monitor.events) == 1
    assert monitor.events[0]["guest"] == "7000"
    assert monitor.events[0]["level"] == "red"
