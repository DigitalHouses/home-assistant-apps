"""Read-only System Globals live lease consumer (contract c5a8f7c)."""
from datetime import datetime,timezone
import time
from .binding_store import decode_json

ROOT="DigitalHouses/digitalhouses_system_globals_app"
LEASE=ROOT+"/readiness/lease"
AVAIL=ROOT+"/availability"
GATES=("mqtt_ready","ha_ready","zigbee_ready","system_ready")
TOPICS=(LEASE,AVAIL)

class Readiness:
    def __init__(self):
        self.reset()

    def reset(self):
        self.online=False
        self.values={}
        self.until=0
        self.observed=None

    def receive(self,topic,payload,retained=False):
        if topic==AVAIL:
            self.online=payload==b"online"
            if not self.online:
                self.values={}
                self.until=0
            return
        if topic!=LEASE or retained:return
        try:
            if len(payload)>4096:raise ValueError("lease too large")
            d=decode_json(payload)
            stamp=datetime.fromisoformat(d["observed_at"])
            age=(datetime.now(timezone.utc)-stamp).total_seconds()
            ttl=d["valid_for_seconds"]
            if not isinstance(d["session_id"],str) or not d["session_id"] or type(ttl) is not int or not 1<=ttl<=20 or not -2<=age<ttl or any(d[k] not in ("on","off") for k in GATES):
                raise ValueError("invalid lease")
            if self.observed is not None and stamp<=self.observed:return
            self.observed=stamp
            self.values={k:d[k] for k in GATES}
            self.until=time.monotonic()+ttl-max(age,0)
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
            self.values={}
            self.until=0

    def ready(self,zigbee=False):
        required=("mqtt_ready","ha_ready","zigbee_ready") if zigbee else ("mqtt_ready","ha_ready")
        return self.online and time.monotonic()<self.until and all(self.values.get(k)=="on" for k in required)
