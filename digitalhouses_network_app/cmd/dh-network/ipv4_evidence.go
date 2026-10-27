package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "sort"
 "time"
)

// IPv4Evidence holds a claim and its provenance, never conflating a router
// reported IP with an on-link ARP response. Source is "ha_router" or "arp".
type IPv4Evidence struct {
 DeviceID string `json:"device_id"`
 MAC string `json:"mac"`
 IPv4 string `json:"ipv4"`
 Source string `json:"source"`
 Reference string `json:"reference,omitempty"`
 State string `json:"state"`
 FirstSeen string `json:"first_seen"`
 LastSeen string `json:"last_seen"`
}
type IPv4Conflict struct {
 IPv4 string `json:"ipv4"`
 Claims []IPv4Evidence `json:"claims"`
 WinnerDeviceID string `json:"winner_device_id,omitempty"`
 WinnerSource string `json:"winner_source,omitempty"`
 Resolution string `json:"resolution"`
}
type IPv4Resolution struct {
 Addresses map[string]string
 Conflicts []IPv4Conflict
}

// Call only with db.mu held; this is an upsert, not a replacement of past claims.
func (db *DB) storeIPv4Evidence(id, source, reference, ip, state, at string) error {
 if ip=="" {return nil}
 return db.run(`INSERT INTO ipv4_evidence(device_id,source,reference,ipv4,state,first_seen,last_seen)
 VALUES(?,?,?,?,?,?,?) ON CONFLICT(device_id,source,reference,ipv4)
 DO UPDATE SET state=excluded.state,last_seen=excluded.last_seen`,id,source,reference,ip,state,at,at)
}

func (db *DB) ipv4EvidenceLocked() ([]IPv4Evidence,error) {
 result:=make([]IPv4Evidence,0)
 _,err:=db.prepared(`SELECT e.device_id,d.mac,e.ipv4,e.source,e.reference,e.state,e.first_seen,e.last_seen
 FROM ipv4_evidence e JOIN devices d ON d.id=e.device_id
 ORDER BY e.device_id,e.source,e.reference,e.ipv4`,nil,func(stmt *C.sqlite3_stmt){
    result=append(result,IPv4Evidence{
      DeviceID:field(stmt,0), MAC:field(stmt,1), IPv4:field(stmt,2),
      Source:field(stmt,3),Reference:field(stmt,4),State:field(stmt,5),
      FirstSeen:field(stmt,6),LastSeen:field(stmt,7)})
 })
 return result,err
}
func (db *DB) evidenceWindows() (time.Duration,time.Duration) {
 arp:=db.lanFreshness
 if arp<=0 {arp=420*time.Second}
 ha:=db.haFreshness
 if ha<=0 {ha=180*time.Second}
 return arp,ha
}
func evidenceRank(item IPv4Evidence) int {
 if item.Source=="arp" && item.State=="observed" {return 2}
 if item.Source=="ha_router" && item.State=="home" {return 1}
 return 0
}
func validEvidence(item IPv4Evidence,now time.Time,arpTTL,haTTL time.Duration) bool {
 rank:=evidenceRank(item)
 if rank==0 || item.DeviceID=="" || normalizedIP(item.IPv4,false)=="" {return false}
 seen,err:=time.Parse(time.RFC3339,item.LastSeen)
 if err!=nil {return false}
 age:=now.Sub(seen)
 if age<0 {return false}
 if rank==2 {return age<=arpTTL}
 return age<=haTTL
}
func preferClaim(a,b IPv4Evidence) bool {
 if evidenceRank(a)!=evidenceRank(b) {return evidenceRank(a)>evidenceRank(b)}
 if a.LastSeen!=b.LastSeen {return a.LastSeen>b.LastSeen}
 if a.DeviceID!=b.DeviceID {return a.DeviceID<b.DeviceID}
 return a.Reference<b.Reference
}

// A current IPv4 must have a fresh positive source claim. When different MACs
// claim the same IP, a fresh ARP response wins. Ambiguous equally authoritative
// ARP answers are withheld; all claims survive for diagnosis.
func resolveIPv4Evidence(evidence []IPv4Evidence,at string,arpTTL,haTTL time.Duration) IPv4Resolution {
 output:=IPv4Resolution{Addresses:map[string]string{},Conflicts:make([]IPv4Conflict,0)}
 now,err:=time.Parse(time.RFC3339,at)
 if err!=nil {return output}
 grouped:=map[string][]IPv4Evidence{}
 for _,e:=range evidence {
   if validEvidence(e,now,arpTTL,haTTL) {grouped[e.IPv4]=append(grouped[e.IPv4],e)}
 }
 keys:=make([]string,0,len(grouped))
 for ip:=range grouped {keys=append(keys,ip)}
 sort.Strings(keys)
 chosenByDevice:=map[string]IPv4Evidence{}
 for _,ip:=range keys {
   claims:=grouped[ip]
   sort.Slice(claims,func(i,j int)bool{return preferClaim(claims[i],claims[j])})
   best:=claims[0]
   // Multiple records for the same device do not constitute an IP conflict.
   different:=false
   for _,candidate:=range claims[1:] {if candidate.DeviceID!=best.DeviceID {different=true;break}}
   ambiguous:=false
   for _,candidate:=range claims[1:] {
     if candidate.DeviceID!=best.DeviceID &&
        evidenceRank(candidate)==evidenceRank(best) &&
        candidate.LastSeen==best.LastSeen {ambiguous=true;break}
   }
   if different {
     conflict:=IPv4Conflict{IPv4:ip,Claims:claims,Resolution:"arp_over_router"}
     if !ambiguous {
       conflict.WinnerDeviceID=best.DeviceID
       conflict.WinnerSource=best.Source
       if best.Source=="ha_router" {conflict.Resolution="newest_router_claim"}
       if best.Source=="arp" && evidenceRank(claims[1])==2 {conflict.Resolution="newest_arp_claim"}
     } else {conflict.Resolution="ambiguous_equal_evidence"}
     output.Conflicts=append(output.Conflicts,conflict)
   }
   if ambiguous {continue}
   previous,found:=chosenByDevice[best.DeviceID]
   if !found || preferClaim(best,previous) {
     chosenByDevice[best.DeviceID]=best
   }
 }
 for id,chosen:=range chosenByDevice {output.Addresses[id]=chosen.IPv4}
 return output
}

// In the same writer transaction as source observations, refresh all display
// addresses using evidence. Empty means "no verified current mapping";
// historical identities and notes are not changed.
func (db *DB) reconcileIPv4Locked(now string) ([]IPv4Conflict,error) {
 evidence,err:=db.ipv4EvidenceLocked()
 if err!=nil{return nil,err}
 arp,ha:=db.evidenceWindows()
 resolved:=resolveIPv4Evidence(evidence,now,arp,ha)
 if err:=db.run("UPDATE devices SET ipv4='' WHERE ipv4<>''");err!=nil{return nil,err}
 ids:=make([]string,0,len(resolved.Addresses))
 for id:=range resolved.Addresses {ids=append(ids,id)}
 sort.Strings(ids)
 for _,id:=range ids {
   if err:=db.run("UPDATE devices SET ipv4=? WHERE id=?",resolved.Addresses[id],id);err!=nil{return nil,err}
 }
 return resolved.Conflicts,nil
}
