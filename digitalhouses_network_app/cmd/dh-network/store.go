package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
#include <stdlib.h>
static int dh_store_bind(sqlite3_stmt *stmt, int pos, const char *value) {
    return sqlite3_bind_text(stmt, pos, value, -1, SQLITE_TRANSIENT);
}
*/
import "C"

import (
    "crypto/rand"
    "encoding/hex"
    "encoding/json"
    "errors"
    "fmt"
    "strings"
    "unsafe"
)

type SourceInfo struct {
    Name string `json:"name"`
    Kind string `json:"kind"`
    Status string `json:"status"`
    LastSuccess string `json:"last_success"`
    DetailsJSON string `json:"details_json"`
}

func (db *DB) sources() ([]SourceInfo,error) {
    records:=make([]SourceInfo,0)
    err:=db.query("SELECT id,kind,status,COALESCE(last_success,''),details_json FROM sources ORDER BY id",
        func(stmt *C.sqlite3_stmt) {
            records=append(records,SourceInfo{field(stmt,0),field(stmt,1),field(stmt,2),field(stmt,3),field(stmt,4)})
        })
    return records,err
}

// These helpers are only used while db.mu is held.
func (db *DB) prepared(sql string,args []string,each func(*C.sqlite3_stmt)) (int,error) {
    cs:=C.CString(sql)
    defer C.free(unsafe.Pointer(cs))
    var stmt *C.sqlite3_stmt
    if C.sqlite3_prepare_v2(db.connection,cs,-1,&stmt,nil)!=C.SQLITE_OK {
        return 0,errors.New(C.GoString(C.sqlite3_errmsg(db.connection)))
    }
    defer C.sqlite3_finalize(stmt)
    for i,arg:=range args {
        val:=C.CString(arg)
        result:=C.dh_store_bind(stmt,C.int(i+1),val)
        C.free(unsafe.Pointer(val))
        if result!=C.SQLITE_OK { return 0, errors.New("SQLite bind failed") }
    }
    count:=0
    for {
        switch C.sqlite3_step(stmt) {
        case C.SQLITE_ROW:
            count++
            if each!=nil { each(stmt) }
        case C.SQLITE_DONE:
            return count,nil
        default:
            return count,errors.New(C.GoString(C.sqlite3_errmsg(db.connection)))
        }
    }
}

func (db *DB) run(sql string,args ...string) error {
    _,err:=db.prepared(sql,args,nil)
    return err
}

func (db *DB) lookupIdentity(kind,value string) (string,error) {
    if value=="" { return "",nil }
    id:=""
    _,err:=db.prepared("SELECT device_id FROM identities WHERE kind=? AND value=? LIMIT 1",
        []string{kind,value},func(stmt *C.sqlite3_stmt){id=field(stmt,0)})
    return id,err
}

func (db *DB) readDevice(id string) (Device,error) {
    var device Device
    _,err:=db.prepared("SELECT id,display_name,hostname,mac,ipv4,ipv6,presence,first_seen,last_seen,note FROM devices WHERE id=?",
        []string{id},func(stmt *C.sqlite3_stmt){
            device=Device{field(stmt,0),field(stmt,1),field(stmt,2),field(stmt,3),field(stmt,4),field(stmt,5),field(stmt,6),field(stmt,7),field(stmt,8),field(stmt,9)}
        })
    if err==nil && device.ID=="" { return device,fmt.Errorf("missing registered device %s",id) }
    return device,err
}

func freshDeviceID() (string,error) {
    bytes:=make([]byte,16)
    if _,err:=rand.Read(bytes);err!=nil{return "",err}
    bytes[6]=(bytes[6]&0x0f)|0x40
    bytes[8]=(bytes[8]&0x3f)|0x80
    h:=hex.EncodeToString(bytes)
    return h[:8]+"-"+h[8:12]+"-"+h[12:16]+"-"+h[16:20]+"-"+h[20:],nil
}

func keep(previous,newValue string) string {
    if newValue!="" {return newValue}
    return previous
}

func (db *DB) storeIdentity(id,kind,value,now string) error {
    if value=="" {return nil}
    return db.run("INSERT INTO identities(device_id,kind,value,first_seen,last_seen) VALUES(?,?,?,?,?) ON CONFLICT(device_id,kind,value) DO UPDATE SET last_seen=excluded.last_seen",
        id,kind,value,now,now)
}

// An HA source snapshot is applied atomically. Duplicate IP addresses are never
// used as an identity; MAC and stable HA entity ID are the only join keys.
func (db *DB) importRouterTrackers(trackers []RouterTracker,now string) error {
    db.mu.Lock()
    defer db.mu.Unlock()
    if err:=db.exec("BEGIN IMMEDIATE");err!=nil{return err}
    done:=false
    defer func(){if !done {_=db.exec("ROLLBACK")}}()
    imported,online,notObserved,unknown,conflicts:=0,0,0,0,0
    cycleRank:=map[string]int{}
    for _,t:=range trackers {
        if t.EntityID=="" {return errors.New("router tracker entity_id missing")}
        byEntity,err:=db.lookupIdentity("ha_entity",t.EntityID)
        if err!=nil{return err}
        byMAC,err:=db.lookupIdentity("mac",t.MAC)
        if err!=nil{return err}
        if byEntity!="" && byMAC!="" && byEntity!=byMAC {
            // Conflicting authoritative identifiers must not silently merge hosts.
            conflicts++
            continue
        }
        id:=byEntity
        if id=="" {id=byMAC}
        if id=="" {
            // An absent or unavailable router tracker is not a discovered host.
            // Otherwise an aged-out device would be recreated on every poll.
            if t.State!="home" {
                imported++
                if t.State=="not_home" {notObserved++} else {unknown++}
                continue
            }
            id,err=freshDeviceID()
            if err!=nil{return err}
            firstLast:=""
            if t.State=="home" {firstLast=now}
            initial:="unknown"
            if t.State=="home" {initial="online"}
            if t.State=="not_home" {initial="not_observed"}
            if err=db.run("INSERT INTO devices(id,display_name,hostname,mac,ipv4,ipv6,presence,first_seen,last_seen,note) VALUES(?,?,?,?,?,?,?,?,?,'')",
                id,t.Name,t.Hostname,t.MAC,t.IPv4,t.IPv6,initial,now,firstLast);err!=nil{return err}
        } else {
            old,readErr:=db.readDevice(id)
            if readErr!=nil{return readErr}
            status:=old.Presence
            seen:=old.LastSeen
            rank:=1
            if t.State=="not_home" {rank=2}
            if t.State=="home" {rank=3}
            if rank>=cycleRank[id] {
                switch t.State {
                case "home": status="online";seen=now
                case "not_home": status="not_observed"
                case "unavailable","unknown": status="unknown"
                }
                cycleRank[id]=rank
            }
            // A fresh direct ARP response is stronger than a negative or
            // unavailable router report, including the router's stale IP.
            lanFresh,err:=db.lanRecentlySeen(id,now)
            if err!=nil{return err}
            if lanFresh && t.State!="home" {
                status="online"
                seen=old.LastSeen
                t.IPv4=""
                t.IPv6=""
            }
            if err=db.run("UPDATE devices SET display_name=?,hostname=?,mac=?,ipv4=?,ipv6=?,presence=?,last_seen=? WHERE id=?",
                keep(old.DisplayName,t.Name),keep(old.Hostname,t.Hostname),keep(old.MAC,t.MAC),
                keep(old.IPv4,t.IPv4),keep(old.IPv6,t.IPv6),status,seen,id);err!=nil{return err}
        }
        if _,ok:=cycleRank[id]; !ok {
            rank:=1
            if t.State=="not_home" {rank=2}
            if t.State=="home" {rank=3}
            cycleRank[id]=rank
        }
        if err=db.storeIdentity(id,"ha_entity",t.EntityID,now);err!=nil{return err}
        if t.State=="home" {if err=db.markDeviceBirthSource(id,"ha_device_tracker");err!=nil{return err}}
        if err=db.storeIdentity(id,"mac",t.MAC,now);err!=nil{return err}
        if err=db.storeIdentity(id,"ipv4",t.IPv4,now);err!=nil{return err}
        // Revoke a prior current claim from this exact router tracker before
        // storing a new state/IP. Historical values remain in both tables.
        if err=db.run("UPDATE ipv4_evidence SET state='previous' WHERE device_id=? AND source='ha_router' AND reference=?",
            id,t.EntityID);err!=nil{return err}
        if err=db.storeIPv4Evidence(id,"ha_router",t.EntityID,t.IPv4,t.State,now);err!=nil{return err}
        if err=db.storeIdentity(id,"ipv6",t.IPv6,now);err!=nil{return err}
        imported++
        switch t.State {
        case "home":online++
        case "not_home":notObserved++
        default:unknown++
        }
    }
    ipConflicts,err:=db.reconcileIPv4Locked(now)
    if err!=nil{return err}
    details,_:=json.Marshal(map[string]int{"trackers":len(trackers),"imported":imported,"home":online,"not_home":notObserved,"unknown":unknown,"conflicts":conflicts,"ipv4_conflicts":len(ipConflicts)})
    status:="ok"
    if len(trackers)==0 {status="empty"}
    if conflicts>0 {status="degraded"}
    for _,conflict:=range ipConflicts {if disagreementClassification(conflict)!="source_disagreement" {status="degraded"}}
    if err:=db.run("INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('Home Assistant router trackers','ha_device_tracker',?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,last_success=excluded.last_success,details_json=excluded.details_json",
        status,now,string(details));err!=nil{return err}
    if err:=db.exec("COMMIT");err!=nil{return err}
    done=true
    return nil
}

func (db *DB) recordSourceFailure(now,message string) error {
    db.mu.Lock()
    defer db.mu.Unlock()
    if len(message)>300 {message=message[:300]}
    detail,_:=json.Marshal(map[string]string{"error":strings.TrimSpace(message),"observed_at":now})
    return db.run("INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('Home Assistant router trackers','ha_device_tracker','error',NULL,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,details_json=excluded.details_json",string(detail))
}
