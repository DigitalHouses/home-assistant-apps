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
    "strings"
    "time"
)

// LAN positive evidence has its own freshness timestamp; it must not be
// overwritten merely because an HA router integration reports not_home.
func (db *DB) lanRecentlySeen(id, now string) (bool, error) {
    var seen string
    _,err:=db.prepared("SELECT last_seen FROM lan_positive WHERE device_id=?",
        []string{id},func(stmt *C.sqlite3_stmt){ seen=field(stmt,0) })
    if err!=nil || seen=="" {return false,err}
    latest,err:=time.Parse(time.RFC3339,seen)
    if err!=nil {return false,fmt.Errorf("invalid stored LAN timestamp: %w",err)}
    point,err:=time.Parse(time.RFC3339,now)
    if err!=nil {return false,err}
    ttl:=db.lanFreshness
    if ttl==0 {ttl=420*time.Second}
    age:=point.Sub(latest)
    return age>=0 && age<=ttl,nil
}

func (db *DB) importARPHosts(hosts []LANHost, now, interfaceName, prefix string) error {
    db.mu.Lock()
    defer db.mu.Unlock()
    if err:=db.exec("BEGIN IMMEDIATE");err!=nil{return err}
    success:=false
    defer func(){if !success {_=db.exec("ROLLBACK")}}()
    // One MAC mapping to multiple IPv4 targets during one scan can be a proxy
    // ARP router. Do not merge those addresses into a single real host.
    counts:=map[string]int{}
    for _,host:=range hosts { counts[host.MAC]++ }
    imported,collisions:=0,0
    for _,host:=range hosts {
        mac:=normalizedMAC(host.MAC)
        ipv4:=normalizedIP(host.IPv4,false)
        if mac=="" || ipv4=="" {return errors.New("invalid ARP observation")}
        if counts[host.MAC]>1 {collisions++;continue}
        id,err:=db.lookupIdentity("mac",mac)
        if err!=nil{return err}
        if id=="" {
            id,err=freshDeviceID()
            if err!=nil{return err}
            if err:=db.run("INSERT INTO devices(id,display_name,hostname,mac,ipv4,ipv6,presence,first_seen,last_seen,note) VALUES(?,?, '',?,?,'','online',?,?,'')",
                id,mac,mac,ipv4,now,now);err!=nil{return err}
        }else{
            // Never replace a user-visible router name or user Note.
            if err:=db.run("UPDATE devices SET mac=?,ipv4=?,presence='online',last_seen=? WHERE id=?",
                mac,ipv4,now,id);err!=nil{return err}
        }
        if err:=db.storeIdentity(id,"mac",mac,now);err!=nil{return err}
        if err:=db.storeIdentity(id,"ipv4",ipv4,now);err!=nil{return err}
        if err:=db.run("INSERT INTO lan_positive(device_id,last_seen) VALUES(?,?) ON CONFLICT(device_id) DO UPDATE SET last_seen=excluded.last_seen",
            id,now);err!=nil{return err}
        imported++
    }
    // Expire presence only for LAN-only hosts after two missed scan windows.
    // HA router devices have their own independent source of positive evidence.
    point,err:=time.Parse(time.RFC3339,now)
    if err!=nil{return err}
    expiry:=db.lanFreshness
    if expiry==0 {expiry=420*time.Second}
    cutoff:=point.Add(-expiry).Format(time.RFC3339)
    if err:=db.run(`UPDATE devices SET presence='not_observed'
      WHERE presence='online'
      AND id IN (SELECT device_id FROM lan_positive WHERE last_seen < ?)
      AND NOT EXISTS (SELECT 1 FROM identities WHERE device_id=devices.id AND kind='ha_entity')`,
      cutoff);err!=nil{return err}
    status:="ok"
    if len(hosts)==0 {status="empty"}
    if collisions>0 {status="degraded"}
    details,_:=json.Marshal(map[string]any{
        "observations":len(hosts),"imported":imported,"ambiguous_proxy_arp":collisions,
        "interface":interfaceName,"subnet":prefix,"discovery":"active_arp",
    })
    if err:=db.run("INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('LAN ARP','lan_arp',?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,last_success=excluded.last_success,details_json=excluded.details_json",
        status,now,string(details));err!=nil{return err}
    if err:=db.exec("COMMIT");err!=nil{return err}
    success=true
    return nil
}

func (db *DB) recordLANFailure(at string,problem error) error {
    db.mu.Lock()
    defer db.mu.Unlock()
    msg:=problem.Error()
    if len(msg)>240 {msg=msg[:240]}
    details,_:=json.Marshal(map[string]string{"error":strings.TrimSpace(msg),"observed_at":at})
    return db.run("INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('LAN ARP','lan_arp','error',NULL,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,details_json=excluded.details_json",
        string(details))
}
