"""Regression tests for numeric VMID order and separate fact/plan totals."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import yaml
from jinja2 import Environment

APP = Path(__file__).resolve().parents[1]


def _views():
    for file in (APP / "dashboards/ru/11_pve_ups.yaml",
                 APP / "examples/dashboard-preview/11_pve_ups_preview_v13.yaml"):
        yield yaml.safe_load(file.read_text(encoding="utf-8"))


def _markdown(view, marker):
    for section in view["sections"]:
        for card in section["cards"]:
            if marker in card.get("content", ""):
                return card["content"]
    raise AssertionError(f"Missing {marker}")


def _history():
    def record(duration, timeout, name):
        return {"duration_seconds": duration, "timeout_seconds": timeout,
                "name": name, "assessment": "ok"}
    return [{
        "shutdown_at": "2026-11-24T21:26:30+05:00",
        "shutdown_status": "correct", "shutdown_class": "normal",
        "shutdown_reason": "shutdown", "actual_shutdown_seconds": 73,
        "planned_shutdown_seconds": 395,
        "guests": {
            "vm": {
                "2242": record(46,150,"ha-core"),
                "2243": record(10,150,"mediaserver-CORE"),
            },
            "lxc": {
                "1199": record(2,15,"ansible-legacy"),
                "1231": record(2,15,"ansible-serzhan-home"),
                "1241": record(2,15,"ansible-dh-core"),
                "1245": record(2,15,"dh-stats-CORE"),
                "1254": record(4,20,"dev"),
            }
        }
    }]


def test_history_tree_is_sorted_numerically_across_vm_and_lxc():
    env=Environment()
    env.filters["as_datetime"]=datetime.fromisoformat
    env.globals["as_datetime"]=datetime.fromisoformat
    env.filters["as_local"]=lambda dt:dt
    for view in _views():
        template=env.from_string(_markdown(view,"PVE · факт / настроено"))
        tree=template.render(
            state_attr=lambda entity,key: _history() if key=="history" else None
        )
        ids=["1199","1231","1241","1245","1254","2242","2243"]
        offsets=[tree.index(gid+"·") for gid in ids]
        assert offsets==sorted(offsets)
        assert "🟢 24.11 · 21:26 · Штатная остановка · 1:13 / 6:35" in tree
        assert "VM 2232" not in tree and "VM 2250" not in tree


class States:
    def __init__(self, attrs):
        self._attrs=attrs
        self.sensor=[SimpleNamespace(entity_id=k) for k in attrs]
    def __call__(self, entity):
        return {"sensor.dh_pve_agent_ups_guest_shutdown_budget": "300",
                "sensor.dh_pve_agent_ups_shutdown_budget": "395"}.get(entity,"unknown")


def test_shutdown_table_is_numerically_sorted_and_separates_actual_from_budget():
    entities={}
    for kind,guest_id,name,duration,limit,onboot in [
        ("lxc",1199,"ansible-legacy",2,15,False),
        ("lxc",1231,"ansible-serzhan-home",2,15,True),
        ("lxc",1241,"ansible-dh-core",2,15,True),
        ("lxc",1245,"dh-stats-CORE",2,15,True),
        ("lxc",1254,"dev",4,20,True),
        ("vm",2242,"ha-core",46,150,True),
        ("vm",2243,"mediaserver-CORE",10,150,True)
    ]:
        entities[f"sensor.dh_pve_agent_{kind}_{guest_id}_shutdown"]={
            "onboot":onboot,"guest_kind":kind,"guest_id":str(guest_id),
            "proxmox_display_name":name,
            "last_shutdown_duration_seconds":duration,
            "last_shutdown_timeout_seconds":limit,
            "last_shutdown_assessment":"ok",
            "shutdown_timeout_seconds":limit,
            "next_shutdown_timeout_seconds":limit,
            "next_shutdown_timeout_ratio":duration/limit,
            "next_shutdown_assessment":"ok"
        }
    previous={
        "actual_guest_shutdown_seconds":58,
        "all_guests_stopped_to_shutdown_seconds":15,
        "actual_shutdown_seconds":73
    }
    def attr(entity,key):
        if entity=="sensor.dh_pve_agent_previous_shutdown":
            return previous.get(key)
        return entities.get(entity,{}).get(key)
    state=States(entities)
    for view in _views():
        jinja=Environment()
        source=_markdown(view,"### ⚙️ Текущее состояние shutdown")
        table=jinja.from_string(source).render(states=state,state_attr=attr)
        ids=["1231","1241","1245","1254","2242","2243"]
        offsets=[table.index("| "+("LXC" if int(i)<2000 else "VM")+" "+i) for i in ids]
        assert offsets == sorted(offsets)
        assert "LXC 1199" not in table
        assert "**Факт · Гости: 0:58 · PVE: 0:15 · ВСЕГО: 1:13**" in table
        assert "**План · Гости: 5:00 · PVE: 1:35 · ВСЕГО: 6:35**" in table


def test_missing_actual_values_are_not_reported_as_zero_time():
    views=list(_views())
    for view in views:
        table=Environment().from_string(_markdown(view,"### ⚙️ Текущее состояние shutdown")).render(
            states=States({}),
            state_attr=lambda entity,key: None
        )
        assert "Факт · Нет достоверных данных" in table
