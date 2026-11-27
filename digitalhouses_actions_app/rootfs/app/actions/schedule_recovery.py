"""Bounded, one-shot recovery for explicitly opted-in daily light/switch events.

One checkpoint per relevant gate class. No device command is sent here:
the normal schedule queue owns dispatch. Checkpoint is committed before
queueing, favoring a missed action over duplicate recovery after a crash.
"""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from hashlib import sha256
import json
import logging
import os

from . import schedule_rules as rules
from .binding_store import decode_json

LOG=logging.getLogger(__name__)
MAX_GAP=timedelta(hours=24)
PERIOD=timedelta(seconds=5)

def timestamp(raw):
    d=datetime.fromisoformat(raw)
    if d.tzinfo is None:raise ValueError("naive checkpoint")
    return d.astimezone(timezone.utc)

class ScheduleRecovery:
    def __init__(self,engine,path):
        self.engine=engine
        self.app=engine.app
        self.path=Path(path)
        self.saved={}
        self.closed={"ha":True,"zigbee":True}
        try:
            if self.path.exists():
                raw=self.path.read_bytes()
                if len(raw)>1048576:raise ValueError("checkpoint too large")
                doc=decode_json(raw)
                if doc.get("schema")!=1:raise ValueError("checkpoint schema")
                self.saved={k:v for k,v in doc["checkpoints"].items() if k in self.closed and isinstance(v,dict)}
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            LOG.warning("Schedule history unavailable; recovery will establish a new baseline")
            self.saved={}

    def disconnect(self):
        self.closed=dict.fromkeys(self.closed,True)

    def save(self,kind,record):
        data={**self.saved,kind:record}
        tmp=self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with tmp.open("w",encoding="utf-8") as f:
                json.dump({"schema":1,"checkpoints":data},f,allow_nan=False,separators=(",",":"))
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.path)
        except (OSError,TypeError,ValueError):
            LOG.warning("Schedule checkpoint write failed; no catch-up commands")
            return False
        self.saved=data
        return True

    def kind(self,eid):
        t=self.app.target_catalog.get(eid,{})
        return "zigbee" if eid in self.app.config.get("light_routes",{}) or t.get("integration")=="mqtt" else "ha"

    def identity(self,rows):
        routes=self.app.config.get("light_routes",{})
        ids={a["entity_id"] for r in rows.values() for a in r["assignments"]}
        # Route and full schedule revision are fenced: an edit during outage
        # cannot be mistaken for a schedule that existed before the outage.
        return sha256(json.dumps([rows,{eid:routes.get(eid) for eid in sorted(ids)}],
                        sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()

    def record(self,now,identity):
        return {"at":now.isoformat(),"zone":self.engine.zone.key,"identity":identity,
                "solar":{k:sorted(d.isoformat() for d in values) for k,values in self.engine.solar.items()}}

    def overlap(self,eid,rows):
        routes=self.app.config.get("light_routes",{})
        def members(key):
            r=routes.get(key)
            if not r:return {("ha",key)}
            if r.get("kind")=="group":return {(r["base_topic"],m["ieee"]) for m in r["members"]}
            return {(r["base_topic"],r.get("ieee",r["friendly_name"]))}
        leaves=members(eid)
        return any(a["entity_id"]!=eid and leaves&members(a["entity_id"])
                   for r in rows.values() if r["enabled"] for a in r["assignments"])

    def candidates(self,kind,rows,old,start,now):
        latest={}
        uncertain={}
        for r in rows.values():
            if r["enabled"]:
                for a in r["assignments"]:
                    common=self.app.config.get("common_actions",{}).get(a["entity_id"])
                    if common and common["enabled"]:
                        for target in common["assignments"]:uncertain[target["entity_id"]]=now
        def fence(targets,until):
            for a in targets:uncertain[a["entity_id"]]=max(until,uncertain.get(a["entity_id"],start))
        for row in rows.values():
            if not row["enabled"]:continue
            targets=[a for a in row["assignments"] if self.kind(a["entity_id"])==kind]
            if not targets:continue
            trigger=row["trigger"]
            if trigger["kind"]=="time":
                events=rules.clock_occurrences(trigger,self.engine.zone,start,now)
            else:
                solar_kind=trigger["kind"]
                try:
                    saved={timestamp(v) for v in old["solar"][solar_kind]}
                    live=self.engine.solar[solar_kind]
                    old_next=min(d for d in saved if d>=start-timedelta(minutes=1))
                    new_next=min(d for d in live if d>=now-timedelta(minutes=1))
                    delta=new_next-old_next
                    # Only a matching prediction or one identifiable daily
                    # rollover. No invented solar time during longer outages.
                    if delta!=timedelta(0) and not timedelta(hours=18)<=delta<=timedelta(hours=26):raise ValueError("ambiguous solar rollover")
                    if delta and old_next>now:raise ValueError("changed future prediction")
                    if trigger["offset_minutes"]>0 and not any(d<start for d in saved) and old_next>start:
                        # An unobserved prior solar event could still have a positive offset.
                        fence(targets,start+timedelta(minutes=trigger["offset_minutes"]))
                    events=[(d.isoformat(),d+timedelta(minutes=trigger["offset_minutes"])) for d in saved|live]
                except (KeyError,TypeError,ValueError,OverflowError):
                    fence(targets,now)
                    continue
            for occurrence,due in events:
                if not start<due<=now:continue
                for a in targets:
                    eid=a["entity_id"]
                    old_event=latest.get(eid)
                    if old_event is None or due>old_event[0]:
                        latest[eid]=(due,occurrence,row,a)
                    elif due==old_event[0] and (row!=old_event[2] or a!=old_event[3]):
                        uncertain[eid]=max(due,uncertain.get(eid,start))
        return [(due,occurrence,row,a) for eid,(due,occurrence,row,a) in latest.items()
                if row.get("catch_up") and due>uncertain.get(eid,start) and not self.overlap(eid,rows)
                and eid in self.app.target_catalog
                and not (self.app.target_catalog[eid].get("integration")=="group" or
                         (self.app.target_catalog[eid].get("group") and self.app.config.get("light_routes",{}).get(eid,{}).get("kind")!="group"))]

    def step(self,now,rows,*,force=False):
        """Return classes recovered this tick; ordinary catch-up rows run only
        when their relevant live gates are open. All later rows supersede."""
        if not any(r.get("catch_up") and r["enabled"] for r in rows.values()):
            for k in list(self.saved):
                if self.saved[k]:self.save(k,{})
            self.disconnect()
            return set()
        if self.app.globals["maintenance_mode"]:
            for k in list(self.saved):
                if self.saved[k]:self.save(k,{})
            self.disconnect()
            return set(self.closed)
        identity=self.identity(rows)
        handled=set()
        for kind in self.closed:
            if not self.engine.ready or not self.app.sensor_engine.ready or not self.app.readiness.ready(kind=="zigbee"):
                self.closed[kind]=True
                continue
            old=self.saved.get(kind,{})
            try:start=timestamp(old["at"])
            except (ValueError,TypeError,KeyError,OverflowError):start=None
            matching=old.get("identity")==identity and old.get("zone")==self.engine.zone.key
            gap=now-start if start else None
            recovering=self.closed[kind] or not matching or gap is None or gap<timedelta(0) or gap>timedelta(seconds=10)
            if recovering:handled.add(kind)
            if recovering or force or gap>=PERIOD:
                planned=[]
                if self.closed[kind] and matching and gap is not None and timedelta(0)<gap<=MAX_GAP and not self.app.globals["maintenance_mode"]:
                    planned=self.candidates(kind,rows,old,start,now)
                if not self.save(kind,self.record(now,identity)):
                    self.closed[kind]=True
                    handled.add(kind)
                    continue
                self.closed[kind]=False
                for due,occurrence,row,a in planned:
                    self.engine.enqueue(row,[a],due,occurrence,now=now,recovery=True)
        return handled
