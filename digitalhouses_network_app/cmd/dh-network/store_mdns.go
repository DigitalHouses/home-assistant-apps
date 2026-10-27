package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "encoding/json"
 "fmt"
 "strings"
 "time"
)

type MDNSRecord struct {
 DeviceID string `json:"device_id"`
 Hostname string `json:"hostname"`
 IPv4 string `json:"ipv4"`
 LastSeen string `json:"last_seen"`
}
type MDNSServiceRecord struct {
 DeviceID string `json:"device_id"`
 Instance string `json:"instance"`
 Type string `json:"type"`
 Port uint16 `json:"port"`
 Target string `json:"target"`
 LastSeen string `json:"last_seen"`
}
type MDNSUnmatched struct {
 Hostname string `json:"hostname"`
 IPv4 string `json:"ipv4"`
 LastSeen string `json:"last_seen"`
 Reason string `json:"reason"`
}

// Called exclusively inside a writer transaction. Never merge a device by
// hostname or by IP alone. Match a current IP only if it has an unequivocal
// recent positive ARP or local OS interface mapping to a MAC-backed device.
func (db *DB) mdnsARPDevice(ip,at string) (string,error) {
 now,err:=time.Parse(time.RFC3339,at)
 if err!=nil{return "",err}
 ttl:=db.lanFreshness
 if ttl<=0 {ttl=420*time.Second}
 cutoff:=now.Add(-ttl).Format(time.RFC3339)
 var ids []string
 _,err=db.prepared(`SELECT DISTINCT e.device_id FROM ipv4_evidence e
 JOIN devices d ON d.id=e.device_id
 WHERE e.source IN ('arp','local_interface') AND e.state='observed' AND e.ipv4=?
 AND d.ipv4=? AND e.last_seen>=? AND d.mac<>''
 ORDER BY e.device_id LIMIT 2`,[]string{ip,ip,cutoff},
 func(stmt *C.sqlite3_stmt){ids=append(ids,field(stmt,0))})
 if err!=nil{return "",err}
 if len(ids)!=1 {return "",nil}
 return ids[0],nil
}

func (db *DB) importMDNSHosts(hosts []MDNSHost,at string,packets int,iface string) (matched,unmatched,services int,err error) {
 db.mu.Lock()
 defer db.mu.Unlock()
 if err=db.exec("BEGIN IMMEDIATE");err!=nil{return}
 committed:=false
 defer func(){if !committed {_=db.exec("ROLLBACK")}}()
 for _,host:=range hosts {
  ip:=normalizedIP(host.IPv4,false)
  hostname:=strings.TrimSuffix(host.Hostname,".")
  if ip=="" || friendlyMDNSHost(hostname)=="" {continue}
  id,lookupErr:=db.mdnsARPDevice(ip,at)
  if lookupErr!=nil{err=lookupErr;return}
  if id=="" {
   unmatched++
   err=db.run(`INSERT INTO mdns_unmatched(hostname,ipv4,last_seen,reason)
     VALUES(?,?,?,'no_fresh_unique_arp')
     ON CONFLICT(hostname,ipv4) DO UPDATE SET last_seen=excluded.last_seen,reason=excluded.reason`,hostname,ip,at)
   if err!=nil{return}
   continue
  }
  matched++
  if err=db.run(`INSERT INTO mdns_hosts(device_id,hostname,ipv4,first_seen,last_seen)
     VALUES(?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE
     SET hostname=excluded.hostname,ipv4=excluded.ipv4,last_seen=excluded.last_seen`,
    id,hostname,ip,at,at);err!=nil{return}
  name:=friendlyMDNSHost(hostname)
  if name!="" {
   // Device names obtained from router integrations take precedence.
   // MAC-only placeholders can be improved with a verified mDNS hostname.
   if err=db.run(`UPDATE devices SET
      display_name=CASE WHEN display_name='' OR LOWER(display_name)=LOWER(mac)
       THEN ? ELSE display_name END,
      hostname=CASE WHEN hostname='' OR LOWER(hostname)=LOWER(mac)
       THEN ? ELSE hostname END
      WHERE id=?`,name,hostname,id);err!=nil{return}
  }
  for _,srv:=range host.Services {
   if srv.Port==0 || len(srv.Instance)>120 || len(srv.Type)>150 || len(srv.Target)>200 {continue}
   if err=db.run(`INSERT INTO mdns_services(device_id,instance,type,port,target,first_seen,last_seen)
     VALUES(?,?,?,?,?,?,?) ON CONFLICT(device_id,instance,type,port)
     DO UPDATE SET target=excluded.target,last_seen=excluded.last_seen`,
     id,srv.Instance,srv.Type,fmt.Sprint(srv.Port),srv.Target,at,at);err!=nil{return}
   services++
  }
 }
 // Unmatched metadata is kept only for recent diagnostics; it never creates
 // a device record or affects Presence.
 prior,_:=time.Parse(time.RFC3339,at)
 if err=db.run("DELETE FROM mdns_unmatched WHERE last_seen < ?",prior.Add(-24*time.Hour).Format(time.RFC3339));err!=nil{return}
 details,_:=json.Marshal(map[string]any{
  "hosts_with_a":len(hosts),"matched":matched,"unmatched":unmatched,
  "services":services,"response_packets":packets,"interface":iface,
  "matching":"fresh_unique_arp_only","txt":"not_collected",
 })
 status:="ok"
 if len(hosts)==0 {status="empty"}
 if err=db.run(`INSERT INTO sources(id,kind,status,last_success,details_json)
   VALUES('mDNS / Bonjour','mdns',?,?,?)
   ON CONFLICT(id) DO UPDATE SET status=excluded.status,last_success=excluded.last_success,details_json=excluded.details_json`,
    status,at,string(details));err!=nil{return}
 if err=db.exec("COMMIT");err!=nil{return}
 committed=true
 return
}

func (db *DB) recordMDNSFailure(at string,problem error) error {
 db.mu.Lock()
 defer db.mu.Unlock()
 msg:=problem.Error()
 if len(msg)>240 {msg=msg[:240]}
 data,_:=json.Marshal(map[string]string{"error":msg,"observed_at":at})
 return db.run(`INSERT INTO sources(id,kind,status,last_success,details_json)
 VALUES('mDNS / Bonjour','mdns','error',NULL,?)
 ON CONFLICT(id) DO UPDATE SET status=excluded.status,details_json=excluded.details_json`,string(data))
}
func (db *DB) mdnsSourceRecordsLocked() ([]MDNSRecord,[]MDNSServiceRecord,[]MDNSUnmatched,error) {
 hosts:=make([]MDNSRecord,0)
 services:=make([]MDNSServiceRecord,0)
 unmatched:=make([]MDNSUnmatched,0)
 _,err:=db.prepared(`SELECT device_id,hostname,ipv4,last_seen FROM mdns_hosts ORDER BY device_id`,nil,
 func(s *C.sqlite3_stmt){hosts=append(hosts,MDNSRecord{DeviceID:field(s,0),Hostname:field(s,1),IPv4:field(s,2),LastSeen:field(s,3)})})
 if err!=nil{return nil,nil,nil,err}
 _,err=db.prepared(`SELECT device_id,instance,type,port,target,last_seen FROM mdns_services
 ORDER BY device_id,type,instance`,nil,
 func(s *C.sqlite3_stmt){
  services=append(services,MDNSServiceRecord{DeviceID:field(s,0),Instance:field(s,1),
   Type:field(s,2),Port:uint16(C.sqlite3_column_int(s,3)),
   Target:field(s,4),LastSeen:field(s,5)})
 })
 if err!=nil{return nil,nil,nil,err}
 _,err=db.prepared(`SELECT hostname,ipv4,last_seen,reason FROM mdns_unmatched ORDER BY last_seen DESC LIMIT 100`,nil,
 func(s *C.sqlite3_stmt){unmatched=append(unmatched,MDNSUnmatched{
  Hostname:field(s,0),IPv4:field(s,1),LastSeen:field(s,2),Reason:field(s,3)})})
 return hosts,services,unmatched,err
}
