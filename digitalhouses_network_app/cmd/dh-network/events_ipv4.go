package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "encoding/json"
 "sort"
)

// Record evidence disagreements as local events only. ARP-vs-router reports
// often originate from media bridges and MUST NOT be treated as IP collision
// alarms. Never modify UUID, MAC, Note or address reconciliation rules here.
type disagreementState struct {
 IP string
 Classification string
 Fingerprint string
 DataJSON string
}
type disagreementClaim struct {
 DeviceID string `json:"device_id"`
 MAC string `json:"mac"`
 Source string `json:"source"`
 Reference string `json:"reference,omitempty"`
}
func disagreementClassification(c IPv4Conflict) string {
 arpDevices:=map[string]bool{}
 router:=false
 for _,claim:=range c.Claims {
  if claim.Source=="arp" && claim.State=="observed" {arpDevices[claim.DeviceID]=true}
  if claim.Source=="ha_router" {router=true}
 }
 if c.WinnerSource=="arp" && len(arpDevices)==1 && router {
  allElseRouter:=true
  for _,claim:=range c.Claims {if claim.Source!="arp" && claim.Source!="ha_router" {allElseRouter=false}}
  if allElseRouter {return "source_disagreement"}
 }
 return "ipv4_conflict"
}
func currentDisagreementStates(conflicts []IPv4Conflict) []disagreementState {
 result:=make([]disagreementState,0,len(conflicts))
 for _,conflict:=range conflicts {
  claims:=make([]disagreementClaim,0,len(conflict.Claims))
  for _,c:=range conflict.Claims {
   claims=append(claims,disagreementClaim{DeviceID:c.DeviceID,MAC:c.MAC,Source:c.Source,Reference:c.Reference})
  }
  sort.Slice(claims,func(i,j int)bool{
   a,b:=claims[i],claims[j]
   return a.DeviceID+"|"+a.Source+"|"+a.Reference < b.DeviceID+"|"+b.Source+"|"+b.Reference
  })
  fingerprint,_:=json.Marshal(claims)
  classification:=disagreementClassification(conflict)
  detail,_:=json.Marshal(map[string]any{
   "ipv4":conflict.IPv4,"classification":classification,
   "resolution":conflict.Resolution,"claims":claims,
   "winner_device_id":conflict.WinnerDeviceID,"winner_source":conflict.WinnerSource,
  })
  result=append(result,disagreementState{IP:conflict.IPv4,Classification:classification,Fingerprint:string(fingerprint),DataJSON:string(detail)})
 }
 sort.Slice(result,func(i,j int)bool{return result[i].IP<result[j].IP})
 return result
}
func (db *DB) recordDisagreementChangesLocked(conflicts []IPv4Conflict,at string) error {
 prior:=map[string]disagreementState{}
 _,err:=db.prepared("SELECT ipv4,classification,fingerprint,details_json FROM ipv4_disagreement_state",nil,func(s *C.sqlite3_stmt){
  ip:=field(s,0);prior[ip]=disagreementState{IP:ip,Classification:field(s,1),Fingerprint:field(s,2),DataJSON:field(s,3)}
 })
 if err!=nil{return err}
 current:=currentDisagreementStates(conflicts)
 for _,item:=range current {
  old,wasPresent:=prior[item.IP]
  if !wasPresent || old.Classification!=item.Classification || old.Fingerprint!=item.Fingerprint {
   action:="ipv4_disagreement_started"
   if wasPresent {action="ipv4_disagreement_changed"}
   if err=db.run("INSERT INTO events(event_type,device_id,occurred_at,data_json) VALUES(?,'',?,?)",
      action,at,item.DataJSON);err!=nil{return err}
  }
  if err=db.run("INSERT INTO ipv4_disagreement_state(ipv4,classification,fingerprint,details_json,first_seen,last_seen) VALUES(?,?,?,?,?,?) ON CONFLICT(ipv4) DO UPDATE SET classification=excluded.classification,fingerprint=excluded.fingerprint,details_json=excluded.details_json,last_seen=excluded.last_seen",
   item.IP,item.Classification,item.Fingerprint,item.DataJSON,at,at);err!=nil{return err}
  delete(prior,item.IP)
 }
 ended:=make([]string,0,len(prior))
 for ip:=range prior {ended=append(ended,ip)}
 sort.Strings(ended)
 for _,ip:=range ended {
  old:=prior[ip]
  payload,_:=json.Marshal(map[string]any{
   "ipv4":ip,"classification":old.Classification,
   "previous":json.RawMessage(old.DataJSON),
  })
  if err=db.run("INSERT INTO events(event_type,device_id,occurred_at,data_json) VALUES('ipv4_disagreement_resolved','',?,?)",
    at,string(payload));err!=nil{return err}
  if err=db.run("DELETE FROM ipv4_disagreement_state WHERE ipv4=?",ip);err!=nil{return err}
 }
 return db.run("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 1000)")
}
