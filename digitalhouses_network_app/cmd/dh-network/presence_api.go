package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "encoding/json"
 "errors"
 "io"
 "net/http"
 "net/netip"
 "strings"
 "time"
)

type PresenceSubscription struct {
 Kind string `json:"kind"`
 Target string `json:"target"`
 Enabled bool `json:"enabled"`
 Notifications bool `json:"notifications"`
 State string `json:"state"`
 LastCheck string `json:"last_check"`
 LastPositive string `json:"last_positive"`
 LastChanged string `json:"last_changed"`
 Reason string `json:"reason"`
 Successes int `json:"successes"`
 Failures int `json:"failures"`
 NeededSuccesses int `json:"needed_successes"`
 NeededFailures int `json:"needed_failures"`
}

func presenceTarget(kind,raw string)(string,error){
 value:=strings.TrimSpace(raw)
 switch kind {
 case "ip":
  address,err:=netip.ParseAddr(value)
  if err!=nil||!address.Is4()||!address.IsGlobalUnicast(){return "",errors.New("valid unicast IPv4 required")}
  return address.String(),nil
 case "mac":
  mac:=normalizedMAC(value)
  if mac=="" {return "",errors.New("valid unicast MAC required")}
  return mac,nil
 default:return "",errors.New("kind must be ip or mac")
 }
}

func (db *DB) presenceSubscriptions()([]PresenceSubscription,error){
 values:=[]PresenceSubscription{}
 err:=db.query(`SELECT p.kind,p.target,p.enabled,p.notifications,
   COALESCE(s.state,'unknown'),COALESCE(s.last_check,''),COALESCE(s.last_positive,''),
   COALESCE(s.last_changed,''),COALESCE(s.reason,'not_checked'),
   COALESCE(s.successes,0),COALESCE(s.failures,0),
   c.confirm_successes,c.confirm_failures
   FROM presence_subscriptions p
   JOIN discovery_settings c ON c.id=1
   LEFT JOIN presence_states s ON s.kind=p.kind AND s.target=p.target WHERE p.enabled=1
   ORDER BY p.kind,p.target`,func(stmt *C.sqlite3_stmt){
    values=append(values,PresenceSubscription{
      Kind:field(stmt,0),Target:field(stmt,1),
      Enabled:field(stmt,2)=="1",Notifications:field(stmt,3)=="1",
      State:field(stmt,4),LastCheck:field(stmt,5),LastPositive:field(stmt,6),
      LastChanged:field(stmt,7),Reason:field(stmt,8),
      Successes:int(C.sqlite3_column_int(stmt,9)),Failures:int(C.sqlite3_column_int(stmt,10)),
      NeededSuccesses:int(C.sqlite3_column_int(stmt,11)),NeededFailures:int(C.sqlite3_column_int(stmt,12)),
    })
 })
 return values,err
}

func (db *DB) updatePresence(kind,target string,enabled,notifications bool)(bool,error){
 db.mu.Lock()
 defer db.mu.Unlock()
 now:=time.Now().UTC().Format(time.RFC3339)
 on,alert:="0","0"
 if enabled {on="1";if notifications {alert="1"}}
 // Preserve last-known state for disabled entries; fresh starts explicitly reset
 // the baseline to avoid emitting spurious transitions when re-enabling.
 if err:=db.exec("BEGIN IMMEDIATE");err!=nil{return false,err}
 done:=false
 defer func(){if !done {_=db.exec("ROLLBACK")}}()
 var before string
 _,err:=db.prepared("SELECT enabled FROM presence_subscriptions WHERE kind=? AND target=?",[]string{kind,target},func(stmt *C.sqlite3_stmt){before=field(stmt,0)})
 if err!=nil{return false,err}
 if err:=db.run(`INSERT INTO presence_subscriptions(kind,target,enabled,notifications,updated_at)
 VALUES(?,?,?,?,?) ON CONFLICT(kind,target) DO UPDATE SET
 enabled=excluded.enabled,notifications=excluded.notifications,updated_at=excluded.updated_at`,
 kind,target,on,alert,now);err!=nil{return false,err}
 newlyEnabled:=enabled && before!="1"
 if !enabled || newlyEnabled {
  // Cancel any stale deliveries before removing their outbox entries.
  if err:=db.run(`DELETE FROM event_delivery_log
       WHERE event_id IN (SELECT event_id FROM presence_outbox WHERE kind=? AND target=?)
       AND status IN ('queued','retrying')`,kind,target);err!=nil{return false,err}
  if err:=db.run("DELETE FROM presence_outbox WHERE kind=? AND target=?",kind,target);err!=nil{return false,err}
  if err:=db.run("DELETE FROM presence_states WHERE kind=? AND target=?",kind,target);err!=nil{return false,err}
 }
 if newlyEnabled {
  // Persist a visible working state BEFORE acknowledging the UI action.
  // The runner ignores ARP snapshots from before this subscription.
  if err:=db.run(`INSERT INTO presence_states
      (kind,target,state,reason) VALUES(?,?,'working','scan_requested')`,
      kind,target);err!=nil{return false,err}
 }
 if err:=db.exec("COMMIT");err!=nil{return false,err}
 done=true
 return newlyEnabled,nil
}

func (s *Service) presenceAPI(w http.ResponseWriter,r *http.Request){
 if r.Method==http.MethodGet {
  values,err:=s.db.presenceSubscriptions()
  if err!=nil {http.Error(w,"presence unavailable",500);return}
  reply(w,values);return
 }
 if r.Method!=http.MethodPut {http.Error(w,"method not allowed",405);return}
 if r.Header.Get("X-DH-UI")!="1"||!strings.HasPrefix(r.Header.Get("Content-Type"),"application/json"){
  http.Error(w,"Ingress JSON required",415);return
 }
 var input struct {
  Kind string `json:"kind"`
  Target string `json:"target"`
  Enabled bool `json:"enabled"`
  Notifications bool `json:"notifications"`
 }
 dec:=json.NewDecoder(http.MaxBytesReader(w,r.Body,4096))
 dec.DisallowUnknownFields()
 if err:=dec.Decode(&input);err!=nil {http.Error(w,"invalid JSON",400);return}
 var extra any
 if err:=dec.Decode(&extra);err!=io.EOF {http.Error(w,"unexpected JSON",400);return}
 target,err:=presenceTarget(input.Kind,input.Target)
 if err!=nil {http.Error(w,err.Error(),400);return}
 newlyEnabled,err:=s.db.updatePresence(input.Kind,target,input.Enabled,input.Notifications)
 if err!=nil{
  http.Error(w,"presence save unavailable",500);return
 }
 if newlyEnabled {s.requestPresenceScan()}
 reply(w,map[string]any{"saved":true,"kind":input.Kind,"target":target,"enabled":input.Enabled,
  "notifications":input.Enabled&&input.Notifications,"scan_requested":newlyEnabled})
}

type DeliveryEvent struct {
 EventID string `json:"event_id"`
 EventType string `json:"event_type"`
 OccurredAt string `json:"occurred_at"`
 PublishedAt string `json:"published_at"`
 Status string `json:"status"`
 Attempts string `json:"attempts"`
 PayloadJSON string `json:"payload_json"`
}
func(db *DB)deliveryEvents()([]DeliveryEvent,error){
 values:=[]DeliveryEvent{}
 err:=db.query(`SELECT event_id,event_type,occurred_at,published_at,status,attempts,payload_json
 FROM event_delivery_log ORDER BY occurred_at DESC,event_id DESC LIMIT 500`,
 func(stmt *C.sqlite3_stmt){values=append(values,DeliveryEvent{
  field(stmt,0),field(stmt,1),field(stmt,2),field(stmt,3),field(stmt,4),field(stmt,5),field(stmt,6),
 })})
 return values,err
}
