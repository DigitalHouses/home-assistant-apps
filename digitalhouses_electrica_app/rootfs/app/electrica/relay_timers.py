"""Auto-OFF of explicitly configured physical Aqara relay channels.

Fresh observations only; restart starts a full delay from the first verified
ON report because MQTT relay state has no reliable persisted transition time.
All access is serialized by Application._mutex; expiry uses the common queue.
"""
import json
import time
import queue
from copy import deepcopy
from .catalog import decode_bridge_devices, CatalogError
from .control import verified_adopted_switch
from .mode_keeper import capabilities, maintained_switch, PHYSICAL, MODE_TO_RELAY


class RelayTimers:
    def __init__(self,app):
        self.app=app
        self.records={}
        self.serial=0
        self.observed={}

    def reset(self):
        self.records.clear()
        self.observed.clear()

    def invalidate(self,base,name=None):
        for ident in list(self.observed):
            if ident[0]==base and (name is None or ident[1]==name):
                self.observed.pop(ident,None)
        for ident,record in list(self.records.items()):
            policy=record["policy"]
            if policy["base"]==base and (name is None or policy["name"]==name):
                self.records.pop(ident,None)

    def observe(self,base,name,device,data):
        try:
            coordinator=json.loads(self.app._networks[base]["info"])["coordinator"]["ieee_address"].lower()
            ieee=device["ieee_address"]
        except (KeyError,TypeError,ValueError):return
        for fields in MODE_TO_RELAY.values():
            for field in fields:
                if field in data:self.observed[(base,name,field)]=(coordinator,ieee,data[field])

    def current(self,sw,key):
        a=self.app
        if not sw.get("enabled") or maintained_switch(sw,a.globals) or sw.get("keep_mode",{}).get(key)!=PHYSICAL:return None
        delay=sw.get("relay_timers",{}).get(key)
        if type(delay) is not int or not 1<=delay<=86400:return None
        base,name=sw["base_topic"],sw["logical_name"]
        net=a._networks.get(base,{})
        if net.get("bridge_state")!="online" or a._input_availability.get((base,name))!="online":return None
        try:
            coordinator=json.loads(net["info"])["coordinator"]["ieee_address"].lower()
            devices=decode_bridge_devices(net["devices"])
            dev=next((d for d in devices if d.get("friendly_name")==name),None)
            if dev is None or dev.get("disabled") is True or not verified_adopted_switch(sw,dev,coordinator,base):return None
            fields=capabilities(dev).get(key)
            if not fields:return None
            mode,relay=fields
            if not all((base,name,f) in a._fresh_fields for f in fields):return None
            state=net.get("states",{}).get(name,{})
            if state.get(mode)!=PHYSICAL or state.get(relay) not in ("ON","OFF"):return None
            if any(self.observed.get((base,name,f))!=(coordinator,sw["ieee"],state.get(f)) for f in fields):return None
            policy={"base":base,"name":name,"coordinator":coordinator,"ieee":sw["ieee"],
                    "fingerprint":deepcopy(sw["fingerprint"]),"field":relay,"delay":delay}
            return policy,state[relay]
        except (KeyError,ValueError,TypeError,CatalogError):
            return None

    def tick(self,now=None,*,enqueue=True):
        now=time.monotonic() if now is None else now
        active=set()
        for room in self.app.config["rooms"]:
            for sw in room["switches"]:
                for key in sw.get("relay_timers",{}):
                    ident=(sw["entity_id"],key)
                    observation=self.current(sw,key)
                    if observation is None or observation[1]!="ON":continue
                    active.add(ident)
                    policy,_=observation
                    rec=self.records.get(ident)
                    if not rec or rec["policy"]!=policy:
                        self.serial+=1
                        rec={"serial":self.serial,"policy":policy,"deadline":now+policy["delay"],"queued":False,"sent":False}
                        self.records[ident]=rec
                    if enqueue and now>=rec["deadline"] and not rec["queued"] and not rec["sent"]:
                        label=ident[0]+"/"+key
                        rid=self.app.event_log.press(policy["base"],policy["name"],"Авто-OFF "+key,[label])
                        try:
                            self.app._jobs.put_nowait((None,None,policy["name"],"RELAY_OFF",[],rid,(ident,rec["serial"])))
                            rec["queued"]=True
                        except queue.Full:
                            self.app.event_log.finish(rid,"Очередь заполнена",[label])
        for ident in list(self.records):
            if ident not in active:self.records.pop(ident,None)

    def dispatch(self,token,rid):
        ident,serial=token
        label=ident[0]+"/"+ident[1]
        rec=self.records.get(ident)
        sw=next((x for room in self.app.config["rooms"] for x in room["switches"] if x["entity_id"]==ident[0]),None)
        live=self.current(sw,ident[1]) if sw else None
        if not rec or rec["serial"]!=serial or rec["sent"] or not live or live!=(rec["policy"],"ON") or time.monotonic()<rec["deadline"]:
            self.app.event_log.finish(rid,"Состояние реле или настройки изменились",[label])
            return False
        rec["sent"]=True
        policy=rec["policy"]
        if not self.app._publish(policy["base"]+"/"+policy["name"]+"/set",{policy["field"]:"OFF"},retain=False):
            self.app.event_log.finish(rid,"MQTT publish rejected",[label])
            return False
        self.app.event_log.sent(rid,label,("relay",policy["base"],policy["name"],policy["field"]),"on","off")
        self.app.event_log.finish(rid)
        return True
