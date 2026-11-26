"""Observed HA lifecycle only; loss of API is not proof of a shutdown."""
from datetime import datetime
from core import Publication, UTC
from discovery import LIFECYCLE_EVENT, state_topic

class Lifecycle:
    def __init__(self):
        self.core_state=None
        self.reachable=None
        self.started=None
        self.stopped=None
        self.downtime=None
        self.stopping=False

    def observe(self, result, now):
        events=[]
        def event(name):
            events.append(Publication(LIFECYCLE_EVENT,{"schema_version":1,"event_type":name,"observed_at":now.isoformat()},False))
        if result.reachable!=self.reachable and self.reachable is not None:
            event("ha_connection_restored" if result.reachable else "ha_connection_lost")
        self.reachable=result.reachable
        if result.reachable:
            previous=self.core_state
            self.core_state=result.state
            if result.state=="STOPPING" and previous!="STOPPING":
                self.stopping=True
                event("ha_stopping")
            if result.state in ("NOT_RUNNING","STOPPED") and self.stopping and previous not in ("NOT_RUNNING","STOPPED"):
                self.stopped=now
                self.stopping=False
                event("ha_stopped")
            if result.state=="RUNNING" and previous in ("STARTING","NOT_RUNNING","STOPPED"):
                self.started=now
                self.downtime=(now-self.stopped).total_seconds() if self.stopped else None
                self.stopping=False
                event("ha_started")
            if result.state=="RUNNING" and previous=="STOPPING":
                self.started=None
                self.stopping=False
        else:
            # A connection break invalidates continuity of the observed runtime.
            self.started=None
            self.core_state=None
        return events

    def values(self, now):
        return {
            "ha_core_state":self.core_state if self.reachable else None,
            "ha_started_at":self.started.isoformat() if self.started else None,
            "ha_stopped_at":self.stopped.isoformat() if self.stopped else None,
            "ha_uptime_seconds":int((now-self.started).total_seconds()) if self.started and self.reachable and self.core_state=="RUNNING" else None,
            "ha_downtime_seconds":self.downtime,
        }
