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
    def __init__(self,app):
        self.app=app
        self.zone=None
        self.ready=False
        self.generation=0
        self.previous=None
        self.solar={}
        self.seen={}
        self.known_rows={}

    def rows(self):
        return self.app.config.get("schedules",{})

    def disconnect(self):
        self.ready=False
        self.generation+=1
        self.previous=None
        self.solar.clear()

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
        if row!=token["row"] or not row["enabled"] or not token["due"]<=now<=token["due"]+timedelta(seconds=DISPATCH_SECONDS):return False
        if row["trigger"]["kind"]!="time" and not any(key==token["occurrence"] and due==token["due"] for key,due in self.occurrences(row,now,now)):
            return False
        if eid is None:return True
        target=self.app.target_catalog.get(eid)
        route=self.app.config.get("light_routes",{}).get(eid)
        if not target or token["routes"].get(eid)!=route:return False
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

    def tick(self,now=None):
        now=now or datetime.now(timezone.utc)
        start=self.previous
        self.previous=now
        if not self.ready or not self.app.sensor_engine.ready:
            return
        # Do not replay missed events after downtime, long worker stalls or clock jumps.
        if start is None or not 0<(now-start).total_seconds()<=GRACE:
            self.known_rows=deepcopy(self.rows())
            return
        for eid,row in self.rows().items():
            if not row["enabled"] or self.known_rows.get(eid)!=row:
                continue
            for occurrence,due in self.occurrences(row,start,now):
                key=(eid,occurrence)
                if not start<due<=now or key in self.seen:continue
                self.seen[key]=due
                if self.app.globals["maintenance_mode"]:continue
                calls=rules.commands(row)
                targets=[a["entity_id"] for a in row["assignments"]]
                rid=self.app.event_log.press("ha",row["name"],"Расписание",targets)
                token={"row":deepcopy(row),"generation":self.generation,"due":due,"occurrence":occurrence,
                       "routes":{e:deepcopy(self.app.config.get("light_routes",{}).get(e)) for e in targets}}
                try:self.app._jobs.put_nowait((None,token,row["name"],"SCHEDULE",calls,rid))
                except queue.Full:self.app.event_log.finish(rid,"Очередь заполнена",targets)
        self.known_rows=deepcopy(self.rows())
        self.seen={k:v for k,v in self.seen.items() if v>=now-timedelta(days=3)}
