"""HAOS App service. A single event loop owns all authoritative mutations."""
from concurrent.futures import ThreadPoolExecutor, Future
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from queue import Queue, Empty, Full
import re
import secrets
import signal
import threading
import time
import urllib.request
import uuid

from core import Engine, Store, Publication, GLOBAL, PRODUCT, ContractError
from runtime import Session, TransportError, COMMANDS
from discovery import (ID, PREFIX, AVAIL, LEASE, PROBE, LOOP, DISCOVERY, HA_STATUS, GATE_EVENT,
                       CTRL, FIELD, OPS, GATES, state_topic, discovery, sync, projections, translate, scalar)
from gates import Gates, Z2MRegistry, ha_probe
from lifecycle import Lifecycle
from ingress import serve

LOG = logging.getLogger(ID)
PERIOD = 5
TTL = 20
PROBE_TIMEOUT = 10
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def utcnow():
    return datetime.now(timezone.utc)


def version_tuple(s):
    if not isinstance(s,str) or not SEMVER.fullmatch(s):
        raise ValueError("Invalid stable version")
    return tuple(map(int,s.split(".")))


def latest_release():
    prefix=ID+"-v"
    best=None
    for page in range(1,11):
        req=urllib.request.Request("https://api.github.com/repos/DigitalHouses/home-assistant-apps/releases?per_page=100&page="+str(page),
                                   headers={"Accept":"application/vnd.github+json","User-Agent":ID})
        with urllib.request.urlopen(req,timeout=5) as res:
            items=json.load(res)
        if not isinstance(items,list):
            raise ValueError("Invalid release response")
        for item in items:
            tag=item.get("tag_name","")
            if tag.startswith(prefix) and not item.get("draft") and not item.get("prerelease"):
                v=tag[len(prefix):]
                if SEMVER.fullmatch(v) and (best is None or version_tuple(v)>version_tuple(best)):
                    best=v
        if len(items)<100:
            break
        if best:
            # Repository releases sorted newest first; include all matches on this page.
            break
    if best is None:
        raise ValueError("Stable release not found")
    return best


def empty_operation(state="idle"):
    return {"state":state,"started_at":None,"finished_at":None,"duration_seconds":None,"error":None}


class Service:
    def __init__(self, engine, version, opts, *, clock=time.monotonic, ha_fn=ha_probe, release_fn=latest_release):
        self.engine=engine
        self.version=version
        version_tuple(version)
        self.started_at=utcnow().isoformat()
        self.opts=opts
        self.clock=clock
        self.ha_fn=ha_fn
        self.release_fn=release_fn
        self.gates=Gates(require_ha=opts["require_ha"],require_z2m=opts["require_z2m"],ttl=TTL)
        self.z=Z2MRegistry(TTL,PROBE_TIMEOUT)
        self.life=Lifecycle()
        self.executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix="dh-probe")
        self.session=None
        self.session_id=None
        self.loop_nonce=None
        self.loop_deadline=0
        self.ha_future=None
        self.ha_generation=0
        self.ha_deadline=0
        self.next_probe=0
        self.next_lease=0
        self.prev_gates=None
        self.next_projection=0
        self.commands=Queue(maxsize=32)
        self.view_lock=threading.Lock()
        self._view={}
        self.card=dict(empty_operation(),operation=None)
        self.refresh_state=empty_operation()
        self.check_state=empty_operation()
        self.operation=None
        self.op_start=None
        self.release_future=None
        self.last_refresh=None
        self.latest=None
        self.clear_success=None
        self.last_life=None
        self.update_view()

    def send(self, pubs):
        if self.session:
            self.session.publish(pubs)

    def entity(self,key,value,retain=True):
        return Publication(state_topic(key),scalar(value),retain)

    def update_view(self):
        with self.view_lock:
            self._view={"state":self.engine.state,"gates":self.gates.states(self.clock()),
                        "diagnostics":self.gates.diagnostics(self.clock()),"zigbee_bridges":self.z.diagnostics(self.clock()),"lifecycle":self.life.values(utcnow()),
                        "card":deepcopy(self.card),"version":self.version,"latest_version":self.latest,
                        "mqtt_connected":self.session is not None}

    def view(self):
        with self.view_lock:
            return deepcopy(self._view)

    def submit(self,topic,payload):
        future=Future()
        try:
            self.commands.put_nowait((topic,payload,future))
        except Full:
            raise ContractError("Command queue full")
        try:
            return future.result(timeout=15)
        except TimeoutError:
            future.cancel()
            raise ContractError("Command confirmation timed out; read current state")

    def drain(self):
        while True:
            try:
                topic,payload,future=self.commands.get_nowait()
            except Empty:
                break
            if not future.set_running_or_notify_cancel():
                continue
            try:
                self.command(topic,payload)
                self.update_view()
                future.set_result(self.view())
            except ContractError as e:
                future.set_exception(e)
            except (TransportError,OSError) as e:
                future.set_exception(ContractError("Transport/storage failure; check current state"))
                raise

    def command(self,topic,payload):
        if topic.startswith(CTRL):
            op=topic[len(CTRL):]
            if op not in OPS or payload!="PRESS":
                raise ContractError("Invalid operation")
            self.start_operation(op)
            return
        if topic.startswith(FIELD):
            topic,payload=translate(topic,payload)
        pubs=(self.engine.import_settings(payload,utcnow()) if topic=="internal/import"
              else self.engine.command(topic,payload,utcnow()))
        # State first, projections next, event last.
        self.send([p for p in pubs if p.retain])
        if pubs:
            self.send(projections(self.engine.state))
        self.send([p for p in pubs if not p.retain])

    def connect(self,host,port,user,password):
        self.session_id=str(uuid.uuid4())
        self.gates.reset()
        self.z=Z2MRegistry(TTL,PROBE_TIMEOUT)
        self.loop_nonce=None
        self.ha_generation+=1
        self.prev_gates=None
        self.next_probe=self.next_lease=0
        s=Session(host,port,user,password,commands=COMMANDS+(FIELD+"+/set",CTRL+"+"),
                  observations=(LOOP,HA_STATUS),discover_bridges=True,
                  availability=AVAIL)
        try:
            s.open()
        except BaseException:
            s.close()
            raise
        self.session=s
        # Fence old retained state before advertising availability.
        self.send([Publication(AVAIL,"offline")])
        self.publish_gates(force=True,events=False)
        self.engine.tick(utcnow())
        self.publish_snapshot()
        self.send([Publication(AVAIL,"online")])
        self.update_view()
        LOG.info("MQTT connected; readiness requires new session probes")

    def publish_snapshot(self):
        self.send([Publication(DISCOVERY,discovery(self.version)),sync(self.version)])
        self.send(self.engine.snapshot()+projections(self.engine.state))
        self.send([self.entity("version",self.version),self.entity("started_at",self.started_at),
                   self.entity("latest_version",self.latest),self.entity("update_available",None if self.latest is None else version_tuple(self.latest)>version_tuple(self.version)),
                   self.entity("last_refresh",self.last_refresh)])
        self.publish_operation()
        self.publish_lifecycle(force=True)

    def publish_gates(self,force=False,events=True):
        now=self.clock()
        values=self.gates.states(now)
        changes=[k for k in GATES if force or self.prev_gates is None or values[k]!=self.prev_gates[k]]
        self.send([Publication("DigitalHouses/Global/"+k+"/state",scalar(values[k])) for k in changes])
        if changes or now>=self.next_lease:
            lease={k:scalar(v) for k,v in values.items()}
            lease.update({"session_id":self.session_id,"observed_at":utcnow().isoformat(),"valid_for_seconds":TTL})
            self.send([Publication(LEASE,lease,False)])
            self.next_lease=now+PERIOD
        if events and self.prev_gates is not None:
            for k in changes:
                if values[k]!=self.prev_gates[k]:
                    self.send([Publication(GATE_EVENT,{"schema_version":1,"event_type":k+"_"+scalar(values[k]),"observed_at":utcnow().isoformat(),"reason":self.gates.diagnostics(now).get(k,{}).get("reason","required_components")},False)])
        self.prev_gates=values

    def publish_lifecycle(self,force=False):
        current=self.life.values(utcnow())
        if force or current!=self.last_life:
            self.send([self.entity(k,v) for k,v in current.items() if force or self.last_life is None or self.last_life.get(k)!=v])
        self.last_life=current

    def disconnect(self,graceful=False):
        if self.session:
            self.gates.reset()
            self.ha_generation+=1
            if graceful:
                try:
                    self.publish_gates(force=True,events=False)
                    self.send([Publication(AVAIL,"offline")])
                except (TransportError,OSError):
                    pass
            self.session.close(abort=not graceful)
            self.session=None
        self.gates.reset()
        self.z=Z2MRegistry(TTL,PROBE_TIMEOUT)
        self.update_view()

    def message(self,topic,raw,retained):
        try:
            value=raw.decode("utf-8")
            if topic==LOOP:
                if not retained and self.loop_nonce and value==self.loop_nonce and self.clock()<=self.loop_deadline:
                    self.gates.prove("mqtt_ready",self.clock())
                    self.loop_nonce=None
                return
            if topic==HA_STATUS:
                if value in ("online","offline"):
                    self.gates.invalidate("ha_ready","ha_"+value)
                    self.ha_generation+=1
                    self.next_probe=0
                    if value=="online":
                        self.send([Publication(DISCOVERY,discovery(self.version))])
                return
            if self.z.observe(topic,value,retained,self.clock()):
                self.z.update_gate(self.gates,self.clock())
                return
            if retained:
                raise ContractError("Retained command")
            if topic in (PRODUCT+"/config/set",PRODUCT+"/profiles/set"):
                value=json.loads(value)
            self.command(topic,value)
        except (ContractError,ValueError,UnicodeError):
            LOG.warning("Rejected invalid payload on %s",topic)

    def probe(self):
        t=self.clock()
        if self.ha_future and self.ha_future[1].done():
            generation,future=self.ha_future
            self.ha_future=None
            result=future.result()
            if generation==self.ha_generation and t<=self.ha_deadline:
                ev=self.life.observe(result,utcnow())
                if result.nonce_seen:
                    self.gates.prove("ha_ready",t)
                else:
                    self.gates.invalidate("ha_ready","ha_probe_not_confirmed")
                self.publish_lifecycle()
                self.send(ev)
        if self.loop_nonce and t>self.loop_deadline:
            self.loop_nonce=None
            self.gates.invalidate("mqtt_ready","roundtrip_timeout")
        self.z.update_gate(self.gates,t)
        if self.ha_future and t>self.ha_deadline:
            self.gates.invalidate("ha_ready","ha_probe_timeout")
        if t<self.next_probe:
            return
        self.next_probe=t+PERIOD
        if self.loop_nonce is None:
            self.loop_nonce=uuid.uuid4().hex
            self.loop_deadline=t+PROBE_TIMEOUT
            self.send([Publication(LOOP,self.loop_nonce,False)])
        for topic,nonce in self.z.requests(t,lambda:secrets.randbelow(2**31)):
            self.send([Publication(topic,{"transaction":nonce},False)])
        self.z.update_gate(self.gates,t)
        if self.ha_future is None:
            nonce=uuid.uuid4().hex
            self.send([Publication(PROBE,nonce,False)])
            self.ha_deadline=t+PROBE_TIMEOUT
            self.ha_future=(self.ha_generation,self.executor.submit(self._ha_wait,nonce))

    def _ha_wait(self,nonce):
        # HA discovery and state delivery are asynchronous; bounded retries.
        until=time.monotonic()+5
        while True:
            r=self.ha_fn(self.opts.get("ha_url"),self.opts.get("ha_token"),nonce,"sensor."+PREFIX+"_ha_probe")
            if r.nonce_seen or time.monotonic()>=until or not self.opts.get("ha_url"):
                return r
            if r.reachable and r.state!="RUNNING":
                return r
            time.sleep(.3)

    def publish_operation(self):
        self.send([Publication(state_topic("card"),self.card),
                   Publication(state_topic("refresh_state"),self.refresh_state),
                   Publication(state_topic("check_state"),self.check_state)])

    def start_operation(self,op):
        if self.operation or (op=="check_updates" and self.release_future and not self.release_future.done()):
            return
        if not self.session:
            raise ContractError("MQTT unavailable")
        self.operation=op
        self.op_start=self.clock()
        self.clear_success=None
        record={"state":"updating","started_at":utcnow().isoformat(),"finished_at":None,"duration_seconds":None,"error":None}
        if op=="refresh":
            self.refresh_state=record
        else:
            self.check_state=record
        self.card=dict(record,state="running",operation="refresh" if op=="refresh" else "check")
        self.publish_operation()
        if op=="refresh":
            self.next_probe=0
        else:
            self.release_future=self.executor.submit(self.release_fn)

    def finish_operation(self,error=None):
        record={"state":"error" if error else "idle","started_at":self.card["started_at"],"finished_at":utcnow().isoformat(),"duration_seconds":round(self.clock()-self.op_start,3),"error":error}
        if self.operation=="refresh":
            self.refresh_state=record
            if not error:
                self.last_refresh=record["finished_at"]
                self.send([self.entity("last_refresh",self.last_refresh)])
        else:
            self.check_state=record
        self.card=dict(record,state="error" if error else "success",operation=self.card["operation"])
        self.operation=None
        self.clear_success=None if error else self.clock()+5
        self.publish_operation()

    def poll_operation(self):
        if self.operation=="refresh":
            t=self.clock()
            fresh=all(self.gates.evidence.get(k,-1)>=self.op_start and self.gates.states(t)[k] for k in self.gates.required)
            if fresh:
                self.publish_gates(force=True,events=False)
                self.send(self.engine.snapshot()+projections(self.engine.state))
                self.publish_lifecycle(force=True)
                self.finish_operation()
            elif t-self.op_start>25:
                self.finish_operation("Required readiness probes did not complete")
        elif self.operation=="check_updates" and self.release_future and self.release_future.done():
            try:
                self.latest=self.release_future.result()
            except Exception:
                self.finish_operation("Stable release check failed")
            else:
                self.send([self.entity("latest_version",self.latest),self.entity("update_available",version_tuple(self.latest)>version_tuple(self.version))])
                self.finish_operation()
            self.release_future=None
        elif self.operation=="check_updates" and self.clock()-self.op_start>65:
            self.finish_operation("Stable release check timed out")
        elif self.clear_success and self.clock()>=self.clear_success:
            self.card=dict(empty_operation(),operation=None)
            self.clear_success=None
            self.publish_operation()

    def step(self):
        self.drain()
        pubs=self.engine.tick(utcnow())
        self.send([p for p in pubs if p.retain])
        if pubs:
            self.send(projections(self.engine.state))
        self.send([p for p in pubs if not p.retain])
        if self.session:
            self.session.pump(.1)
            for _ in range(len(self.session.messages)):
                self.message(*self.session.messages.popleft())
            self.probe()
            self.publish_gates()
            self.poll_operation()
        self.update_view()

    def run(self,host,port,user,password,stop):
        try:
            while not stop():
                try:
                    self.step()
                    if self.session is None:
                        self.connect(host,port,user,password)
                except (TransportError,OSError) as e:
                    LOG.warning("MQTT or I/O unavailable: %s",type(e).__name__)
                    self.disconnect()
                    if self.operation:
                        # No successful operation may survive a failed required publication.
                        self.finish_operation("Connection lost")
                    end=self.clock()+3
                    while not stop() and self.clock()<end:
                        self.step()
                        time.sleep(.1)
        finally:
            self.disconnect(graceful=True)
            self.executor.shutdown(wait=False,cancel_futures=True)


def main():
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    opts=json.loads(Path("/data/options.json").read_text())
    for key in ("require_ha","require_z2m","telemetry_enabled"):
        if type(opts.get(key)) is not bool:
            raise ContractError("Invalid option "+key)
    if opts["telemetry_enabled"] is not True:
        LOG.error("Telemetry terms have not been accepted; official App activation is disabled")
        return
    opts.update(ha_url="http://supervisor/core/api",ha_token=os.environ.get("SUPERVISOR_TOKEN"))
    engine=Engine(Store("/data/state.json"))
    if engine.state["config"]["timezone"] is None and os.environ.get("TZ"):
        engine.command(PRODUCT+"/config/set",{"timezone":os.environ["TZ"]},utcnow())
    svc=Service(engine,os.environ["APP_VERSION"],opts)
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    server=serve(svc,host="0.0.0.0",port=8099,allowed={"172.30.32.2"})
    telemetry=None
    if opts["telemetry_enabled"]:
        from telemetry import TelemetryClient, TelemetryRunner
        telemetry=TelemetryRunner(TelemetryClient(enabled=True,version=svc.version))
        telemetry.start()
    try:
        svc.run(os.environ["MQTT_HOST"],int(os.environ["MQTT_PORT"]),os.environ.get("MQTT_USERNAME"),os.environ.get("MQTT_PASSWORD"),stop.is_set)
    finally:
        server.shutdown()
        if telemetry:
            telemetry.stop()


if __name__=="__main__":
    main()
