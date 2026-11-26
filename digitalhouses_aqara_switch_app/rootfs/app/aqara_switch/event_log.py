"""Bounded, in-memory action journal; confirmation is observed state, not ACK."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from time import monotonic
from uuid import uuid4

class EventLog:
    LIMIT = 500
    MAX_AGE = 86400
    CONFIRM_SECONDS = 90

    def __init__(self):
        self.lock = RLock()
        self.rows = OrderedDict()
        self.pending = {}  # one latest command per transport identity
        self.seq = 0
        self.generation = uuid4().hex
        self.timezone = None

    def _touch(self, row):
        self.seq += 1
        row["revision"] = self.seq

    def _prune(self, now):
        for key, (rid, eid, started) in list(self.pending.items()):
            row = self.rows.get(rid)
            if row is None or now-started >= self.CONFIRM_SECONDS:
                self.pending.pop(key, None)
                if row and row["targets"][eid]["status"] == "sent":
                    row["targets"][eid]["status"] = "timeout"
                    self._touch(row)
        while self.rows and (len(self.rows)>self.LIMIT or
                now-next(iter(self.rows.values()))["_created"] >= self.MAX_AGE):
            rid, _ = self.rows.popitem(last=False)
            for key, p in list(self.pending.items()):
                if p[0] == rid:
                    del self.pending[key]

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

    def sent(self, rid, eid, route, before, desired, started=None, sent_at=None):
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
                prev["targets"][old[1]]["status"] = "superseded"
                self._touch(prev)
            row["targets"][eid].update(status="sent",
                before=before.lower() if before in ("ON","OFF","on","off") else None,
                desired=desired.lower(), sent_at=sent_at or datetime.now(timezone.utc).isoformat())
            self.pending[route]=(rid,eid,now)
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
            if state.lower()!=t["desired"]:
                return
            t.update(status="confirmed", observed=state.lower())
            self.pending.pop(route,None)
            self._touch(row)

    def ha_observations(self, states):
        with self.lock:
            self._prune(monotonic())
        for s in states:
            eid=s.get("entity_id")
            if eid:
                self.observe(("ha",eid),s.get("state"),s.get("last_changed"))

    def invalidate(self, route):
        with self.lock:
            pending=self.pending.pop(route,None)
            if pending:
                rid,eid,_=pending
                row=self.rows.get(rid)
                if row:
                    row["targets"][eid]["status"]="timeout"
                    self._touch(row)

    def disconnect(self):
        with self.lock:
            for route,(rid,eid,_) in list(self.pending.items()):
                if route[0]=="z2m":
                    row=self.rows.get(rid)
                    if row:
                        row["targets"][eid]["status"]="timeout"
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
                    "rows":rows,"limit":self.LIMIT}
