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
from .light_routes import current_route
from .mode_keeper import maintained_switch

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
        if source.startswith("key:"):
            parts=source.split(":",2)
            if len(parts)!=3:return None
            _,eid,press=parts
            sw=next((x for r in self.app.config["rooms"] for x in r["switches"] if x["entity_id"]==eid),None)
            if not sw or not sw.get("enabled") or maintained_switch(sw,self.app.globals):return None
            rule=sw.get("bindings",{}).get(press,{})
            timers=rule.get("target_timers",{})
            if not timers:return None
            return {"entity_id":source,"enabled":True,"assignments":[
                {"entity_id":target,"operation":"on","data":rule["target_data"].get(target,{}),"off_delay_seconds":delay}
                for target,delay in timers.items()],"identity":{k:sw[k] for k in ("ieee","base_topic","coordinator_ieee","logical_name","fingerprint")},
                "rule":deepcopy(rule),"keep_mode":deepcopy(sw.get("keep_mode",{}))}
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

    def group_members(self,eid):
        """One existing individual HA entity per verified Z2M member."""
        routes=self.app.config.get("light_routes",{})
        route=routes.get(eid,{})
        if route.get("kind")!="group":return None
        members=[]
        for member in route["members"]:
            ids=[key for key,r in routes.items() if r.get("kind")!="group"
                 and r.get("base_topic")==route["base_topic"]
                 and r.get("coordinator_ieee")==route["coordinator_ieee"]
                 and r.get("ieee")==member["ieee"]
                 and r.get("friendly_name")==member["friendly_name"]]
            if len(ids)!=1 or ids[0] not in self.app.target_catalog:return []
            members.append(ids[0])
        return sorted(members) if len(set(members))==len(members) else []

    def state(self,eid):
        members=self.group_members(eid)
        if members is None:return self.states.get(eid,{}).get("state")
        values={self.states.get(m,{}).get("state") for m in members}
        if not members or not values <= {"on","off"}:return None
        return next(iter(values)) if len(values)==1 else "mixed"

    def target_signature(self,eid):
        members=self.group_members(eid)
        if members is None:return signature(self.states.get(eid,{}))
        if not members:return {}
        records={m:signature(self.states.get(m,{})) for m in members}
        # Membership and identity changes invalidate ownership even after restart.
        route=self.app.config["light_routes"][eid]
        return {"state":self.state(eid),"last_changed":max(v["last_changed"] for v in records.values()) if all(isinstance(v["last_changed"],str) and v["last_changed"] for v in records.values()) else None,
                "members":records,"route":deepcopy(route)}

    def group_ready(self,eid,desired):
        members=self.group_members(eid)
        if members is None:return True
        if not members:return False
        routes=self.app.config["light_routes"]
        route=routes[eid]
        net=self.app._networks.get(route["base_topic"],{})
        if net.get("bridge_state")!="online" or not current_route(route,net):return False
        if self.app._light_availability.get((route["base_topic"],route["friendly_name"]))!="online":return False
        if (route["base_topic"],route["friendly_name"]) in self.app._light_shadows:return False
        return all(current_route(routes[m],net)
                   and self.app.observed_target_state(m,verify_route=True)==desired
                   and (routes[m]["base_topic"],routes[m]["friendly_name"]) not in self.app._light_shadows
                   for m in members)

    def presence(self,eid):
        state = self.states.get(eid,{})
        return state.get("state") if sensor_rules.is_presence(state) else None

    def target_ok(self,eid):
        t = self.app.target_catalog.get(eid)
        members=self.group_members(eid)
        if members is not None:return bool(t and members)
        state = self.states.get(eid,{})
        return bool(t and not t.get("group") and t.get("integration")!="group"
                    and not state.get("attributes",{}).get("entity_id"))

    def leaves(self,eid):
        members=self.group_members(eid)
        return set(members) if members is not None else {eid}

    def related(self,eid):
        leaves=self.leaves(eid)
        return [s for s,row in self.rows().items() if row["enabled"]
                and any(leaves & self.leaves(a["entity_id"]) for a in row["assignments"])]

    def group_overlap(self,eid):
        # Different target sets cannot simultaneously own the same lamp.
        # A group assigned to multiple sensors is fine (same exact target).
        leaves=self.leaves(eid)
        return any(a["entity_id"]!=eid and leaves & self.leaves(a["entity_id"])
                   for row in self.rows().values() if row["enabled"] for a in row["assignments"])

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
        tracked = set(self.owners)|set(self.pending)|set(ids)|{a["entity_id"] for r in self.rows().values() for a in r["assignments"]}
        tracked.update(eid for room in self.app.config["rooms"] for sw in room["switches"]
                       for rule in sw.get("bindings",{}).values() for eid in rule.get("target_timers",{}))
        tracked.update(a["entity_id"] for r in self.app.config.get("schedules",{}).values()
                       if r.get("catch_up") for a in r["assignments"])
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
            if r["row"] != self.row(r["source"]) or self.state(eid)!="on" or not r["signature"].get("last_changed") or self.target_signature(eid)!=r["signature"]:
                self.drop(eid)
            elif not r["source"].startswith("key:") and (not self.absent(eid) or r.get("absence")!=self.absence_signature(eid)):
                r["deadline"]=None
        self.reconcile(time.time())

    def key_token(self,sw,action,targets):
        source="key:"+sw["entity_id"]+":"+action
        row=self.row(source)
        if not row:return None
        return {"source":source,"row":row,"generation":self.generation,
                "manual":{eid:self.manual.get(eid,0) for eid in targets},
                "routes":{eid:deepcopy(self.app.config.get("light_routes",{}).get(eid)) for eid in targets}}

    def key_can_start(self,token,eid):
        return bool(token and self.ready and token["generation"]==self.generation
                    and token["manual"].get(eid)==self.manual.get(eid,0)
                    and token["row"]==self.row(token["source"])
                    and any(a["entity_id"]==eid for a in token["row"]["assignments"])
                    and self.target_ok(eid) and self.state(eid)=="off" and self.group_ready(eid,"off"))

    def key_dispatched(self,token,eid,desired,before):
        if not token or desired!="on" or before!="off" or not self.ready:return
        if not any(a["entity_id"]==eid for a in token["row"]["assignments"]):return
        if token["routes"].get(eid)!=self.app.config.get("light_routes",{}).get(eid) or not self.target_ok(eid):return
        # The key itself may actuate without a timer when the target is
        # not observed OFF in the event subscription. Never claim a pre-existing ON.
        if self.state(eid) not in ("off","on"):return
        self.dispatched(token["source"],"KEY_ON",token,eid,desired)

    def home_mode(self):
        return (self.app._home_profile or {}).get("mode")

    def assignment(self,row,eid):
        return next((a for a in row["assignments"] if a["entity_id"]==eid),{})

    def mode_owner(self,eid):
        record=self.owners.get(eid)
        if not record or record["source"].startswith("key:"):return None
        source=record["source"]
        row=self.row(source)
        if (not self.ready or not row or record["row"]!=row or self.presence(source)!="on"
                or self.related(eid)!=[source] or self.group_overlap(eid) or not self.target_ok(eid)
                or self.state(eid)!="on" or self.target_signature(eid)!=record["signature"]):
            return None
        a=self.assignment(row,eid)
        return (source,a) if sensor_rules.conditional(a) else None

    def mode_parameters(self,mode):
        result={}
        for eid in self.owners:
            owned=self.mode_owner(eid)
            if owned:
                _,a=owned
                if sensor_rules.mode_allows(a,mode) and ("night_data" in a or "modes" in a):
                    data=sensor_rules.mode_data(a,mode)
                    if data and eid.startswith("light."):result[eid]=deepcopy(data)
        return result

    def mode_off_allowed(self,eid,source,snapshot):
        if (self.app._home_profile is not snapshot or not self.app.globals.get("auto_day_night")
                or self.app.globals["maintenance_mode"] or eid in self.profile_changes):
            return False
        owned=self.mode_owner(eid)
        return bool(owned and owned[0]==source and not sensor_rules.mode_allows(owned[1],snapshot["mode"])
                    and self.group_ready(eid,"on"))

    def mode_transition(self,snapshot):
        count=0
        for eid,r in list(self.owners.items()):
            source=r["source"]
            owned=self.mode_owner(eid)
            if owned and sensor_rules.mode_allows(owned[1],snapshot["mode"]):
                r["mode"]=snapshot["mode"]
            if self.mode_off_allowed(eid,source,snapshot) and not self.app.event_log.active_target(eid):
                if self.enqueue(source,"off",[eid],mode_snapshot=snapshot):count+=1
        self.save()
        return count

    def enqueue(self,source,operation,ids,mode_snapshot=None):
        row = self.row(source)
        if not row or not ids:return False
        action = "SENSOR_ON" if operation=="on" else "SENSOR_OFF"
        token = {"generation":self.generation,"epoch":self.epoch.get(source,0),
                 "row":deepcopy(row),"manual":{eid:self.manual.get(eid,0) for eid in ids},
                 "routes":{eid:deepcopy(self.app.config.get("light_routes",{}).get(eid)) for eid in ids}}
        token["mode"]=self.home_mode()
        if mode_snapshot is not None:token["mode_snapshot"]=mode_snapshot
        calls = sensor_rules.commands(row,set(ids),operation,token["mode"])
        if not calls:return False
        rid = self.app.event_log.press("ha",source,"Присутствие" if operation=="on" else "День/Ночь · OFF" if mode_snapshot is not None else "Авто-OFF",ids)
        try:
            self.app._jobs.put_nowait((None,token,source,action,calls,rid))
            return True
        except queue.Full:
            self.app.event_log.finish(rid,"Очередь заполнена",ids)
            return False

    def dynamic_owner(self,eid):
        record=self.owners.get(eid)
        if not record or self.row(record["source"])!=record["row"] or (not record["source"].startswith("key:") and self.group_overlap(eid)):return False
        return any(a["entity_id"]==eid and "night_data" not in a and not ("modes" in a and sensor_rules.conditional(a))
                   and sensor_rules.mode_allows(a,self.home_mode())
                   and sensor_rules.mode_data(a,self.home_mode()).get("profile")=="current"
                   for a in record["row"]["assignments"])

    def expect_profile(self,eid,data):
        # A verified automatic parameter adjustment must not cancel an
        # existing Auto-OFF timer, even if it came from explicit Lights.
        record=self.owners.get(eid)
        if record and self.state(eid)=="on" and self.target_signature(eid)==record["signature"]:
            self.profile_changes[eid]={"data":deepcopy(data),"until":time.time()+CONFIRM_SECONDS+data.get("transition",0)}

    def profile_matches(self,eid,observed,now):
        change=self.profile_changes.get(eid)
        if not change or now>change["until"] or observed.get("state")!="on":return False
        previous=self.owners[eid]["signature"]
        data=change["data"]
        def matches(old,new,allow_unchanged=True):
            if old.get("last_changed")!=new.get("last_changed"):return False
            if allow_unchanged and old==new:return True
            attrs=new.get("params",{})
            try:
                if "brightness_pct" in data and abs(attrs["brightness"]/255*100-data["brightness_pct"])>1:return False
                if "color_temp_kelvin" in data and abs(attrs["color_temp_kelvin"]-data["color_temp_kelvin"])>50:return False
                if "rgb_color" in data and (len(attrs["rgb_color"])!=3 or any(abs(a-b)>3 for a,b in zip(attrs["rgb_color"],data["rgb_color"]))):return False
            except (KeyError,TypeError,ValueError):return False
            return True
        if "members" in previous:
            if previous.get("route")!=observed.get("route") or previous["members"].keys()!=observed.get("members",{}).keys():return False
            matched=all(matches(old,observed["members"][member]) for member,old in previous["members"].items())
            if matched and all(matches(old,observed["members"][member],False) for member,old in previous["members"].items()):
                self.profile_changes.pop(eid,None)
            return matched
        return matches(previous,observed)

    def changed(self,eid,state):
        old = self.states.get(eid,{})
        state = state if isinstance(state,dict) and state.get("entity_id")==eid else {}
        self.states[eid]=state
        now=time.time()
        # A group report alone never proves ownership. Re-evaluate the
        # individual members on each HA state event.
        affected={eid}|{target for target in set(self.owners)|set(self.pending)
                        if eid in (self.group_members(target) or [])}
        for target in affected:
            pending=self.pending.get(target)
            observed=self.target_signature(target)
            current=self.state(target)
            if pending and (pending.get("route")!=self.app.config.get("light_routes",{}).get(target)
                            or pending.get("members")!=self.group_members(target)):
                self.pending.pop(target,None)
                continue
            if pending and current=="on" and observed.get("last_changed") and now<=pending["expires"] and pending["row"]==self.row(pending["source"]):
                if target!=eid or self.group_members(target) is not None or old.get("state")=="off":
                    self.pending.pop(target,None)
                    self.owners[target]={"source":pending["source"],"row":pending["row"],
                                         "signature":observed,"deadline":None,"mode":pending.get("mode")}
            elif pending and current not in ("on","off","mixed"):
                self.pending.pop(target,None)
            elif target in self.owners and observed!=self.owners[target]["signature"]:
                if self.profile_matches(target,observed,now):
                    self.owners[target]["signature"]=observed
                    # Group members may report the new profile one at a time.
                    if self.group_members(target) is None:self.profile_changes.pop(target,None)
                else:
                    self.drop(target)
        if eid in self.rows():
            before = old.get("state") if sensor_rules.is_presence(old) else None
            after = self.presence(eid)
            if before != after:
                self.epoch[eid]=self.epoch.get(eid,0)+1
                row=self.row(eid)
                if self.ready and row and before=="off" and after=="on" and not self.app.globals["maintenance_mode"]:
                    ids=[a["entity_id"] for a in row["assignments"] if sensor_rules.mode_allows(a,self.home_mode()) and self.target_ok(a["entity_id"])
                         and self.state(a["entity_id"])=="off"
                         and not self.group_overlap(a["entity_id"])
                         and self.group_ready(a["entity_id"],"off")
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
            if not row or row != r["row"] or self.state(eid)!="on" or not self.target_ok(eid) or (not r["source"].startswith("key:") and self.group_overlap(eid)) or self.target_signature(eid)!=r["signature"]:
                self.drop(eid)
                continue
            a=next((a for a in row["assignments"] if a["entity_id"]==eid),{})
            delay=sensor_rules.mode_delay(a,r.get("mode",self.home_mode()))
            if r["source"].startswith("key:"):
                delay=a.get("off_delay_seconds")
                if delay is None:self.drop(eid)
                elif r["deadline"] is None:r["deadline"]=now+delay
                continue
            if delay is None:
                r["deadline"]=None
                r.pop("absence",None)
                if not self.dynamic_owner(eid) and not sensor_rules.conditional(a):self.drop(eid)
            elif self.app.globals["maintenance_mode"] or not self.absent(eid):
                r["deadline"]=None
                r.pop("absence",None)
                self.queued.discard(eid)
            elif r["deadline"] is None:
                r["deadline"]=now+delay
                r["absence"]=self.absence_signature(eid)
        self.save()

    def live_group_owned(self,eid,states):
        record=self.owners.get(eid)
        members=self.group_members(eid)
        if not record or not members:return False
        observed={s.get("entity_id"):s for s in states if isinstance(s,dict)}
        return record["signature"].get("members")=={m:signature(observed.get(m,{})) for m in members}

    def live_owned(self,eid,state):
        record=self.owners.get(eid)
        return bool(record and isinstance(state,dict) and state.get("entity_id")==eid
                    and signature(state)==record["signature"])

    def allowed(self,source,action,token,eid,rid=None):
        if (not self.ready or self.app.globals["maintenance_mode"] or token["generation"]!=self.generation
                or token["row"]!=self.row(source) or token["manual"].get(eid)!=self.manual.get(eid,0)
                or not self.target_ok(eid) or (not source.startswith("key:") and self.group_overlap(eid))
                or token.get("routes",{}).get(eid)!=self.app.config.get("light_routes",{}).get(eid)):
            return False
        if action=="SENSOR_ON":
            if rid is not None and self.app.event_log.active_target(eid,exclude=rid):return False
            a=self.assignment(token["row"],eid)
            if not sensor_rules.mode_allows(a,self.home_mode()) or (sensor_rules.conditional(a) and token.get("mode")!=self.home_mode()):return False
            return self.presence(source)=="on" and token["epoch"]==self.epoch.get(source,0) and self.state(eid)=="off" and eid not in self.pending and self.group_ready(eid,"off")
        if "mode_snapshot" in token:
            return (not self.app.event_log.active_target(eid,exclude=rid)
                    and self.mode_off_allowed(eid,source,token["mode_snapshot"]))
        r=self.owners.get(eid)
        return bool(r and r["source"]==source and r["deadline"] is not None
                    and r["deadline"]<=time.time() and (source.startswith("key:") or self.absent(eid)) and self.state(eid)=="on" and eid not in self.profile_changes
                    and self.group_ready(eid,"on") and self.target_signature(eid)==r["signature"] and (source.startswith("key:") or r.get("absence")==self.absence_signature(eid)))

    def dispatched(self,source,action,token,eid,desired):
        if action=="SENSOR_OFF" or desired!="on" or not self.ready or token["generation"]!=self.generation:
            self.drop(eid)
        elif token["manual"].get(eid)==self.manual.get(eid,0) and token["row"]==self.row(source):
            a=next((a for a in token["row"]["assignments"] if a["entity_id"]==eid),{})
            if (sensor_rules.mode_delay(a,token.get("mode")) is not None
                    or sensor_rules.mode_data(a,token.get("mode")).get("profile")=="current" or sensor_rules.conditional(a)):
                if self.state(eid)=="on" and self.target_signature(eid).get("last_changed"):
                    self.owners[eid]={"source":source,"row":deepcopy(token["row"]),
                                      "signature":self.target_signature(eid),"deadline":None,"mode":token.get("mode")}
                else:
                    self.pending[eid]={"source":source,"row":deepcopy(token["row"]),"expires":time.time()+CONFIRM_SECONDS,
                                       "route":deepcopy(self.app.config.get("light_routes",{}).get(eid)),
                                       "members":self.group_members(eid),"mode":token.get("mode")}
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
                    r=self.owners.get(eid,{})
                    if (r.get("source","").startswith("key:") or self.absent(eid)) and eid not in self.profile_changes:self.drop(eid)
            self.save()
