from app.production import ProductionCollectors
from app.state_store import StateStore


def test_base_gpu_collector_fails_closed_without_legacy_subprocess_polling(tmp_path, monkeypatch):
    import app.production as production

    calls = []

    def forbidden_run(argv, *, timeout=20.0, check=True):
        calls.append(tuple(argv))
        raise AssertionError(f"legacy GPU polling must not run: {argv}")

    monkeypatch.setattr(production, "_run", forbidden_run)
    collector = ProductionCollectors(
        node_name="PVE",
        disk_state_store=StateStore(tmp_path / "disks.json"),
        pve_root=tmp_path / "pve",
        sys_root=tmp_path / "sys",
    )

    sample = collector.gpu()

    assert sample.data == {}
    assert sample.metrics == {}
    assert calls == []
