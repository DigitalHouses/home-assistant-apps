package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "encoding/json"
 "errors"
 "fmt"
 "net/netip"
 "time"
)

// LocalInterfaceObservation comes from the OS-selected default IPv4 LAN
// interface, not an ARP response or an HA Router device_tracker. It may
// legitimately be missing from a scan (hosts do not ARP-probe themselves).
type LocalInterfaceObservation struct {
 MAC string
 IPv4 string
 Interface string
 Prefix string
}
func localInterfaceFromPlan(plan lanTarget) LocalInterfaceObservation {
 return LocalInterfaceObservation{MAC:plan.iface.HardwareAddr.String(),IPv4:plan.address.String(),Interface:plan.iface.Name,Prefix:plan.network.String()}
}
func (db *DB) importLocalInterface(o LocalInterfaceObservation,now string) (err error) {
 mac:=normalizedMAC(o.MAC)
 ip:=normalizedIP(o.IPv4,false)
 parsedIP,parseErr:=netip.ParseAddr(ip)
 if mac=="" || ip=="" || parseErr!=nil || !parsedIP.IsPrivate() || o.Interface=="" || len(o.Interface)>64 {
  return errors.New("invalid local interface observation")
 }
 prefix,parseErr:=netip.ParsePrefix(o.Prefix)
 if parseErr!=nil || !prefix.Contains(parsedIP) || !prefix.IsValid(){return errors.New("invalid local LAN prefix")}
 db.mu.Lock()
 defer db.mu.Unlock()
 if err=db.exec("BEGIN IMMEDIATE");err!=nil{return err}
 completed:=false
 defer func(){if !completed {_=db.exec("ROLLBACK")}}()
 id,err:=db.lookupIdentity("mac",mac)
 if err!=nil {return err}
 if id=="" {
  id,err=freshDeviceID()
  if err!=nil{return err}
  // An IP or a guessed hostname alone must never merge identities.
  if err=db.run("INSERT INTO devices(id,display_name,hostname,mac,ipv4,ipv6,presence,first_seen,last_seen,note) VALUES(?,'','',?,?,'','online',?,?,'')",
    id,mac,ip,now,now);err!=nil{return err}
 }else {
  // Local interface is a strong positive observation. Keep all existing names,
  // notes, UUID and historical identities untouched.
  if err=db.run("UPDATE devices SET mac=?,ipv4=?,presence='online',last_seen=? WHERE id=?",mac,ip,now,id);err!=nil{return err}
 }
 if err=db.storeIdentity(id,"mac",mac,now);err!=nil{return err}
 if err=db.storeIdentity(id,"ipv4",ip,now);err!=nil{return err}
 // Keep any historical interface IP while revoking only this source's
 // previous address assignments for the same MAC-backed device.
 if err=db.run("UPDATE ipv4_evidence SET state='previous' WHERE device_id=? AND source='local_interface'",id);err!=nil{return err}
 if err=db.storeIPv4Evidence(id,"local_interface",o.Interface,ip,"observed",now);err!=nil{return err}
 if err=db.run("INSERT INTO lan_positive(device_id,last_seen) VALUES(?,?) ON CONFLICT(device_id) DO UPDATE SET last_seen=excluded.last_seen",id,now);err!=nil{return err}
 if _,err=db.reconcileIPv4Locked(now);err!=nil{return err}
 info,_:=json.Marshal(map[string]string{
  "interface":o.Interface,"ipv4":ip,"mac":mac,"subnet":prefix.String(),
  "evidence":"os_default_route_interface","identity":"mac_only",
 })
 if err=db.run("INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('Local Interface','local_interface','ok',?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,last_success=excluded.last_success,details_json=excluded.details_json",
    now,string(info));err!=nil{return err}
 if err=db.exec("COMMIT");err!=nil{return err}
 completed=true
 return nil
}
func (db *DB) recordLocalInterfaceFailure(at string,issue error) error {
 db.mu.Lock()
 defer db.mu.Unlock()
 message:=issue.Error()
 if len(message)>200 {message=message[:200]}
 payload,_:=json.Marshal(map[string]any{"error":message,"observed_at":at})
 return db.run("INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('Local Interface','local_interface','error',NULL,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,details_json=excluded.details_json",string(payload))
}
func (s *Service) recordLocalInterface(plan lanTarget) {
 now:=time.Now().UTC().Format(time.RFC3339)
 if err:=s.db.importLocalInterface(localInterfaceFromPlan(plan),now);err!=nil {
  // Local interface errors must never stop ARP discovery or other scanners.
  err=fmt.Errorf("local interface registration: %w",err)
  if sourceErr:=s.db.recordLocalInterfaceFailure(now,err);sourceErr!=nil {
   // pollLAN will still continue; error is visible via LAN diagnostics.
   return
  }
 }
}
