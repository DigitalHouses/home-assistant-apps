"""Bounded live journal, optionally backed by SQLite. Never replay commands."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from time import monotonic, time
import logging
import sqlite3
from uuid import uuid4
from . import climate_rules, media_rules, profile_feedback
from .log_storage import LogStorage

LOG=logging.getLogger(__name__)

class EventLog:
    LIMIT = 500
    MAX_AGE = 86400
    CONFIRM_SECONDS = 90

    def __init__(self,path=None):
        self.lock = RLock()
        self.rows = OrderedDict()
        self.pending = {}  # one latest command per transport identity
        self.seq = 0
        self.generation = uuid4().hex
        self.timezone = None
        self.storage=None
        self.storage_error=False
        if path is not None:
            try:
                self.storage=LogStorage(path)
                now=monotonic()
                for created,row in self.storage.load(time()-self.MAX_AGE,self.LIMIT):
                    row["_created"]=now-max(0,time()-created)
                    self.rows[row["id"]]=row
                    self.seq=max(self.seq,row["id"],row["revision"])
                for row in self.rows.values():
                    changed=False
                    for target in row["targets"].values():
                        if target["status"]=="queued":
                            target.update(status="skipped",reason="Перезапуск приложения")
                            changed=True
                        elif target["status"]=="sent" or (target["status"]=="accepted" and target.get("expected_parameters")):
                            target.update(status="timeout",reason="Перезапуск до подтверждения")
                            changed=True
                    if row.get("reason")=="Применение профиля в очереди":
                        row["reason"]="Перезапуск до выполнения"
                        changed=True
                    if changed:self._touch(row)
            except (sqlite3.Error,OSError,ValueError,KeyError,TypeError) as exc:
                self._storage_failed(exc)
                self.rows.clear()
                self.seq=0

    def _storage_failed(self,exc):
        LOG.error("SQLite action log unavailable; using volatile memory: %s",exc)
        self.storage_error=True
        if self.storage is not None:
            try:self.storage.close()
            except sqlite3.Error:pass
        self.storage=None

    def close(self):
        with self.lock:
            if self.storage is not None:
                self.storage.close()
                self.storage=None

    def _touch(self, row):
        self.seq += 1
        row["revision"] = self.seq
        if self.storage is not None:
            try:self.storage.put(row,datetime.fromisoformat(row["at"]).timestamp())
            except (sqlite3.Error,OSError,ValueError,TypeError) as exc:self._storage_failed(exc)

    def _prune(self, now):
        for key, (rid, eid, started) in list(self.pending.items()):
            row = self.rows.get(rid)
            target=row["targets"][eid] if row else {}
            extension=target.get("parameters",{}).get("transition",0) if target.get("expected_parameters") else 0
            if row is None or now-started >= self.CONFIRM_SECONDS+extension:
                self.pending.pop(key, None)
                if row and target["status"] in ("sent","accepted"):
                    target["status"] = "timeout"
                    target["reason"]="Нет подтверждения параметров" if target.get("expected_parameters") else "Нет подтверждения состояния"
                    self._touch(row)
        removed=[]
        while self.rows and (len(self.rows)>self.LIMIT or
                now-next(iter(self.rows.values()))["_created"] >= self.MAX_AGE):
            rid, _ = self.rows.popitem(last=False)
            removed.append(rid)
            for key, p in list(self.pending.items()):
                if p[0] == rid:
                    del self.pending[key]
        if removed and self.storage is not None:
            try:self.storage.remove(removed)
            except (sqlite3.Error,OSError) as exc:self._storage_failed(exc)

    def active_target(self, eid, *, exclude=None):
        """Use the existing journal as the authority for in-flight commands."""
        with self.lock:
            self._prune(monotonic())
            return any(rid != exclude and
                       row["targets"].get(eid, {}).get("status") in ("queued", "sent")
                       for rid, row in self.rows.items())

    def press(self, network, device, action, targets=()):
        with self.lock:
            self._prune(monotonic())
            rid = self.seq+1
            row = {"id":rid,"at":datetime.now(timezone.utc).isoformat(),
                   "_created":monotonic(),"network":str(network)[:200],
                   "device":str(device)[:200],"action":str(action)[:100],
                   "targets":{eid:{"status":"queued","before":None,"desired":None}
                              for eid in list(targets)[:16] if isinstance(eid,str) and len(eid)<=256},"reason":None}
            self._touch(row)
            self.rows[rid] = row
            self._prune(monotonic())
            return rid

    def finish(self, rid, reason=None, targets=()):
        with self.lock:
            row = self.rows.get(rid)
            if not row:
                return
            if reason:
                row["reason"] = str(reason)[:200]
            for eid in targets:
                if eid in row["targets"] and row["targets"][eid]["status"]=="queued":
                    row["targets"][eid].update(status="skipped",reason=str(reason or "Пропущено")[:160])
            self._touch(row)

    def sent(self, rid, eid, route, before, desired, started=None, sent_at=None, accepted_only=False, parameters=None, expected_parameters=None):
        # Called only after accepted dispatch. MQTT runtime holds its mutex.
        with self.lock:
            row = self.rows.get(rid)
            if not row or eid not in row["targets"]:
                return
            now = monotonic() if started is None else started
            self._prune(monotonic())
            if rid not in self.rows:
                return
            old = self.pending.pop(route,None)
            if old and old[0] in self.rows:
                prev = self.rows[old[0]]
                prev["targets"][old[1]].update(status="superseded",reason="Заменено новой командой")
                self._touch(prev)
            row["targets"][eid].update(status="accepted" if accepted_only else "sent",
                before=before.lower() if before in ("ON","OFF","on","off") else None,
                desired=desired.lower(), sent_at=sent_at or datetime.now(timezone.utc).isoformat())
            if parameters:
                # Requested values, not a claim that the physical light
                # applied them. Never infer color confirmation from ON.
                row["targets"][eid]["parameters"]=deepcopy(
                    parameters if desired.lower()=="on" else
                    {k:v for k,v in parameters.items() if k=="transition" or (k=="brightness_pct" and v==0)})
            expected_parameters=expected_parameters if desired.lower()=="on" else None
            if expected_parameters:
                row["targets"][eid]["expected_parameters"]=deepcopy(expected_parameters)
                # Parameter observation is not an execution interlock; a newer
                # mode or manual command may supersede this command immediately.
            if not accepted_only or expected_parameters:
                self.pending[route]=(rid,eid,now)
            self._touch(row)

    def sent_cover(self,rid,eid,state,desired,sent_at):
        self.sent_ha_domain(rid,eid,state,desired,sent_at)

    def sent_ha_domain(self,rid,eid,state,desired,sent_at,operation=None):
        """Track a requested domain-specific state, not a service ACK."""
        with self.lock:
            row=self.rows.get(rid)
            if not row or eid not in row["targets"]:
                return
            route=("ha",eid)
            old=self.pending.pop(route,None)
            if old and old[0] in self.rows:
                prev=self.rows[old[0]]
                prev["targets"][old[1]]["status"]="superseded"
                self._touch(prev)
            before=state.get("state")
            if eid.startswith("climate.") and desired and desired.startswith("temperature:"):
                value=state.get("attributes",{}).get("temperature")
                before="temperature:"+str(value) if climate_rules.number(value) else None
            if eid.startswith("media_player.") and desired and desired.startswith("volume:"):
                v=state.get("attributes",{}).get("volume_level")
                before="volume:"+str(round(v*100)) if media_rules.number(v) else None
            row["targets"][eid].update(status="sent" if desired else "accepted",
                before=before,desired=desired or operation or "stop",sent_at=sent_at)
            if desired:
                self.pending[route]=(rid,eid,monotonic())
            self._touch(row)

    def observe_cover(self,state):
        self.observe_ha_domain(state)

    def observe_ha_domain(self,state):
        eid=state.get("entity_id")
        with self.lock:
            self._prune(monotonic())
            pending=self.pending.get(("ha",eid))
            if not pending:
                return
            rid,_,_=pending
            row=self.rows[rid]
            target=row["targets"][eid]
            desired=target.get("desired","")
            if eid.startswith("climate."):
                actual=climate_rules.observed_value(state,desired)
            elif eid.startswith("media_player."):
                actual=media_rules.observed_value(state,desired)
            else:
                actual=state.get("state")
                if actual not in ("open","closed"):
                    return
                if desired.startswith("position:"):
                    pos=state.get("attributes",{}).get("current_position")
                    if type(pos) is not int or desired!="position:"+str(pos):
                        return
                    actual=desired
            if actual!=desired:
                return
            try:
                observed=datetime.fromisoformat(state["last_updated"].replace("Z","+00:00"))
                if observed<=datetime.fromisoformat(target["sent_at"]):
                    return
            except (KeyError,ValueError,TypeError,AttributeError):
                return
            target.update(status="confirmed",observed=actual)
            self.pending.pop(("ha",eid),None)
            self._touch(row)

    def skip(self,rid,eid,reason):
        with self.lock:
            row=self.rows.get(rid)
            if row and eid in row["targets"] and row["targets"][eid]["status"]=="queued":
                row["targets"][eid].update(status="skipped",reason=str(reason)[:160])
                self._touch(row)

    def observe(self, route, state, observed_at=None):
        if state not in ("on","off","ON","OFF"):
            return
        with self.lock:
            pending=self.pending.get(route)
            if not pending:
                return
            self._prune(monotonic())
            pending=self.pending.get(route)
            if not pending:
                return
            rid,eid,started=pending
            row=self.rows[rid]
            t=row["targets"][eid]
            # HA snapshots may contain stale cached states. Require a new
            # state-change timestamp; same-state HA cache is not execution.
            if route[0]=="ha":
                if not isinstance(observed_at,str):
                    return
                try:
                    if datetime.fromisoformat(observed_at.replace("Z","+00:00")) <= datetime.fromisoformat(t["sent_at"]):
                        return
                except (ValueError,TypeError):
                    return
            if t.get("expected_parameters"):
                return  # profile must match actual attributes, not just ON
            if state.lower()!=t["desired"]:
                return
            t.update(status="confirmed", observed=state.lower())
            self.pending.pop(route,None)
            self._touch(row)

    def profile_pending(self,route):
        with self.lock:
            pending=self.pending.get(route)
            if not pending:return False
            rid,eid,_=pending
            return bool(self.rows[rid]["targets"][eid].get("expected_parameters"))

    def observe_light(self,route,report):
        """Called only with a fresh, non-duplicate Z2M report or HA state."""
        with self.lock:
            if not self.profile_pending(route):return
            self._prune(monotonic())
            pending=self.pending.get(route)
            if not pending:return
            rid,eid,_=pending
            row=self.rows[rid]
            target=row["targets"][eid]
            expected=target.get("expected_parameters")
            if not expected:return
            if route[0]=="ha":
                try:
                    observed=datetime.fromisoformat(report["last_updated"].replace("Z","+00:00"))
                    if observed<=datetime.fromisoformat(target["sent_at"]):return
                except (KeyError,AttributeError,TypeError,ValueError):return
                actual=profile_feedback.match_ha(expected,report)
            else:
                actual=profile_feedback.match_z2m(expected,report)
            if actual is None:return
            target.update(status="confirmed",observed="on",observed_parameters=actual,
                          observed_at=datetime.now(timezone.utc).isoformat())
            self.pending.pop(route,None)
            self._touch(row)

    def ha_observations(self, states):
        with self.lock:
            self._prune(monotonic())
        for s in states:
            eid=s.get("entity_id")
            if isinstance(eid,str) and eid.startswith(("cover.","climate.","media_player.")):
                self.observe_ha_domain(s)
            elif eid:
                if eid.startswith("light."):self.observe_light(("ha",eid),s)
                self.observe(("ha",eid),s.get("state"),s.get("last_changed"))

    def invalidate(self, route):
        with self.lock:
            pending=self.pending.pop(route,None)
            if pending:
                rid,eid,_=pending
                row=self.rows.get(rid)
                if row:
                    row["targets"][eid].update(status="timeout",reason="Устройство или маршрут недоступны")
                    self._touch(row)

    def disconnect(self):
        with self.lock:
            for route,(rid,eid,_) in list(self.pending.items()):
                if route[0]=="z2m":
                    row=self.rows.get(rid)
                    if row:
                        row["targets"][eid].update(status="timeout",reason="Потеря MQTT")
                        self._touch(row)
                    del self.pending[route]

    def set_timezone(self, name):
        if isinstance(name,str) and 0<len(name)<=128:
            with self.lock:
                self.timezone=name

    def snapshot(self, cursor=0, generation=None):
        with self.lock:
            self._prune(monotonic())
            reset=generation!=self.generation or cursor>self.seq
            rows=[]
            for row in self.rows.values():
                if reset or row["revision"]>cursor:
                    rows.append(deepcopy({k:v for k,v in row.items() if k!="_created"}))
            return {"generation":self.generation,"cursor":self.seq,"reset":reset,
                    "oldest":next(iter(self.rows),self.seq+1),"timezone":self.timezone,
                    "rows":rows,"limit":self.LIMIT,
                    "storage":"sqlite" if self.storage is not None else "memory",
                    "storage_error":self.storage_error}
