"""Daily point events on the same Electrica queue; no missed-command replay."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .light_routes import current_route
import queue
from . import schedule_rules as rules

GRACE=10
DISPATCH_SECONDS=30

class ScheduleEngine:
    def __init__(self,app,path=None):
        self.app=app
        self.zone=None
        self.ready=False
        self.generation=0
        self.previous=None
        self.solar={}
        self.seen={}
        self.known_rows={}
        from .schedule_recovery import ScheduleRecovery
        self.recovery=ScheduleRecovery(self,path) if path is not None else None

    def rows(self):
        return self.app.config.get("schedules",{})

    def disconnect(self):
        self.ready=False
        self.generation+=1
        self.previous=None
        self.solar.clear()
        if self.recovery:self.recovery.disconnect()

    def baseline(self,zone,state,now=None):
        self.disconnect()
        now=now or datetime.now(timezone.utc)
        try:self.zone=ZoneInfo(zone)
        except (ValueError,TypeError,KeyError):self.zone=None
        self.ready=self.zone is not None
        self.previous=now
        self.known_rows=deepcopy(self.rows())
        self.observe_sun(state,now)

    def observe_sun(self,state,now=None):
        now=now or datetime.now(timezone.utc)
        times=rules.solar_times(state,now)
        # Keep the previous confirmed event through next_rising/setting
        # rollover, so positive offsets still execute after the event.
        for kind in rules.SOLAR_FIELDS:
            if kind not in times:
                self.solar.pop(kind,None)
                continue
            old=self.solar.get(kind,set())
            self.solar[kind]={dt for dt in old if (now-timedelta(hours=13)<=dt<=now) or dt==times[kind]}|{times[kind]}

    def occurrences(self,row,start,end):
        t=row["trigger"]
        if t["kind"]=="time":
            return rules.clock_occurrences(t,self.zone,start,end)
        return [(dt.isoformat(),dt+timedelta(minutes=t["offset_minutes"])) for dt in self.solar.get(t["kind"],set())]

    def allowed(self,token,eid=None):
        if not self.ready or not self.app.sensor_engine.ready or self.app.globals["maintenance_mode"] or token["generation"]!=self.generation:
            return False
        now=datetime.now(timezone.utc)
        row=self.rows().get(token["row"]["entity_id"])
        if row!=token["row"] or not row["enabled"] or not token["queued_at"]<=now<=token["queued_at"]+timedelta(seconds=DISPATCH_SECONDS):return False
        if not token.get("recovery") and not token["due"]<=now<=token["due"]+timedelta(seconds=DISPATCH_SECONDS):return False
        if row.get("catch_up") and (not self.recovery or (eid is not None and not self.app.readiness.ready(self.recovery.kind(eid)=="zigbee"))):return False
        if not token.get("recovery") and row["trigger"]["kind"]!="time" and not any(key==token["occurrence"] and due==token["due"] for key,due in self.occurrences(row,now,now)):
            return False
        if eid is None:return True
        target=self.app.target_catalog.get(eid)
        route=self.app.config.get("light_routes",{}).get(eid)
        if not target or token["routes"].get(eid)!=route:return False
        if token.get("recovery"):
            if token["identity"]!=self.recovery.identity(self.rows()) or self.recovery.overlap(eid,self.rows()):return False
            if target.get("integration")=="group" or (target.get("group") and (not route or route.get("kind")!="group")):return False
            # A manual action after queueing invalidates recovery.
            if token["manual"].get(eid,0)!=self.app.sensor_engine.manual.get(eid,0):return False
        if route and route.get("kind")=="group":
            base=route["base_topic"]
            net=self.app._networks.get(base,{})
            if not current_route(route,net):return False
            # Explicit group schedules may unify mixed ON/OFF, but never
            # treat missing member reports as a verified group.
            return all(self.app._light_availability.get((base,m["friendly_name"]))=="online"
                       and (base,m["friendly_name"],"state") in self.app._fresh_fields
                       and net.get("states",{}).get(m["friendly_name"],{}).get("state") in ("ON","OFF")
                       and (base,m["friendly_name"]) not in self.app._light_shadows
                       for m in route["members"]) and bool(route["members"])
        return True

    def already_zigbee(self,eid,desired):
        route=self.app.config.get("light_routes",{}).get(eid,{})
        if route.get("kind")=="group":
            net=self.app._networks.get(route["base_topic"],{})
            return bool(route["members"]) and all(net.get("states",{}).get(m["friendly_name"],{}).get("state")==desired.upper() for m in route["members"])
        return self.app.observed_target_state(eid,verify_route=True)==desired

    def enqueue(self,row,assignments,due,occurrence,*,now,recovery=False):
        if not assignments:return
        calls=rules.commands({**row,"assignments":assignments})
        targets=[a["entity_id"] for a in assignments]
        rid=self.app.event_log.press("ha",row["name"],"Восстановление расписания" if recovery else "Расписание",targets)
        token={"row":deepcopy(row),"generation":self.generation,"due":due,"queued_at":now,"occurrence":occurrence,
               "routes":{e:deepcopy(self.app.config.get("light_routes",{}).get(e)) for e in targets},
               "recovery":recovery}
        if recovery:
            token["identity"]=self.recovery.identity(self.rows())
            token["manual"]={eid:self.app.sensor_engine.manual.get(eid,0) for eid in targets}
        try:self.app._jobs.put_nowait((None,token,row["name"],"SCHEDULE",calls,rid))
        except queue.Full:self.app.event_log.finish(rid,"Очередь заполнена",targets)

    def tick(self,now=None):
        now=now or datetime.now(timezone.utc)
        start=self.previous
        self.previous=now
        rows=self.rows()
        if not self.ready or not self.app.sensor_engine.ready:
            if self.recovery:self.recovery.disconnect()
            return
        normal=[]
        if start is not None and 0<(now-start).total_seconds()<=GRACE:
            for eid,row in rows.items():
                if not row["enabled"] or self.known_rows.get(eid)!=row:continue
                for occurrence,due in self.occurrences(row,start,now):
                    key=(eid,occurrence)
                    if not start<due<=now or key in self.seen:continue
                    self.seen[key]=due
                    normal.append((row,due,occurrence))
        # Commit crossed boundaries before normal dispatch, even between
        # periodic checkpoints; recovery and normal path never duplicate.
        handled=self.recovery.step(now,rows,force=bool(normal)) if self.recovery else set()
        for row,due,occurrence in normal:
            if self.app.globals["maintenance_mode"]:continue
            assignments=row["assignments"]
            if row.get("catch_up"):
                assignments=[a for a in assignments if self.recovery
                             and self.recovery.kind(a["entity_id"]) not in handled
                             and self.app.readiness.ready(self.recovery.kind(a["entity_id"])=="zigbee")]
            self.enqueue(row,assignments,due,occurrence,now=now)
        self.known_rows=deepcopy(rows)
        self.seen={k:v for k,v in self.seen.items() if v>=now-timedelta(days=3)}
