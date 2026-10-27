package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "encoding/json"
 "errors"
 "time"
)

type WSDEndpoint struct {
 DeviceID string `json:"device_id"`
 IPv4 string `json:"ipv4"`
 Endpoint string `json:"endpoint"`
 Types string `json:"types"`
 Scopes string `json:"scopes"`
 Origin string `json:"origin"`
 LastSeen string `json:"last_seen"`
}
type WSDUnmatched struct {
 IPv4 string `json:"ipv4"`
 Endpoint string `json:"endpoint"`
 LastSeen string `json:"last_seen"`
 Reason string `json:"reason"`
}
func (db *DB) importWSD(items []WSDAnnouncement,at string,packets int,iface string) (matched,unmatched int,err error) {
 db.mu.Lock()
 defer db.mu.Unlock()
 if err=db.exec("BEGIN IMMEDIATE");err!=nil{return}
 complete:=false
 defer func(){if !complete {_=db.exec("ROLLBACK")}}()
 linked:=map[string]bool{}
 for _,x:=range items {
  ip:=normalizedIP(x.IPv4,false)
  if ip==""||len(x.Endpoint)>130||len(x.Types)>300||len(x.Scopes)>500||len(x.Origin)>150 {continue}
  id,lookupErr:=db.mdnsARPDevice(ip,at)
  if lookupErr!=nil{err=lookupErr;return}
  if id=="" {
   unmatched++
   if err=db.run("INSERT INTO wsd_unmatched(ipv4,endpoint,last_seen,reason) VALUES(?,?,?,'no_fresh_unique_direct_evidence') ON CONFLICT(ipv4,endpoint) DO UPDATE SET last_seen=excluded.last_seen",ip,x.Endpoint,at);err!=nil{return}
   continue
  }
  linked[id]=true
  if err=db.run("INSERT INTO wsd_endpoints(device_id,ipv4,endpoint,types,scopes,origin,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(device_id,endpoint) DO UPDATE SET ipv4=excluded.ipv4,types=excluded.types,scopes=excluded.scopes,origin=excluded.origin,last_seen=excluded.last_seen",
   id,ip,x.Endpoint,x.Types,x.Scopes,x.Origin,at,at);err!=nil{return}
  // Never set devices.display_name from endpoint UUID, Types or arbitrary Scopes.
 }
 timestamp,_:=time.Parse(time.RFC3339,at)
 if err=db.run("DELETE FROM wsd_unmatched WHERE last_seen < ?",timestamp.Add(-24*time.Hour).Format(time.RFC3339));err!=nil{return}
 if err=db.run("DELETE FROM wsd_endpoints WHERE last_seen < ?",timestamp.Add(-7*24*time.Hour).Format(time.RFC3339));err!=nil{return}
 details,_:=json.Marshal(map[string]any{
  "responses":packets,"endpoints":len(items),"linked_devices":len(linked),
  "unmatched":unmatched,"interface":iface,"matching":"fresh_unique_arp_or_local_interface",
  "metadata_get":"not_performed","name_assignment":"none",
 })
 status:="ok"
 if len(items)==0 {status="empty"}
 if err=db.run("INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('WS-Discovery','wsd',?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,last_success=excluded.last_success,details_json=excluded.details_json",
   status,at,string(details));err!=nil{return}
 if err=db.exec("COMMIT");err!=nil{return}
 complete=true
 return len(linked),unmatched,nil
}
func (db *DB) recordWSDFailure(at string,e error) error {
 if e==nil {return errors.New("missing WSD error")}
 db.mu.Lock()
 defer db.mu.Unlock()
 msg:=e.Error()
 if len(msg)>200 {msg=msg[:200]}
 payload,_:=json.Marshal(map[string]string{"error":msg,"observed_at":at})
 return db.run("INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('WS-Discovery','wsd','error',NULL,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,details_json=excluded.details_json",string(payload))
}
func (db *DB) wsdRecordsLocked() ([]WSDEndpoint,[]WSDUnmatched,error) {
 endpoints:=make([]WSDEndpoint,0)
 missing:=make([]WSDUnmatched,0)
 _,err:=db.prepared("SELECT device_id,ipv4,endpoint,types,scopes,origin,last_seen FROM wsd_endpoints ORDER BY device_id,endpoint",nil,func(s *C.sqlite3_stmt){
  endpoints=append(endpoints,WSDEndpoint{DeviceID:field(s,0),IPv4:field(s,1),Endpoint:field(s,2),Types:field(s,3),Scopes:field(s,4),Origin:field(s,5),LastSeen:field(s,6)})
 })
 if err!=nil{return nil,nil,err}
 _,err=db.prepared("SELECT ipv4,endpoint,last_seen,reason FROM wsd_unmatched ORDER BY last_seen DESC LIMIT 100",nil,func(s *C.sqlite3_stmt){
  missing=append(missing,WSDUnmatched{IPv4:field(s,0),Endpoint:field(s,1),LastSeen:field(s,2),Reason:field(s,3)})
 })
 return endpoints,missing,err
}
