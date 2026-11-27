"""Execute a named common action through the existing serialized Engine."""
from copy import deepcopy
import time
import queue
from datetime import datetime,timezone
from .binding_store import decode_json
import re
import json
from . import common_rules as rules
from .catalog import decode_bridge_devices,CatalogError
from .control import light_commands,verified_adopted_switch
from .mode_keeper import maintained_switch
from .light_routes import current_route

COMMAND_TOPIC="DigitalHouses/digitalhouses_actions_app/common_action/run"

class CommonEngine:
    def __init__(self,app):
        self.app=app
        self.requests={}
        self.generation=0

    def disconnect(self):
        self.generation+=1

    def receive(self,payload,retained=False):
        if retained or len(payload)>4096:return None
        try:
            data=decode_json(payload)
            if not isinstance(data,dict) or set(data)!={"entity_id","request_id","issued_at"} or not rules.is_common(data["entity_id"]) or not isinstance(data["request_id"],str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",data["request_id"]):return None
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(data["issued_at"])).total_seconds()
            if not -2<=age<=30:return None
            now=time.monotonic()
            self.requests={k:v for k,v in self.requests.items() if now-v<=60}
            if data["request_id"] in self.requests or len(self.requests)>=1024:return None
            self.requests[data["request_id"]]=now
            return self.enqueue(data["entity_id"],{"kind":"mqtt","generation":self.generation})
        except (CatalogError,ValueError,KeyError,TypeError,OverflowError):return None

    def enqueue(self,eid,origin):
        a=self.app
        row=a.config.get("common_actions",{}).get(eid)
        if not row or not row["enabled"] or a.globals["maintenance_mode"]:
            raise CatalogError("Общее действие отключено или отсутствует")
        targets=[x["entity_id"] for x in row["assignments"]]
        token={"row":deepcopy(row),"origin":deepcopy(origin),"expires":time.monotonic()+30,
               "routes":{e:deepcopy(a.config.get("light_routes",{}).get(e)) for e in targets}}
        source=origin["kind"]
        label=row["name"]
        if source=="key":source=origin["base"];label=origin["name"]+" / "+origin["press"]+" → "+label
        elif source=="schedule":label=origin["token"]["row"]["name"]+" → "+label
        rid=a.event_log.press(source,label,"Общее действие",targets)
        if origin["kind"]=="key":a.sensor_engine.manual_control(targets)
        try:a._jobs.put_nowait((None,token,row["name"],"COMMON",rules.commands(row),rid))
        except queue.Full:
            a.event_log.finish(rid,"Очередь заполнена",targets)
            raise CatalogError("Очередь заполнена")
        return rid

    def allowed(self,token,eid=None):
        a=self.app
        row=token["row"]
        if a.globals["maintenance_mode"] or time.monotonic()>token["expires"] or a.config.get("common_actions",{}).get(row["entity_id"])!=row or not row["enabled"]:
            return False
        origin=token["origin"]
        if origin["kind"]=="schedule":
            if not a.schedule_engine.allowed(origin["token"]):return False
        elif origin["kind"]=="key":
            base,name,coordinator,press=(origin[k] for k in ("base","name","coordinator","press"))
            net=a._networks.get(base,{})
            sw=next((s for room in a.config["rooms"] for s in room["switches"]
                     if (s["base_topic"],s["logical_name"],s["coordinator_ieee"])==(base,name,coordinator)),None)
            try:
                devices=decode_bridge_devices(net["devices"])
                actual=json.loads(net["info"])["coordinator"]["ieee_address"].lower()
                if actual!=coordinator or [d.get("ieee_address","").lower() for d in devices if d.get("type")=="Coordinator"]!=[coordinator]:return False
                device=next((d for d in devices if d.get("friendly_name")==name),None)
                if not sw or not sw["enabled"] or not device or maintained_switch(sw,a.globals) or not verified_adopted_switch(sw,device,coordinator,base) or not a._input_mode_allowed(sw,press,net,device,False) or rules.reference(light_commands(sw,press) or [])!=row["entity_id"]:
                    return False
            except (CatalogError,KeyError,TypeError,ValueError):return False
        elif origin["kind"]=="mqtt":
            if origin["generation"]!=self.generation:return False
        elif origin["kind"]!="ingress":return False
        if eid is None:return True
        route=a.config.get("light_routes",{}).get(eid)
        if eid not in a.target_catalog or token["routes"].get(eid)!=route:return False
        # For now fail closed on ambiguous group/member overlap instead of
        # issuing contradictory or duplicate commands.
        leaves=self.members(eid)
        if any(other!=eid and leaves&self.members(other) for other in token["routes"]):return False
        if route and route.get("kind")=="group":
            base=route["base_topic"];net=a._networks.get(base,{})
            return current_route(route,net) and bool(route["members"]) and all(
                a._light_availability.get((base,m["friendly_name"]))=="online"
                and (base,m["friendly_name"],"state") in a._fresh_fields
                and net.get("states",{}).get(m["friendly_name"],{}).get("state") in ("ON","OFF")
                and (base,m["friendly_name"]) not in a._light_shadows for m in route["members"])
        return (a.target_catalog[eid].get("integration")!="group" and not a.target_catalog[eid].get("group")
                and not a.sensor_engine.states.get(eid,{}).get("attributes",{}).get("entity_id"))

    def members(self,eid):
        r=self.app.config.get("light_routes",{}).get(eid)
        if not r:return {("ha",eid)}
        if r.get("kind")=="group":return {(r["base_topic"],m["ieee"]) for m in r["members"]}
        return {(r["base_topic"],r.get("ieee",r["friendly_name"]))}
