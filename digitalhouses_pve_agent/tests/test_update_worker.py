"""Exercise the updater's backup, rollback and independent NUT preflight safely."""
import json
import runpy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "digitalhouses-pve-agent-update-runner"


def sandbox(tmp_path):
    values = runpy.run_path(str(SCRIPT), run_name="updater_under_test")
    scope = values["rollback"].__globals__
    paths = {
        "ROOT": tmp_path / "opt" / "agent",
        "STATE": tmp_path / "var",
        "CONFIG": tmp_path / "etc" / "agent.conf",
        "UNIT": tmp_path / "etc" / "agent.service",
        "UPDATE_UNIT": tmp_path / "etc" / "update.service",
        "RECOVERY_UNIT": tmp_path / "etc" / "recover.service",
        "RUNNER": tmp_path / "bin" / "runner",
        "ROOT_GUIDE": tmp_path / "root" / "guide",
        "BACKUP": tmp_path / "var" / "update-backup",
        "LOCK": tmp_path / "var" / "update.lock",
    }
    for name, path in paths.items():
        scope[name] = path
    scope["FILES"] = {
        "config": paths["CONFIG"], "service": paths["UNIT"],
        "update_unit": paths["UPDATE_UNIT"],
        "recovery_unit": paths["RECOVERY_UNIT"],
        "runner": paths["RUNNER"], "guide": paths["ROOT_GUIDE"],
    }
    return values, scope, paths


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_rollback_restores_original_runtime_units_config_and_guide(tmp_path):
    values, scope, paths = sandbox(tmp_path)
    write(paths["ROOT"] / "VERSION", "0.5.46\n")
    write(paths["ROOT"] / "app" / "main.py", "old code\n")
    write(paths["CONFIG"], "secret config\n")
    write(paths["UNIT"], "old unit\n")
    write(paths["RUNNER"], "old runner\n")
    write(paths["ROOT_GUIDE"], "old guide\n")
    calls = []
    scope["run"] = lambda cmd, **kw: calls.append(cmd)
    values["backup_files"]()
    assert (paths["BACKUP"] / "pending").exists()
    write(paths["ROOT"] / "VERSION", "0.5.47\n")
    write(paths["CONFIG"], "modified config\n")
    write(paths["UNIT"], "modified unit\n")
    write(paths["UPDATE_UNIT"], "brand new unit\n")
    values["rollback"](restart=False)
    assert (paths["ROOT"] / "VERSION").read_text().strip() == "0.5.46"
    assert (paths["ROOT"] / "app" / "main.py").read_text().strip() == "old code"
    assert paths["CONFIG"].read_text().strip() == "secret config"
    assert paths["UNIT"].read_text().strip() == "old unit"
    assert paths["RUNNER"].read_text().strip() == "old runner"
    assert paths["ROOT_GUIDE"].read_text().strip() == "old guide"
    assert not paths["UPDATE_UNIT"].exists()
    assert not (paths["BACKUP"] / "pending").exists()
    assert calls == [["systemctl", "daemon-reload"]]


def test_recovery_skips_when_no_incomplete_transaction(tmp_path):
    values, scope, paths = sandbox(tmp_path)
    assert values["recover"]() == 0
    assert not paths["BACKUP"].exists()


@pytest.mark.parametrize("raw", [
    "ups.status: OB DISCHRG\n",
    "ups.status: OL FSD\n",
    "ups.status: OL\nbattery.charger.status: discharging\n",
    "ups.status: \n",
])
def test_direct_nut_guard_blocks_unsafe_power(tmp_path, raw):
    values, scope, paths = sandbox(tmp_path)
    write(paths["STATE"] / "ups_selection.json", json.dumps({"selected_name": "ups"}))
    write(paths["CONFIG"], "[ups]\nhost = 127.0.0.1\nport = 3493\n")
    scope["run"] = lambda cmd, **kw: SimpleNamespace(stdout=raw)
    with pytest.raises(RuntimeError, match="UPS power not confirmed safe"):
        values["guard_ups"]()


def test_direct_nut_guard_allows_only_confirmed_line_power(tmp_path):
    values, scope, paths = sandbox(tmp_path)
    write(paths["STATE"] / "ups_selection.json", json.dumps({"selected_name": "ups"}))
    write(paths["CONFIG"], "[ups]\nhost = 127.0.0.1\nport = 3493\n")
    calls = []
    def fake(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(stdout="ups.status: OL\nbattery.charger.status: charging\n")
    scope["run"] = fake
    values["guard_ups"]()
    assert calls == [["upsc", "ups@127.0.0.1:3493"]]


def test_no_selected_ups_requires_no_nut_process(tmp_path):
    values, scope, paths = sandbox(tmp_path)
    scope["run"] = lambda cmd, **kw: pytest.fail("No NUT call for unconfigured host")
    values["guard_ups"]()
