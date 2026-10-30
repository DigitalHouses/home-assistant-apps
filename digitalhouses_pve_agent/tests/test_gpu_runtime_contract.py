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


def test_gpu_collector_does_not_poll_guest_or_host_gpu_engines(tmp_path, monkeypatch):
    from app.collectors.gpu import GpuOwner
    from app.production_guest import GuestAwareProductionCollectors
    from app.state_store import StateStore
    import app.production as production

    class Topology:
        def gpu_catalog_text(self):
            return (
                "0000:00:02.0 VGA compatible controller [0300]: "
                "Intel Corporation Alder Lake-N [UHD Graphics] [8086:46d1]\n"
                "    Kernel driver in use: vfio-pci\n"
            )

        def gpu_owners(self):
            return {"0000:00:02.0": GpuOwner(
                connection="passthrough_pci", source_type="vm",
                source_id="2238", source_name="Media Server", source_status="running",
            )}

        def guest_exec(self, *args, **kwargs):
            raise AssertionError("QGA GPU engine probing must be removed")

    def no_subprocess(*args, **kwargs):
        raise AssertionError("intel_gpu_top must never run in PVE Agent")

    monkeypatch.setattr(production, "_run", no_subprocess)
    collector = GuestAwareProductionCollectors(
        node_name="PVE", disk_state_store=StateStore(tmp_path / "disk.json"),
        topology=Topology(), sys_root=tmp_path / "sys", pve_root=tmp_path / "pve",
    )
    sample = collector.gpu()
    gpu = sample.data["pci_0000_00_02_0"]
    assert gpu["owner"] == "VM 2238"
    assert "transcoding_load_percent" not in gpu
    assert "video_busy_percent" not in gpu
    assert "transcoding" not in sample.metrics

def test_pve_dashboard_uses_only_optional_plex_entities_for_transcoding():
    from pathlib import Path
    app = Path(__file__).resolve().parents[1]
    dashboard = (app / "examples/dh_pve_agent_dashboard_ru.yaml").read_text()
    assert "binary_sensor.dh_plex_agent_video_transcoding_active" in dashboard
    assert "binary_sensor.dh_plex_agent_audio_transcoding_active" in dashboard
    assert "binary_sensor.dh_plex_agent_server_running" in dashboard
    assert "states(video) in ['on', 'off']" in dashboard
    assert "states(audio) in ['on', 'off']" in dashboard
    assert "video_decision" not in dashboard and "audio_decision" not in dashboard
