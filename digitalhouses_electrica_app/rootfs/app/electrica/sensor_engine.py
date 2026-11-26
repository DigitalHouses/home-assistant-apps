"""Sensor lifecycle, ownership and timer decisions; transport is the shared Engine."""
from copy import deepcopy
from pathlib import Path
import json
import logging
import math
import os
import queue
import time
from . import sensor_rules

LOG = logging.getLogger(__name__)
CONFIRM_SECONDS = 30


def signature(state):
    """Distinguish a later manual state/parameter change from the owned ON."""
    attrs = state.get("attributes", {})
    return {"state":state.get("state"),"last_changed":state.get("last_changed"),
            "params":{k:attrs[k] for k in ("brightness","color_mode","color_temp_kelvin",
                     "rgb_color","xy_color","hs_color","effect") if k in attrs}}


class SensorEngine:
    """All public methods run under Application._mutex."""
    def __init__(self, app, path):
        self.app = app
        self.path = Path(path)
        self.states = {}
        self.ready = False
        self.generation = 0
        self.epoch = {}
        self.manual = {}
        self.pending = {}
        self.profile_changes = {}
        self.queued = set()
        self.owners = {}
        try:
            if self.path.exists():
                raw = self.path.read_bytes()
                if len(raw) > 1048576:
                    raise ValueError("timer state too large")
                from .binding_store import decode_json
                doc = decode_json(raw)
                if doc.get("schema") == 1 and isinstance(doc.get("owners"),dict):
                    self.owners = {eid:r for eid,r in doc["owners"].items()
                                   if isinstance(r,dict) and isinstance(r.get("source"),str)
                                   and isinstance(r.get("row"),dict) and isinstance(r.get("signature"),dict)
                                   and (r.get("deadline") is None or (type(r["deadline"]) in (int,float) and math.isfinite(r["deadline"])))}
        except (OSError,ValueError,TypeError,AttributeError):
            LOG.warning("Sensor timer state unavailable; do not recover ownership")
        self.saved = deepcopy(self.owners)

    def save(self):
        if self.owners == self.saved:
            return
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w",encoding="utf-8") as f:
                json.dump({"schema":1,"owners":self.owners},f,allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.path)
            self.saved = deepcopy(self.owners)
        except (OSError,ValueError):
            LOG.warning("Sensor timer persistence failed; discard timer ownership")
            self.owners.clear()
            # Do not continue automatic OFF with an uncertain durable record.
            self.ready = False

    def rows(self):
        return self.app.config.get("sensor_bindings",{})

    def row(self, source):
        row = self.rows().get(source)
        cap = self.app.sensor_catalog.get(source)
        if not row or not row["enabled"] or not cap:
            return None
        lux = {x["entity_id"] for x in cap.get("lux_sources",[])}
        if lux and row.get("lux_entity_id") not in lux:
            return None
        if row.get("lux_entity_id") and row["lux_entity_id"] not in lux:
            return None
        return row

    def state(self,eid):
        return self.states.get(eid,{}).get("state")

    def presence(self,eid):
        state = self.states.get(eid,{})
        return state.get("state") if sensor_rules.is_presence(state) else None

    def target_ok(self,eid):
        t = self.app.target_catalog.get(eid)
        route = self.app.config.get("light_routes",{}).get(eid,{})
        state = self.states.get(eid,{})
        return bool(t and not t.get("group") and t.get("integration")!="group"
                    and route.get("kind")!="group" and not state.get("attributes",{}).get("entity_id"))

    def related(self,eid):
        return [s for s,row in self.rows().items() if row["enabled"]
                   and any(a["entity_id"]==eid for a in row["assignments"])]
    def absent(self,eid):
        sources=self.related(eid)
        return bool(sources) and all(self.row(s) and self.presence(s)=="off" for s in sources)

    def absence_signature(self,eid):
        return {s:self.states.get(s,{}).get("last_changed") for s in self.related(eid)}


    def drop(self,eid):
        self.owners.pop(eid,None)
        self.pending.pop(eid,None)
        self.queued.discard(eid)
        self.profile_changes.pop(eid,None)

    def manual_control(self,ids):
        # A direct member and its known Zigbee group share manual priority.
        routes = self.app.config.get("light_routes",{})
        def members(eid):
            r = routes.get(eid,{})
            if not r:return {("ha",eid)}
            if r.get("kind")=="group":return {(r["base_topic"],m["ieee"]) for m in r["members"]}
            return {(r["base_topic"],r.get("ieee",r["friendly_name"]))}
        touched = set().union(*(members(eid) for eid in ids))
        tracked = set(self.owners)|set(self.pending)|{a["entity_id"] for r in self.rows().values() for a in r["assignments"]}
        for eid in tracked:
            if touched & members(eid):
                self.manual[eid]=self.manual.get(eid,0)+1
                self.drop(eid)
        self.save()

    def disconnect(self):
        self.ready = False
        self.generation += 1
        self.states.clear()
        self.pending.clear()
        self.profile_changes.clear()
        self.queued.clear()

    def baseline(self,states):
        self.disconnect()
        self.states = {s["entity_id"]:s for s in states if isinstance(s,dict) and isinstance(s.get("entity_id"),str)}
        self.ready = True
        # Retain a deadline only when the confirmed ON and source configuration
        # still match. Restart never synthesizes a motion event.
        for eid,r in list(self.owners.items()):
            if r["row"] != self.rows().get(r["source"]) or self.state(eid)!="on" or not r["signature"].get("last_changed") or signature(self.states[eid])!=r["signature"]:
                self.drop(eid)
            elif not self.absent(eid) or r.get("absence")!=self.absence_signature(eid):
                r["deadline"]=None
        self.reconcile(time.time())

    def enqueue(self,source,operation,ids):
        row = self.row(source)
        if not row or not ids:return False
        action = "SENSOR_ON" if operation=="on" else "SENSOR_OFF"
        token = {"generation":self.generation,"epoch":self.epoch.get(source,0),
                 "row":deepcopy(row),"manual":{eid:self.manual.get(eid,0) for eid in ids}}
        calls = sensor_rules.commands(row,set(ids),operation)
        rid = self.app.event_log.press("ha",source,"Присутствие" if operation=="on" else "Авто-OFF",ids)
        try:
            self.app._jobs.put_nowait((None,token,source,action,calls,rid))
            return True
        except queue.Full:
            self.app.event_log.finish(rid,"Очередь заполнена",ids)
            return False

    def dynamic_owner(self,eid):
        record=self.owners.get(eid)
        if not record or self.row(record["source"])!=record["row"]:return False
        return any(a["entity_id"]==eid and a.get("data",{}).get("profile")=="current"
                   for a in record["row"]["assignments"])

    def expect_profile(self,eid,data):
        if self.dynamic_owner(eid):
            self.profile_changes[eid]={"data":deepcopy(data),"until":time.time()+CONFIRM_SECONDS+data.get("transition",0)}

    def profile_matches(self,eid,state,now):
        change=self.profile_changes.get(eid)
        if not change or now>change["until"] or state.get("state")!="on":return False
        previous=self.owners[eid]["signature"]
        if state.get("last_changed")!=previous["last_changed"]:return False
        attrs=state.get("attributes",{})
        data=change["data"]
        try:
            if "brightness_pct" in data and abs(attrs["brightness"]/255*100-data["brightness_pct"])>1:return False
            if "color_temp_kelvin" in data and abs(attrs["color_temp_kelvin"]-data["color_temp_kelvin"])>50:return False
            if "rgb_color" in data and (len(attrs["rgb_color"])!=3 or any(abs(a-b)>3 for a,b in zip(attrs["rgb_color"],data["rgb_color"]))):return False
        except (KeyError,TypeError,ValueError):return False
        return True

    def changed(self,eid,state):
        old = self.states.get(eid,{})
        state = state if isinstance(state,dict) and state.get("entity_id")==eid else {}
        self.states[eid]=state
        now=time.time()
        pending=self.pending.get(eid)
        if pending and state.get("state")=="on" and old.get("state")=="off" and now<=pending["expires"] and pending["row"]==self.row(pending["source"]):
            self.pending.pop(eid,None)
            self.owners[eid]={"source":pending["source"],"row":pending["row"],
                              "signature":signature(state),"deadline":None}
        elif pending and state.get("state") not in ("on","off"):
            self.pending.pop(eid,None)
        elif eid in self.owners and signature(state)!=self.owners[eid]["signature"]:
            if self.profile_matches(eid,state,now):
                self.owners[eid]["signature"]=signature(state)
                self.profile_changes.pop(eid,None)
            else:
                self.drop(eid)
        if eid in self.rows():
            before = old.get("state") if sensor_rules.is_presence(old) else None
            after = self.presence(eid)
            if before != after:
                self.epoch[eid]=self.epoch.get(eid,0)+1
                row=self.row(eid)
                if self.ready and row and before=="off" and after=="on" and not self.app.globals["maintenance_mode"]:
                    ids=[a["entity_id"] for a in row["assignments"] if self.target_ok(a["entity_id"])
                         and self.state(a["entity_id"])=="off"
                         and not self.app.event_log.active_target(a["entity_id"])]
                    if sensor_rules.lux_allows(row,self.states):
                        self.enqueue(eid,"on",ids)
                    elif ids:
                        rid=self.app.event_log.press("ha",eid,"Присутствие",ids)
                        self.app.event_log.finish(rid,"Lux выше порога или недоступен",ids)
        self.reconcile(now)

    def reconcile(self,now):
        for eid,r in list(self.owners.items()):
            row=self.row(r["source"])
            if not row or row != r["row"] or self.state(eid)!="on" or not self.target_ok(eid):
                self.drop(eid)
                continue
            a=next((a for a in row["assignments"] if a["entity_id"]==eid),{})
            delay=a.get("off_delay_seconds")
            if delay is None:
                r["deadline"]=None
                r.pop("absence",None)
                if not self.dynamic_owner(eid):self.drop(eid)
            elif self.app.globals["maintenance_mode"] or not self.absent(eid):
                r["deadline"]=None
                r.pop("absence",None)
                self.queued.discard(eid)
            elif r["deadline"] is None:
                r["deadline"]=now+delay
                r["absence"]=self.absence_signature(eid)
        self.save()

    def live_owned(self,eid,state):
        record=self.owners.get(eid)
        return bool(record and isinstance(state,dict) and state.get("entity_id")==eid
                    and signature(state)==record["signature"])

    def allowed(self,source,action,token,eid,rid=None):
        if (not self.ready or self.app.globals["maintenance_mode"] or token["generation"]!=self.generation
                or token["row"]!=self.row(source) or token["manual"].get(eid)!=self.manual.get(eid,0)
                or not self.target_ok(eid)):
            return False
        if action=="SENSOR_ON":
            if rid is not None and self.app.event_log.active_target(eid,exclude=rid):return False
            return self.presence(source)=="on" and token["epoch"]==self.epoch.get(source,0) and self.state(eid)=="off" and eid not in self.pending
        r=self.owners.get(eid)
        return bool(r and r["source"]==source and r["deadline"] is not None
                    and r["deadline"]<=time.time() and self.absent(eid) and self.state(eid)=="on" and eid not in self.profile_changes
                    and signature(self.states[eid])==r["signature"] and r.get("absence")==self.absence_signature(eid))

    def dispatched(self,source,action,token,eid,desired):
        if action=="SENSOR_OFF" or desired!="on" or not self.ready or token["generation"]!=self.generation:
            self.drop(eid)
        elif token["manual"].get(eid)==self.manual.get(eid,0) and token["row"]==self.row(source):
            a=next((a for a in token["row"]["assignments"] if a["entity_id"]==eid),{})
            if a.get("off_delay_seconds") is not None or a.get("data",{}).get("profile")=="current":
                if self.state(eid)=="on":
                    self.owners[eid]={"source":source,"row":deepcopy(token["row"]),
                                      "signature":signature(self.states[eid]),"deadline":None}
                else:
                    self.pending[eid]={"source":source,"row":deepcopy(token["row"]),"expires":time.time()+CONFIRM_SECONDS}
        self.reconcile(time.time())

    def tick(self):
        if not self.ready:return
        now=time.time()
        for eid,p in list(self.pending.items()):
            if p["expires"]<=now:self.pending.pop(eid,None)
        for eid,change in list(self.profile_changes.items()):
            if change["until"]<=now:self.profile_changes.pop(eid,None)
        self.reconcile(now)
        if self.app.globals["maintenance_mode"]:return
        for eid,r in list(self.owners.items()):
            if r["deadline"] is not None and r["deadline"]<=now and eid not in self.queued and eid not in self.profile_changes:
                if self.enqueue(r["source"],"off",[eid]):self.queued.add(eid)

    def finished(self,action,ids):
        if action=="SENSOR_OFF":
            for eid in ids:
                if eid in self.queued:
                    self.queued.discard(eid)
                    if self.absent(eid) and eid not in self.profile_changes:self.drop(eid)
            self.save()
