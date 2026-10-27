package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "encoding/json"
 "strings"
 "time"
)

// Source facts only. SSDP never creates or joins devices by IP/USN, changes
// a hostname, updates Presence, or runs requests to a LOCATION URL.
type SSDPServiceRecord struct {
 DeviceID string `json:"device_id"`
 IPv4 string `json:"ipv4"`
 ST string `json:"st"`
 USN string `json:"usn"`
 Server string `json:"server"`
 Location string `json:"location"`
 LastSeen string `json:"last_seen"`
}
type SSDPUnmatched struct {
 IPv4 string `json:"ipv4"`
 ST string `json:"st"`
 USN string `json:"usn"`
 LastSeen string `json:"last_seen"`
 Reason string `json:"reason"`
}

func (db *DB) importSSDPRecords(records []SSDPRecord,at string,packets int,iface string) (matched,unmatched,services int,err error) {
 db.mu.Lock()
 defer db.mu.Unlock()
 if err=db.exec("BEGIN IMMEDIATE");err!=nil{return}
 committed:=false
 defer func(){if !committed {_=db.exec("ROLLBACK")}}()
 seen:=map[string]bool{}
 for _,r:=range records {
  ip:=normalizedIP(r.IPv4,false)
  if ip=="" || r.USN=="" || r.ST=="" || len(r.USN)>220 || len(r.ST)>180 || len(r.Server)>160 || len(r.Location)>300 {continue}
  id,lookupErr:=db.mdnsARPDevice(ip,at)
  if lookupErr!=nil{err=lookupErr;return}
  if id=="" {
   unmatched++
   if err=db.run("INSERT INTO ssdp_unmatched(ipv4,st,usn,last_seen,reason) VALUES(?,?,?,?,'no_fresh_unique_arp') ON CONFLICT(ipv4,st,usn) DO UPDATE SET last_seen=excluded.last_seen",
     ip,r.ST,r.USN,at);err!=nil{return}
   continue
  }
  if !seen[id]{matched++;seen[id]=true}
  if err=db.run("INSERT INTO ssdp_services(device_id,ipv4,st,usn,server,location,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(device_id,st,usn) DO UPDATE SET ipv4=excluded.ipv4,server=excluded.server,location=excluded.location,last_seen=excluded.last_seen",
   id,ip,r.ST,r.USN,r.Server,r.Location,at,at);err!=nil{return}
  services++
 }
 point,_:=time.Parse(time.RFC3339,at)
 if err=db.run("DELETE FROM ssdp_unmatched WHERE last_seen < ?",point.Add(-24*time.Hour).Format(time.RFC3339));err!=nil{return}
 details,_:=json.Marshal(map[string]any{
  "responses":packets,"valid_records":len(records),"matched_devices":matched,
  "unmatched_records":unmatched,"services":services,"interface":iface,
  "matching":"fresh_unique_arp_only","device_xml":"not_fetched","location":"origin_only",
 })
 status:="ok"
 if len(records)==0 {status="empty"}
 if err=db.run("INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('SSDP','ssdp',?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,last_success=excluded.last_success,details_json=excluded.details_json",
   status,at,string(details));err!=nil{return}
 if err=db.exec("COMMIT");err!=nil{return}
 committed=true
 return
}
func (db *DB) recordSSDPFailure(at string,problem error) error {
 db.mu.Lock()
 defer db.mu.Unlock()
 msg:=strings.TrimSpace(problem.Error())
 if len(msg)>240{msg=msg[:240]}
 payload,_:=json.Marshal(map[string]string{"error":msg,"observed_at":at})
 return db.run("INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('SSDP','ssdp','error',NULL,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,details_json=excluded.details_json",
  string(payload))
}
func (db *DB) ssdpSourceRecordsLocked() ([]SSDPServiceRecord,[]SSDPUnmatched,error) {
 records:=make([]SSDPServiceRecord,0)
 unmatched:=make([]SSDPUnmatched,0)
 _,err:=db.prepared("SELECT device_id,ipv4,st,usn,server,location,last_seen FROM ssdp_services ORDER BY device_id,st,usn",nil,func(s *C.sqlite3_stmt){
  records=append(records,SSDPServiceRecord{DeviceID:field(s,0),IPv4:field(s,1),ST:field(s,2),USN:field(s,3),Server:field(s,4),Location:field(s,5),LastSeen:field(s,6)})
 })
 if err!=nil{return nil,nil,err}
 _,err=db.prepared("SELECT ipv4,st,usn,last_seen,reason FROM ssdp_unmatched ORDER BY last_seen DESC LIMIT 100",nil,func(s *C.sqlite3_stmt){
  unmatched=append(unmatched,SSDPUnmatched{IPv4:field(s,0),ST:field(s,1),USN:field(s,2),LastSeen:field(s,3),Reason:field(s,4)})
 })
 return records,unmatched,err
}
