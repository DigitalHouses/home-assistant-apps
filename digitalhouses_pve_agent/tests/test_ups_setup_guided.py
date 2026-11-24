from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import AppConfig, GeneralConfig, MqttConfig, UpsConfig
from app.discovery import build_discovery_payload
from app.identity import HostIdentity
from app.mqtt_bridge import MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics
from app.ups_policy_preflight import PreflightCheck, UpsPolicyPreflight
from app.ups_setup import (
    VALID_STAGES, _managed_source, setup_snapshot, usb_ups_devices,
)
from app.ups_setup_apply import UpsSetupError, execute, live_ol, _backup_and_write, _restore_changes


def _config(host="127.0.0.1"):
    return AppConfig(
        general=GeneralConfig(instance_id="",node_name="PVE",log_level="info"),
        mqtt=MqttConfig(host="mqtt",port=1883,username="",password="",
                        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
                        discovery_prefix="homeassistant",keepalive_seconds=60),
        ups=UpsConfig(host=host),
    )


def _usb(sysfs: Path, **overrides):
    item=sysfs/"1-2"
    item.mkdir(parents=True,exist_ok=True)
    values={"idVendor":"0764","idProduct":"0501","manufacturer":"CyberPower",
            "product":"CP1500","serial":"XYZ","busnum":"1","devnum":"4"}
    values.update(overrides)
    for k,v in values.items():
        (item/k).write_text(v+"\n")
    return item


def _runner(command, **kwargs):
    if command[:2]==["systemctl","is-active"]:
        service=command[2]
        state="active" if service in {"nut-server.service","nut-driver@ups.service"} else "inactive"
        return SimpleNamespace(returncode=0 if state=="active" else 3,
                               stdout=state+"\n",stderr="")
    raise AssertionError(command)


def _status(tmp_path, *, host="127.0.0.1", installed=True, healthy=True):
    sysfs=tmp_path/"sysfs";sysfs.mkdir();_usb(sysfs)
    nut=tmp_path/"nut";nut.mkdir()
    (nut/"ups.conf").write_text("[ups]\n    driver = usbhid-ups\n    port = auto\n")
    status = setup_snapshot(
        _config(host),state_dir=tmp_path,sysfs_root=sysfs,nut_dir=nut,
        which=(lambda name: "/usr/bin/"+name if installed else None),
        runner=_runner,
        ups_reader=lambda config: SimpleNamespace(
            driver_name="usbhid-ups",line_power=healthy),
        preflight=lambda config: UpsPolicyPreflight(
            "Ready" if healthy else "Blocked",healthy,
            tuple(PreflightCheck(k,healthy,k) for k in (
                "nut_primary_role","primary_role","credentials_consistent",
                "monitor_active","shutdown_enabled","helper_secure")),
            100),
    )
    return status


def test_usb_scan_exposes_address_and_identity(tmp_path):
    usb=tmp_path/"sys";usb.mkdir()
    _usb(usb)
    assert usb_ups_devices(usb)==[{
        "vendor":"CyberPower","model":"CP1500","serial":"XYZ",
        "vid":"0764","pid":"0501","bus":"001","device":"004","sysfs":"1-2",
    }]


def test_unrelated_usb_device_is_not_confused_with_ups(tmp_path):
    root=tmp_path/"usb";root.mkdir()
    _usb(root,idVendor="1234",idProduct="5678",manufacturer="Generic",product="Keyboard")
    assert usb_ups_devices(root)==[]


def test_before_nut_install_shows_one_install_step(tmp_path):
    status=_status(tmp_path,installed=False)
    assert status["state"]=="blocked"
    assert status["usb"]["selected"]["bus"]=="001"
    assert status["nut"]["installed"] is False
    assert status["actions"]["install"] is True
    assert all(not flag for action,flag in status["actions"].items() if action!="install")


def test_ready_uses_existing_preflight_and_shows_no_buttons(tmp_path):
    status=_status(tmp_path)
    assert status["ready"]
    assert status["actions"]=={action:False for action in VALID_STAGES}


def test_external_snmp_is_read_only_and_does_not_claim_usb_setup(tmp_path):
    status=_status(tmp_path,host="192.168.11.10")
    assert status["transport"]=="external"
    assert not any(status["actions"].values())


def test_existing_snmp_driver_is_read_only_even_on_local_listener(tmp_path):
    nut=tmp_path/"nut";nut.mkdir()
    (nut/"ups.conf").write_text("[ups]\n driver = snmp-ups\n port = 192.168.11.10\n")
    assert not _managed_source(_config(),nut)


@pytest.mark.parametrize("raw,expected",[
    ("OL",True),("OL CHRG",True),("OB",False),("OL FSD",False),
    ("OL LB",False),("OL OVER",False),("OL DISCHRG",False),("",False),
])
def test_live_power_safety_never_accepts_bad_ups_status(raw,expected):
    runner=lambda command,**kwargs: SimpleNamespace(stdout=raw,returncode=0)
    assert live_ol("ups",runner=runner) is expected


def test_mqtt_setup_commands_are_fixed_and_driver_selection_validated():
    config=_config()
    identity=HostIdentity(machine_id="0123456789abcdef0123456789abcdef",
                          instance_id="pve",hostname="pve",node_name="PVE")
    topics=build_topics(config.mqtt,identity)
    events=MqttEvents(topics,RuntimeSettings())
    for action in VALID_STAGES:
        assert events.handle_message(f"{topics.base}/ups/setup/{action}",b"PRESS")
        assert events.ups_setup_requests.get_nowait()==action
    assert not events.handle_message(f"{topics.base}/ups/setup/fake",b"PRESS")
    assert not events.handle_message(f"{topics.base}/ups/setup/activate",b"bash")
    assert events.ups_setup_requests.empty()
    assert not events.handle_message(f"{topics.base}/ups/setup/driver/set",b"../../../bin/sh")
    assert events.handle_message(f"{topics.base}/ups/setup/driver/set",b"usbhid-ups")
    assert events.ups_setup_driver_updates.get_nowait()=="usbhid-ups"


def test_ups_setup_discovery_available_before_any_nut_selection():
    config=_config()
    identity=HostIdentity(machine_id="0123456789abcdef0123456789abcdef",
                          instance_id="pve",hostname="pve",node_name="PVE")
    components=build_discovery_payload(config,identity,version="test")["components"]
    assert components["ups_setup"]["default_entity_id"]=="sensor.dh_pve_agent_ups_setup"
    assert components["ups_setup_driver_select"]["platform"]=="select"
    for stage in VALID_STAGES:
        button=components["ups_setup_"+stage]
        assert button["platform"]=="button"
        assert button["payload_press"]=="PRESS"
        assert button["command_topic"].endswith("/ups/setup/"+stage)


def test_unknown_stage_is_refused_without_touching_host(tmp_path):
    with pytest.raises(UpsSetupError,match="Неизвестное"):
        execute("shutdown",state_dir=tmp_path,nut_dir=tmp_path,app_conf=tmp_path/"app")


def test_installer_refuses_to_provision_without_usb(monkeypatch,tmp_path):
    monkeypatch.setattr("app.ups_setup_apply.os.geteuid",lambda:0)
    sysfs=tmp_path/"sys";sysfs.mkdir()
    with pytest.raises(UpsSetupError,match="USB UPS"):
        execute("install",state_dir=tmp_path,nut_dir=tmp_path,
                app_conf=tmp_path/"app",sysfs_root=sysfs)


def test_backup_can_restore_original_files_on_operation_failure(tmp_path,monkeypatch):
    from app import ups_setup_apply as apply
    monkeypatch.setattr(apply.os,"fchown",lambda *args:None)
    path=tmp_path/"upsmon.conf"
    path.write_text('SHUTDOWNCMD "/bin/true"\n')
    path.chmod(0o600)
    restore=_backup_and_write({path:'SHUTDOWNCMD "/sbin/shutdown -h now"\n'},state_dir=tmp_path)
    assert path.read_text().find("shutdown -h now")>=0
    _restore_changes(restore)
    assert path.read_text()=='SHUTDOWNCMD "/bin/true"\n'
    assert path.stat().st_mode & 0o777==0o600
    assert any((tmp_path/"nut_setup_backups").iterdir())


def test_commissioning_service_is_separate_from_protected_monitor():
    package=Path(__file__).resolve().parents[1]
    monitor=(package/"systemd/digitalhouses_pve_agent.service").read_text()
    unit=(package/"systemd/digitalhouses_pve_agent-ups-setup@.service").read_text()
    assert "ProtectSystem=full" in monitor
    assert "ExecStart=" in unit
    assert "ups_setup_apply %i" in unit
    assert "[Install]" not in unit



@pytest.mark.parametrize("stage,expected", [
    ("primary","UPS"),("monitor","UPS"),("activate","UPS"),
])
def test_no_provisioning_is_allowed_when_live_power_is_not_confirmed(
    monkeypatch,tmp_path,stage,expected,
):
    from app import ups_setup_apply as apply
    monkeypatch.setattr(apply.os,"geteuid",lambda:0)
    monkeypatch.setattr(apply,"usb_ups_devices",lambda root:[{"vid":"0764"}])
    monkeypatch.setattr(apply,"load_config",lambda _: _config())
    monkeypatch.setattr(apply,"_single_ups",lambda *args:"ups")
    monkeypatch.setattr(apply,"guard_restart",lambda *args,**kwargs:None)
    monkeypatch.setattr(apply.shutil,"which",lambda x:"/usr/bin/"+x)
    monkeypatch.setattr(apply,"live_ol",lambda *args,**kwargs:False)
    def forbidden(*args,**kwargs):
        raise AssertionError("no service command permitted")
    with pytest.raises(UpsSetupError,match=expected):
        execute(stage,state_dir=tmp_path,nut_dir=tmp_path,
                app_conf=tmp_path/"app",runner=forbidden)


def test_monitor_cannot_start_before_primary(monkeypatch,tmp_path):
    from app import ups_setup_apply as apply
    monkeypatch.setattr(apply.os,"geteuid",lambda:0)
    monkeypatch.setattr(apply,"usb_ups_devices",lambda root:[{"vid":"0764"}])
    monkeypatch.setattr(apply,"load_config",lambda _: _config())
    monkeypatch.setattr(apply,"_single_ups",lambda *args:"ups")
    monkeypatch.setattr(apply,"guard_restart",lambda *args,**kwargs:None)
    monkeypatch.setattr(apply.shutil,"which",lambda x:"/usr/bin/"+x)
    monkeypatch.setattr(apply,"live_ol",lambda *args,**kwargs:True)
    monkeypatch.setattr(apply,"service_status",lambda *args,**kwargs:"inactive")
    def forbidden(*args,**kwargs):
        raise AssertionError("must not start monitor without primary")
    with pytest.raises(UpsSetupError,match="PRIMARY"):
        execute("monitor",state_dir=tmp_path,nut_dir=tmp_path,
                app_conf=tmp_path/"app",runner=forbidden)


def test_activate_cannot_run_before_monitor(monkeypatch,tmp_path):
    from app import ups_setup_apply as apply
    monkeypatch.setattr(apply.os,"geteuid",lambda:0)
    monkeypatch.setattr(apply,"usb_ups_devices",lambda root:[{"vid":"0764"}])
    monkeypatch.setattr(apply,"load_config",lambda _: _config())
    monkeypatch.setattr(apply,"_single_ups",lambda *args:"ups")
    monkeypatch.setattr(apply,"guard_restart",lambda *args,**kwargs:None)
    monkeypatch.setattr(apply.shutil,"which",lambda x:"/usr/bin/"+x)
    monkeypatch.setattr(apply,"live_ol",lambda *args,**kwargs:True)
    monkeypatch.setattr(apply,"service_status",lambda *args,**kwargs:"inactive")
    def forbidden(*args,**kwargs):
        raise AssertionError("must not enable shutdown without monitor")
    with pytest.raises(UpsSetupError,match="Monitor"):
        execute("activate",state_dir=tmp_path,nut_dir=tmp_path,
                app_conf=tmp_path/"app",runner=forbidden)



def test_ups_preview_keeps_four_columns_and_full_pve_history():
    import yaml
    view = Path(__file__).resolve().parents[1] / "examples/dashboard-preview/11_pve_ups_preview_v8.yaml"
    config = yaml.safe_load(view.read_text(encoding="utf-8"))
    assert config["max_columns"] == 4
    first, second, third, fourth = [s["cards"] for s in config["sections"]]
    assert sum(card["type"] == "conditional" for card in first) == 2
    assert first[1]["heading"] == "Защита PVE (UPS)"
    assert third[0]["heading"] == "Управление"
    assert fourth[0]["heading"] == "Тесты батареи"
    assert any(c.get("heading") == "Условия аварийного выключения" for c in fourth)
    text = str(second)
    assert "История остановок PVE" in text
    assert "PVE · планируемое выключение" in text
    assert "shutdown_sequence" in text
    assert "Последний shutdown" in text
    assert "Логика аварийного отключения" not in str(config)
    assert "select.dh_pve_agent_ups_driver" in str(first)



def test_ups_preview_v9_uses_inline_per_step_controls_without_hiding_blocked_steps():
    import yaml
    root = Path(__file__).resolve().parents[1]
    examples = root / "examples" / "dashboard-preview"
    v8 = yaml.safe_load((examples / "11_pve_ups_preview_v8.yaml").read_text())
    v9 = yaml.safe_load((examples / "11_pve_ups_preview_v9.yaml").read_text())
    assert v9["path"] == "dh_pve_agent_ups_preview_v9"
    assert v9["sections"][1:] == v8["sections"][1:]
    assert [len(s["cards"]) for s in v9["sections"]] == [8, 4, 8, 10]
    problem = v9["sections"][0]["cards"][3]
    assert problem["conditions"][0]["state_not"] == "ready"
    cards = problem["card"]["cards"]
    assert cards[0]["primary"] == "Защита требует настройки"
    assert not any(c["type"] == "button" for c in cards)
    stages = ["install", "driver", "server", "primary", "monitor", "activate"]
    rows = [c for c in cards if c["type"] == "horizontal-stack"]
    assert len(rows) == len(stages)
    for row, stage in zip(rows, stages):
        assert len(row["cards"]) == 2
        action_container = row["cards"][1]
        assert action_container["type"] == "vertical-stack"
        enabled, blocked = action_container["cards"]
        assert enabled["conditions"][0]["state"] == "on"
        assert blocked["conditions"][0]["state"] == "off"
        assert enabled["conditions"][0]["entity"].endswith("_can_" + stage)
        chip = enabled["card"]["chips"][0]
        assert chip["tap_action"]["action"] == "perform-action"
        assert chip["tap_action"]["target"]["entity_id"].endswith("_setup_" + stage)
        blocked_chip = blocked["card"]["chips"][0]
        assert blocked_chip["tap_action"]["action"] == "none"
        assert "mdi:lock-outline" in blocked_chip["icon"]
    assert "Подробная диагностика" in cards[-1]["content"]
    assert "select.dh_pve_agent_ups_driver" in str(cards)
    assert "История остановок PVE" in str(v9)
    assert "PVE · планируемое выключение" in str(v9)
