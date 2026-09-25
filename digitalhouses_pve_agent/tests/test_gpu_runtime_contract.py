from app.production_guest import GuestAwareProductionCollectors
from app.state_store import StateStore


def test_guest_aware_gpu_without_topology_does_not_fallback_to_subprocess_polling(tmp_path, monkeypatch):
    import app.production as production

    calls = []

    def forbidden(argv, *, timeout=20.0, check=True):
        calls.append(tuple(argv))
        raise AssertionError(f"forbidden legacy GPU polling: {argv}")

    monkeypatch.setattr(production, "_run", forbidden)
    collector = GuestAwareProductionCollectors(
        node_name="PVE",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        topology=None,
        sys_root=tmp_path / "sys",
        pve_root=tmp_path / "pve",
    )

    sample = collector.gpu()

    assert sample.data == {}
    assert sample.metrics == {}
    assert calls == []
