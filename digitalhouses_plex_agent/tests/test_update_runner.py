"""Transactional updater regression tests without touching system services."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest


def runner():
    path = Path(__file__).resolve().parents[1] / "bin/digitalhouses-plex-agent-update-runner"
    loader = importlib.machinery.SourceFileLoader("plex_agent_update_runner_under_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_root_updater_requires_matching_published_stable_release(tmp_path, monkeypatch):
    module = runner()
    root = tmp_path / "app"
    root.mkdir()
    (root / "VERSION").write_text("0.7.2\n", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", root)

    def release(**overrides):
        item = {
            "tag_name": "digitalhouses_plex_agent-v0.8.0",
            "draft": False, "prerelease": False, "published_at": "2026-10-12",
        }
        item.update(overrides)
        return item

    state = {"payload": release()}
    monkeypatch.setattr(module.urllib.request, "urlopen",
                        lambda request, timeout: io.BytesIO(
                            json.dumps(state["payload"]).encode()))
    module.verify_release("digitalhouses_plex_agent-v0.8.0", "0.8.0")

    for invalid in (
        release(draft=True),
        release(prerelease=True),
        release(published_at=None),
        release(tag_name="digitalhouses_pve_agent-v0.8.0"),
    ):
        state["payload"] = invalid
        with pytest.raises(RuntimeError):
            module.verify_release("digitalhouses_plex_agent-v0.8.0", "0.8.0")

    state["payload"] = release()
    with pytest.raises(RuntimeError):
        module.verify_release("digitalhouses_plex_agent-v0.7.2", "0.7.2")
    with pytest.raises(RuntimeError):
        module.verify_release("digitalhouses_plex_agent-v0.8.0", "0.8.1")


def test_transactional_rollback_restores_application_and_config(tmp_path, monkeypatch):
    module = runner()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "VERSION").write_text("0.8.0\n")
    conf = tmp_path / "agent.conf"
    conf.write_text("new")
    private = tmp_path / "private"
    backup = private / "update-backup"
    old_app = backup / "app"
    old_app.mkdir(parents=True)
    (old_app / "VERSION").write_text("0.7.2\n")
    (backup / "config").write_text("old")
    (backup / "manifest.json").write_text(json.dumps({"files": ["config"]}))
    (backup / "pending").write_text("{}")

    monkeypatch.setattr(module, "ROOT", runtime)
    monkeypatch.setattr(module, "PRIVATE", private)
    monkeypatch.setattr(module, "BACKUP", backup)
    monkeypatch.setattr(module, "FILES", {"config": conf})
    calls = []
    monkeypatch.setattr(module, "run", lambda argv, **kwargs: calls.append(argv))
    module.rollback(restart=False)

    assert (runtime / "VERSION").read_text().strip() == "0.7.2"
    assert conf.read_text() == "old"
    assert not (backup / "pending").exists()
    assert calls == [["systemctl", "daemon-reload"]]


def test_update_requires_exact_source_installer_and_recovery_unit():
    root = Path(__file__).resolve().parents[1]
    installer = (root / "install.sh").read_text(encoding="utf-8")
    unit = (root / "systemd/digitalhouses_plex_agent.service").read_text()
    runner_source = (root / "bin/digitalhouses-plex-agent-update-runner").read_text()
    assert 'DIGITALHOUSES_SOURCE_REF' in runner_source
    assert "verify_release(tag, version)" in runner_source
    assert "backup_files()" in runner_source
    assert "rollback(restart=True)" in runner_source
    assert "PRIVATE / \"update-backup\"" in runner_source
    assert 'systemctl enable --now "${UPDATE_PATH_NAME}"' in installer
    assert "Requires=digitalhouses_plex_agent-update-recover.service" in unit
    assert "After=digitalhouses_plex_agent-update-recover.service" in unit
    assert "systemctl restart plexmediaserver" not in runner_source
